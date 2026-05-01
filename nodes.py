import os
import time
import base64
import io
import tempfile
import re
import json
import hashlib
import requests
import numpy as np
from PIL import Image

try:
    import torch
except ImportError:
    torch = None

import folder_paths

try:
    from comfy_api.latest import io as comfy_io, ui as comfy_ui
except ImportError:
    comfy_io = None
    comfy_ui = None



# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _tensor_to_b64(tensor):
    """ComfyUI IMAGE tensor (B, H, W, C float32 0-1) → PNG data URI."""
    img_np = (tensor[0].numpy() * 255).clip(0, 255).astype(np.uint8)
    pil = Image.fromarray(img_np).convert("RGB")
    buf = io.BytesIO()
    pil.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()



def _find_ci(obj, *keys):
    """Return the first matching dict value using case-insensitive key lookup."""
    if not isinstance(obj, dict):
        return None
    lowered = {str(k).lower(): v for k, v in obj.items()}
    for key in keys:
        val = lowered.get(str(key).lower())
        if val not in (None, ""):
            return val
    return None


def _walk_dicts(root, max_depth=6):
    """Yield nested dicts breadth-first so polling can tolerate schema drift."""
    if not isinstance(root, dict):
        return

    queue = [(root, 0)]
    seen = set()

    while queue:
        current, depth = queue.pop(0)
        current_id = id(current)
        if current_id in seen:
            continue
        seen.add(current_id)
        yield current

        if depth >= max_depth:
            continue

        for value in current.values():
            if isinstance(value, dict):
                queue.append((value, depth + 1))
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        queue.append((item, depth + 1))


def _extract_poll_fields(body):
    """Extract status/video URL from AnyFast poll responses with loose schema handling."""
    status = ""
    video_url = ""
    progress = ""

    for candidate in _walk_dicts(body):
        if not status:
            found_status = _find_ci(candidate, "status", "state")
            if found_status not in (None, ""):
                status = str(found_status).strip().lower()

        if not progress:
            found_progress = _find_ci(candidate, "progress")
            if found_progress not in (None, ""):
                progress = str(found_progress).strip()

        if not video_url:
            found_url = _find_ci(
                candidate,
                "video_url",
                "url",
                "result_url",
                "resultUrl",
                "videoUrl",
            )
            if found_url not in (None, ""):
                video_url = str(found_url).strip()

        if status and video_url:
            break

    return status, video_url, progress


def _poll_v2(base_url, api_key, task_id, timeout=1200, interval=5):
    """Poll Seedance 2.0 task until completion."""
    headers  = {"Authorization": f"Bearer {api_key}"}
    url      = f"{base_url}/v1/video/generations/{task_id}"
    deadline = time.time() + timeout
    _first   = True

    time.sleep(3)

    while time.time() < deadline:
        r    = requests.get(url, headers=headers, timeout=30)
        r.raise_for_status()
        body = r.json()

        if _first:
            print(f"[Seedance] Poll response keys: {list(body.keys())}")
            _first = False

        status, video_url, progress = _extract_poll_fields(body)

        progress_label = progress or "?"
        print(f"[Seedance] task_id={task_id}  status={status}  progress={progress_label}  video_url={'yes' if video_url else 'no'}")

        if status in ("completed", "succeeded", "success") or (not status and video_url):
            if not video_url:
                raise RuntimeError(f"Status=completed but no video_url in response: {body}")
            return video_url
        if status in ("failed", "error", "failure", "cancelled", "canceled", "rejected", "aborted") or "fail" in status:
            print(f"[Seedance] Full failure response body: {body}")
            message = None
            if isinstance(body, dict):
                data = _find_ci(body, "data", "result")
                if isinstance(data, dict):
                    # fail_reason is the actual AnyFast failure field
                    message = _find_ci(data, "fail_reason", "failReason", "error", "message")
                message = message or _find_ci(body, "error", "message")
            msg_str = str(message or body)
            if "PrivacyInformation" in msg_str or "SensitiveContent" in msg_str or "real people" in msg_str.lower():
                raise RuntimeError(
                    "AnyFast rejected the image: real-person face detected.\n"
                    "Use the SeedanceUploadAsset node to upload the image as an asset first,\n"
                    "then connect it via SeedanceAssetRef instead of sending base64 directly."
                )
            raise RuntimeError(f"Seedance generation failed: {msg_str}")

        time.sleep(interval)

    raise TimeoutError(f"Seedance timed out after {timeout}s (task_id={task_id})")


def _first_frame(video_url):
    """Download video and extract its first frame as a ComfyUI IMAGE tensor (B,H,W,C float32).
    Requires opencv-python. Falls back to a 64×64 black image on any failure."""
    try:
        import cv2
    except ImportError:
        print("[Seedance] opencv-python not installed — first_frame output will be blank. "
              "Run: pip install opencv-python")
        return _blank_frame()

    tmp_path = None
    try:
        r = requests.get(video_url, timeout=120, stream=True)
        r.raise_for_status()
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            for chunk in r.iter_content(chunk_size=65536):
                tmp.write(chunk)
            tmp_path = tmp.name

        cap = cv2.VideoCapture(tmp_path)
        ok, frame = cap.read()
        cap.release()

        if not ok:
            raise ValueError("cv2 could not read a frame from the video")

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        arr = rgb.astype(np.float32) / 255.0          # H, W, C
        if torch is not None:
            return torch.from_numpy(arr).unsqueeze(0)  # 1, H, W, C
        return np.expand_dims(arr, 0)                  # fallback: numpy
    except Exception as e:
        print(f"[Seedance] first_frame extraction failed: {e}")
        return _blank_frame()
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


def _blank_frame():
    """Return a 1×64×64×3 black tensor as a placeholder first frame."""
    arr = np.zeros((1, 64, 64, 3), dtype=np.float32)
    if torch is not None:
        return torch.from_numpy(arr)
    return arr


def _is_anyfast_asset_not_ready_error(response_text):
    txt = str(response_text or "").lower()
    # Older AnyFast error pattern
    if (
        "fail_to_fetch_task" in txt
        and "invalidparameter" in txt
        and "asset" in txt
        and "not found" in txt
    ):
        return True
    # Generation endpoint: "The specified asset <id> is not found"
    if "specified asset" in txt and "not found" in txt:
        return True
    return False


def _payload_uses_anyfast_assets(payload):
    """Return True if the generation payload references any asset:// URI."""
    content = payload.get("content") or []
    for entry in content:
        if not isinstance(entry, dict):
            continue
        url = (
            entry.get("image_url", {}).get("url")
            or entry.get("video_url", {}).get("url")
            or entry.get("audio_url", {}).get("url")
        )
        if isinstance(url, str) and url.lower().startswith("asset://"):
            return True
    return False


def _submit_and_poll(api, payload):
    base_url = api["base_url"].rstrip("/")
    api_key  = api["api_key"].strip()

    if not api_key:
        raise ValueError("API key is empty — paste your AnyFast key in the Seedance API Key node.")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    uses_assets = _payload_uses_anyfast_assets(payload)
    r = None
    max_attempts = 12 if uses_assets else 8
    retry_delay = 10 if uses_assets else 8
    for attempt in range(1, max_attempts + 1):
        try:
            r = requests.post(
                f"{base_url}/v1/video/generations",
                json=payload,
                headers=headers,
                timeout=(30, 600),
            )
        except requests.exceptions.ReadTimeout as e:
            raise RuntimeError(
                "AnyFast did not return a generation task within 600 seconds. "
                "The server may have accepted the job but failed to return the task_id in time, "
                "so this node will not auto-retry the submit to avoid duplicate generations. "
                "Check your AnyFast job history before running again."
            ) from e
        except requests.exceptions.RequestException as e:
            if attempt < max_attempts:
                print(
                    f"[Seedance/AnyFast] Submit request failed with network error: {e}. "
                    f"Retrying in {retry_delay}s (attempt {attempt}/{max_attempts})..."
                )
                time.sleep(retry_delay)
                continue
            raise RuntimeError(f"AnyFast submit request failed: {e}") from e
        if r.ok:
            break
        if r.status_code == 400 and _is_anyfast_asset_not_ready_error(r.text):
            if attempt < max_attempts:
                delay = retry_delay + (attempt - 1) * 2 if uses_assets else retry_delay
                print(
                    f"[Seedance/AnyFast] Asset not yet visible to generation, "
                    f"retrying submit in {delay}s (attempt {attempt}/{max_attempts})..."
                )
                time.sleep(delay)
                continue
        if r.status_code == 400 and ("PrivacyInformation" in r.text or "SensitiveContent" in r.text or "real person" in r.text.lower()):
            raise RuntimeError(
                "AnyFast rejected the image: real-person face detected.\n"
                "Connect the face image to SeedanceFaceRef → anyfast_refs input.\n"
                "Do NOT use SeedanceRefImages (reference_images) for faces — that sends base64 which AnyFast blocks."
            )
        raise RuntimeError(f"Seedance API error {r.status_code}: {r.text}")
    if not r.ok:
        raise RuntimeError(f"Seedance API error {r.status_code}: {r.text}")

    resp_json = r.json()
    print(f"[Seedance] Submit response keys: {list(resp_json.keys()) if isinstance(resp_json, dict) else resp_json}")
    task_id = _extract_id(resp_json, "id", "Id", "task_id", "taskId", "ID")
    print(f"[Seedance] Job submitted — task_id={task_id}")

    video_url = _poll_v2(base_url, api_key, task_id)
    frame     = _first_frame(video_url)
    return video_url, task_id, frame


# --------------------------------------------------------------------------- #
# Asset Management helpers
# --------------------------------------------------------------------------- #

def _extract_id(resp_json, *keys):
    """Try several field name candidates with forgiving key normalization."""
    def _canon(value):
        return re.sub(r"[^a-z0-9]", "", str(value).lower())

    def _lookup(source):
        if not isinstance(source, dict):
            return None

        for k in keys:
            if k in source:
                return source[k]

        canon_map = {_canon(k): v for k, v in source.items()}
        for k in keys:
            ck = _canon(k)
            if ck in canon_map:
                return canon_map[ck]
        return None

    direct = _lookup(resp_json)
    if direct is not None:
        return direct

    nested = resp_json.get("data", {})
    nested_value = _lookup(nested)
    if nested_value is not None:
        return nested_value

    raise RuntimeError(f"Cannot find ID in response (tried {keys}): {resp_json}")


def _extract_optional_id(resp_json, *keys):
    """Best-effort ID lookup that returns None instead of raising."""
    try:
        return _extract_id(resp_json, *keys)
    except RuntimeError:
        return None


def _extract_verify_url(resp_json):
    return (resp_json.get("VerifyUrl") or resp_json.get("verify_url") or
            resp_json.get("data", {}).get("VerifyUrl") or
            resp_json.get("data", {}).get("verify_url"))


def _list_asset_group_type(base_url, headers, group_id):
    """Resolve GroupType for an AnyFast asset group if ListAssets requires it."""
    r = requests.post(
        f"{base_url}/volc/asset/ListAssetGroups",
        json={
            "model": "volc-asset",
            "Filter": {
                "GroupIds": [group_id],
            },
            "PageNumber": 1,
            "PageSize": 10,
        },
        headers=headers,
        timeout=30,
    )
    if not r.ok:
        raise RuntimeError(f"ListAssetGroups failed {r.status_code}: {r.text}")

    body = r.json()
    items = body.get("Items") or body.get("items") or []
    for item in items:
        item_id = _extract_optional_id(item, "Id", "GroupId", "group_id", "id", "ID")
        if item_id != group_id:
            continue
        group_type = _find_ci(item, "GroupType", "group_type")
        if group_type:
            return str(group_type).strip()
    return None


def _validate_anyfast_image_bytes(file_bytes, filename):
    """Validate documented AnyFast image constraints and log useful diagnostics."""
    size_mb = len(file_bytes) / (1024 * 1024)
    if size_mb >= 30:
        raise ValueError(f"Image asset exceeds AnyFast 30 MB limit: {size_mb:.2f} MB ({filename})")

    try:
        with Image.open(io.BytesIO(file_bytes)) as img:
            width, height = img.size
            fmt = (img.format or "").upper()
    except Exception as e:
        raise ValueError(f"Could not inspect image asset {filename}: {e}") from e

    if width < 300 or height < 300 or width > 6000 or height > 6000:
        raise ValueError(
            f"Image asset dimensions {width}x{height} are outside AnyFast limits "
            f"(300–6000 px per side): {filename}"
        )

    ratio = width / float(height)
    if ratio < 0.4 or ratio > 2.5:
        raise ValueError(
            f"Image asset aspect ratio {ratio:.3f} is outside AnyFast limits (0.4–2.5): {filename}"
        )

    print(
        f"[Seedance Assets] Image validated for AnyFast: "
        f"format={fmt or '?'} size={size_mb:.2f}MB dims={width}x{height} ratio={ratio:.3f}"
    )


def _ensure_group(api, group_name, existing_group_id=None):
    """Return existing_group_id if provided, otherwise create a new asset group."""
    if existing_group_id and existing_group_id.strip():
        gid = existing_group_id.strip()
        print(f"[Seedance Assets] Reusing group: {gid}")
        return gid

    base_url = api["base_url"].rstrip("/")
    api_key  = api["api_key"].strip()
    headers  = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    r = requests.post(f"{base_url}/volc/asset/CreateAssetGroup",
                      json={"model": "volc-asset", "Name": group_name},
                      headers=headers, timeout=30)
    if not r.ok:
        raise RuntimeError(f"CreateAssetGroup failed {r.status_code}: {r.text}")

    group_id = _extract_id(r.json(), "Id", "GroupId", "group_id", "id", "ID")
    print(f"[Seedance Assets] Group created: {group_id} — waiting 3s for propagation")
    time.sleep(3)
    return group_id


def _upload_to_temp_host(file_bytes, filename):
    """Upload bytes to a public host and return a URL for AnyFast to fetch.
    Tries Catbox → Litterbox → 0x0.st in order."""
    errors = []

    # Catbox (permanent)
    try:
        r = requests.post(
            "https://catbox.moe/user/api.php",
            data={"reqtype": "fileupload"},
            files={"fileToUpload": (filename, file_bytes)},
            headers={"User-Agent": "comfyui-seedance/1.0"},
            timeout=60,
        )
        r.raise_for_status()
        url = r.text.strip()
        if url.startswith("http"):
            print(f"[Seedance] Uploaded to catbox: {url}")
            return url
        errors.append(f"catbox.moe: unexpected response: {url[:120]}")
    except Exception as e:
        errors.append(f"catbox.moe: {e}")

    # Litterbox (catbox temp service, 24h, different infra)
    try:
        r = requests.post(
            "https://litterbox.catbox.moe/resources/internals/api.php",
            data={"reqtype": "fileupload", "time": "24h"},
            files={"fileToUpload": (filename, file_bytes)},
            headers={"User-Agent": "comfyui-seedance/1.0"},
            timeout=60,
        )
        r.raise_for_status()
        url = r.text.strip()
        if url.startswith("http"):
            print(f"[Seedance] Uploaded to litterbox: {url}")
            return url
        errors.append(f"litterbox: unexpected response: {url[:120]}")
    except Exception as e:
        errors.append(f"litterbox: {e}")

    # 0x0.st (temp, no expiry for small files)
    try:
        r = requests.post(
            "https://0x0.st",
            files={"file": (filename, file_bytes)},
            headers={"User-Agent": "comfyui-seedance/1.0"},
            timeout=60,
        )
        r.raise_for_status()
        url = r.text.strip()
        if url.startswith("http"):
            print(f"[Seedance] Uploaded to 0x0.st: {url}")
            return url
        errors.append(f"0x0.st: unexpected response: {url[:120]}")
    except Exception as e:
        errors.append(f"0x0.st: {e}")

    raise RuntimeError(
        "Temp host upload failed on all endpoints.\n" + "\n".join(errors)
    )


def _upload_asset(api, asset_type, name, group_id=None, image_tensor=None, file_path=None):
    """Upload an image tensor or a local file to Seedance Asset Management.

    Returns (asset_uri, verify_url, resolved_group_id) where verify_url may be
    None if the API does not require a liveness check for this upload."""
    base_url = api["base_url"].rstrip("/")
    api_key  = api["api_key"].strip()
    auth_headers = {"Authorization": f"Bearer {api_key}"}

    mime_map  = {"Image": "image/png",  "Video": "video/mp4",  "Audio": "audio/mpeg"}

    audio_mime = {".mp3": "audio/mpeg", ".wav": "audio/wav", ".ogg": "audio/ogg",
                  ".flac": "audio/flac", ".m4a": "audio/mp4"}
    if asset_type == "Audio" and file_path:
        ext = os.path.splitext(file_path)[1].lower()
        mime_map["Audio"] = audio_mime.get(ext, "audio/mpeg")

    if image_tensor is not None:
        img_np     = (image_tensor[0].numpy() * 255).clip(0, 255).astype(np.uint8)
        pil        = Image.fromarray(img_np).convert("RGB")
        buf        = io.BytesIO()
        pil.save(buf, format="PNG")
        file_bytes = buf.getvalue()
        filename   = f"{name}.png"
    elif file_path and os.path.exists(file_path):
        with open(file_path, "rb") as f:
            file_bytes = f.read()
        filename = os.path.basename(file_path)
    else:
        raise ValueError("Provide either an image input or a valid file_path.")

    if asset_type == "Image":
        _validate_anyfast_image_bytes(file_bytes, filename)

    mime_type = mime_map.get(asset_type, "application/octet-stream")
    model_map = {"Image": "volc-asset", "Video": "volc-asset-video", "Audio": "volc-asset-audio"}
    asset_model = model_map.get(asset_type, "volc-asset")
    r = None
    for attempt in range(1, 4):
        # For Image assets, prefer the documented JSON data-URI flow first.
        # It is the closest match to AnyFast's asset-management examples and
        # avoids multipart-specific backend differences.
        if asset_type == "Image":
            data_uri = f"data:{mime_type};base64,{base64.b64encode(file_bytes).decode('ascii')}"
            json_data = {
                "model": asset_model,
                "Name": name,
                "AssetType": asset_type,
                "URL": data_uri,
            }
            if group_id:
                json_data["GroupId"] = group_id
            r = requests.post(
                f"{base_url}/volc/asset/CreateAsset",
                json=json_data,
                headers={**auth_headers, "Content-Type": "application/json"},
                timeout=60,
            )
            if r.ok:
                break

            txt = r.text.lower()
            if r.status_code in (400, 502) and "group" in txt and ("notfound" in txt or "not found" in txt):
                if attempt < 3:
                    print(f"[Seedance Assets] Group not visible yet after JSON image upload, retrying in 4s (attempt {attempt}/3) ...")
                    time.sleep(4)
                    continue

        data = {
            "model": asset_model,
            "Name": name,
            "AssetType": asset_type,
        }
        if group_id:
            data["GroupId"] = group_id

        r = requests.post(
            f"{base_url}/volc/asset/CreateAsset",
            data=data,
            files={"file": (filename, file_bytes, mime_type)},
            headers=auth_headers,
            timeout=60,
        )
        if r.ok:
            break

        txt = r.text.lower()
        if r.status_code in (400, 502) and "group" in txt and ("notfound" in txt or "not found" in txt):
            if attempt < 3:
                print(f"[Seedance Assets] Group not visible yet, retrying in 4s (attempt {attempt}/3) ...")
                time.sleep(4)
                continue

        raise RuntimeError(f"Asset upload failed {r.status_code}: {r.text}")
    if not r.ok:
        raise RuntimeError(f"Asset upload failed after retries: {r.status_code}: {r.text}")

    resp = r.json()
    raw_id     = _extract_id(resp, "Id", "AssetId", "asset_id", "id", "ID")
    verify_url = _extract_verify_url(resp)
    resolved_group_id = group_id or _extract_optional_id(resp, "GroupId", "group_id", "GroupID")

    if verify_url:
        print(f"[Seedance Assets] *** IDENTITY VERIFICATION REQUIRED ***")
        print(f"[Seedance Assets] Open this link on your phone or browser (< 30 s): {verify_url}")
        if resolved_group_id:
            print(f"[Seedance Assets] After completing the liveness check, save your Group ID: {resolved_group_id}")

    print(f"[Seedance Assets] Asset created: {raw_id} — waiting 5s for propagation")
    time.sleep(5)
    return f"asset://{raw_id}", verify_url, resolved_group_id


def _wait_for_asset_active(api, asset_id, group_id, timeout=300, interval=5):
    """Wait until an AnyFast asset becomes visible and Active in its group.

    ListAssets is polled without GroupType — groups are created without a type
    field, so filtering by GroupType returns nothing."""
    raw_asset_id = str(asset_id or "").strip()
    if raw_asset_id.lower().startswith("asset://"):
        raw_asset_id = raw_asset_id.split("://", 1)[1]
    group_id = str(group_id or "").strip()

    if not raw_asset_id or not group_id:
        raise ValueError("asset_id and group_id are required to verify asset visibility.")

    base_url = api["base_url"].rstrip("/")
    api_key = api["api_key"].strip()
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    deadline = time.time() + timeout
    resolved_group_type = None

    print(f"[Seedance Assets] Waiting for asset {raw_asset_id} to become Active (timeout={timeout}s)...")
    while time.time() < deadline:
        filter_payload = {
            "GroupIds": [group_id],
        }
        if resolved_group_type:
            filter_payload["GroupType"] = resolved_group_type

        r = requests.post(
            f"{base_url}/volc/asset/ListAssets",
            json={
                "model": "volc-asset",
                "Filter": filter_payload,
                "PageNumber": 1,
                "PageSize": 100,
            },
            headers=headers,
            timeout=30,
        )
        if not r.ok:
            txt = r.text or ""
            if (
                resolved_group_type is None
                and "GroupType" in txt
                and "missing" in txt.lower()
            ):
                resolved_group_type = _list_asset_group_type(base_url, headers, group_id)
                if resolved_group_type:
                    print(
                        f"[Seedance Assets] ListAssets requires GroupType; "
                        f"resolved group_id={group_id} GroupType={resolved_group_type}"
                    )
                    continue
            raise RuntimeError(f"ListAssets failed {r.status_code}: {r.text}")

        body = r.json()
        items = body.get("Items") or body.get("items") or []

        if not items:
            print(f"[Seedance Assets] asset_id={raw_asset_id} — group has no assets yet, retrying...")
            time.sleep(interval)
            continue

        found = False
        for item in items:
            item_id = _extract_optional_id(item, "Id", "AssetId", "asset_id", "id", "ID")
            if item_id != raw_asset_id:
                continue
            found = True
            status = str(_find_ci(item, "Status", "status") or "").strip().lower()
            print(f"[Seedance Assets] asset_id={raw_asset_id} group_id={group_id} status={status or '?'}")
            if status == "active":
                return
            break

        if not found:
            print(f"[Seedance Assets] asset_id={raw_asset_id} — not in group list yet ({len(items)} other item(s)), retrying...")

        time.sleep(interval)

    raise RuntimeError(
        "AnyFast asset is not visible/Active yet. "
        f"asset_id={raw_asset_id} group_id={group_id}. "
        "Finish verification if required, wait a bit, then retry."
    )


def _stabilize_anyfast_asset(asset_type):
    """Allow extra backend propagation time after Active for some asset types."""
    settle_delays = {
        "Image": 20,
    }
    delay = settle_delays.get(asset_type, 0)
    if delay > 0:
        print(
            f"[Seedance Assets] Asset reached Active but AnyFast may still be propagating it "
            f"to generation. Waiting {delay}s before continuing..."
        )
        time.sleep(delay)


# --------------------------------------------------------------------------- #
# Asset ID cache — avoids re-uploading the same image on repeated runs
# --------------------------------------------------------------------------- #

def _get_asset_cache_path():
    try:
        cache_dir = folder_paths.get_user_directory()
    except Exception:
        cache_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(cache_dir, "seedance_asset_cache.json")


def _load_asset_cache():
    path = _get_asset_cache_path()
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_asset_cache(cache):
    path = _get_asset_cache_path()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2)
    except Exception as e:
        print(f"[Seedance Assets] Warning: could not save asset cache: {e}")


def _image_asset_cache_key(img_tensor, base_url):
    """SHA-256 of PNG bytes + AnyFast base URL → unique cache key per image+server."""
    img_np = (img_tensor[0].numpy() * 255).clip(0, 255).astype(np.uint8)
    pil    = Image.fromarray(img_np).convert("RGB")
    buf    = io.BytesIO()
    pil.save(buf, format="PNG")
    img_hash = hashlib.sha256(buf.getvalue()).hexdigest()[:24]
    url_hash = hashlib.md5(base_url.encode()).hexdigest()[:8]
    return f"{img_hash}_{url_hash}"


class SeedanceFaceRef:
    """Upload images containing real human faces as AnyFast assets to bypass face moderation.

    Volcano Engine blocks real-person images sent as base64 directly to the generation
    API. This node routes each image through the required asset flow
    (CreateAssetGroup → CreateAsset → wait Active → asset://) so the generation
    request uses asset:// URIs instead of raw base64.

    Asset IDs are cached locally — if you run again with the same images the upload
    is skipped entirely. Use force_reupload to override.

    Roles:
      ref_image_1…9 → style/identity reference (R2V, use @image1…N in prompt,
                       compatible with reference_audio and reference_video)
      first_frame    → video starts literally from this image (I2V, cannot mix
                       with reference_images / audio / video)

    On first use, AnyFast may show a liveness verification link in the console —
    open it on your phone within 30 s. Save the output group_id and reconnect it
    via existing_group_id to skip re-verification on future runs."""

    CATEGORY = "Seedance AM/AnyFast"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "api":        ("SEEDANCE_API",),
                "group_name": ("STRING", {"default": "comfyui-assets"}),
            },
            "optional": {
                "existing_group_id": ("STRING", {"forceInput": True}),
                "force_reupload":    ("BOOLEAN", {"default": False,
                                                   "tooltip": "Force re-upload even if asset IDs are cached locally."}),
                "first_frame":   ("IMAGE",),
                "last_frame":    ("IMAGE",),
                "ref_image_1":   ("IMAGE",),
                "ref_image_2":   ("IMAGE",),
                "ref_image_3":   ("IMAGE",),
                "ref_image_4":   ("IMAGE",),
                "ref_image_5":   ("IMAGE",),
                "ref_image_6":   ("IMAGE",),
                "ref_image_7":   ("IMAGE",),
                "ref_image_8":   ("IMAGE",),
                "ref_image_9":   ("IMAGE",),
                "existing_refs": ("ANYFAST_IMAGE_REFS", {"forceInput": True}),
            }
        }

    RETURN_TYPES  = ("ANYFAST_IMAGE_REFS", "STRING", "STRING")
    RETURN_NAMES  = ("anyfast_refs", "group_id", "asset_ids")
    OUTPUT_NODE   = True
    FUNCTION      = "upload"

    def upload(self, api, group_name, existing_group_id=None, force_reupload=False,
               first_frame=None, last_frame=None,
               ref_image_1=None, ref_image_2=None, ref_image_3=None,
               ref_image_4=None, ref_image_5=None, ref_image_6=None,
               ref_image_7=None, ref_image_8=None, ref_image_9=None,
               existing_refs=None):

        images_with_roles = []
        if first_frame is not None:
            images_with_roles.append((first_frame, "first_frame"))
        if last_frame is not None:
            images_with_roles.append((last_frame, "last_frame"))
        for img in [ref_image_1, ref_image_2, ref_image_3,
                    ref_image_4, ref_image_5, ref_image_6,
                    ref_image_7, ref_image_8, ref_image_9]:
            if img is not None:
                images_with_roles.append((img, "reference_image"))

        if not images_with_roles:
            raise ValueError(
                "Connect at least one image (first_frame, last_frame, or ref_image_1 … ref_image_9) "
                "to SeedanceFaceRef."
            )

        cache    = {} if force_reupload else _load_asset_cache()
        group_id = _ensure_group(api, group_name, existing_group_id)
        refs     = list(existing_refs) if existing_refs else []
        asset_id_list = []

        for idx, (img_tensor, role) in enumerate(images_with_roles):
            cache_key = _image_asset_cache_key(img_tensor, api["base_url"])

            if not force_reupload and cache_key in cache:
                asset_uri = cache[cache_key]["asset_id"]
                print(f"[Seedance Assets] Cache hit — reusing {asset_uri} (role={role}, skipping upload)")
            else:
                asset_name = f"face_{role}_{idx + 1}"
                asset_uri, _verify_url, group_id = _upload_asset(
                    api, "Image", asset_name, group_id, image_tensor=img_tensor
                )
                _wait_for_asset_active(api, asset_uri, group_id)
                _stabilize_anyfast_asset("Image")
                cache[cache_key] = {
                    "asset_id":    asset_uri,
                    "group_id":    group_id,
                    "uploaded_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                }
                _save_asset_cache(cache)

            asset_id_list.append(asset_uri)
            entry = {
                "type":      "image_url",
                "image_url": {"url": asset_uri},
                "role":      role,
            }
            if role in ("first_frame", "last_frame"):
                refs.insert(0, entry)
            else:
                refs.append(entry)

            print(f"[Seedance/AnyFast] Face asset ready: role={role}  url={asset_uri}")

        asset_ids_text = "\n".join(asset_id_list)
        print(f"[Seedance/AnyFast] {len(refs)} face ref(s) ready via asset://")
        ui_text = f"group_id: {group_id}\n{asset_ids_text}" if group_id else asset_ids_text
        return {"ui": {"text": [ui_text]}, "result": (refs, group_id, asset_ids_text)}


class SeedanceAssetRef:
    """Wire an asset:// ID from SeedanceUploadAsset into a generation node.

    Use this after SeedanceUploadAsset to turn the returned asset_id into an
    ANYFAST_IMAGE_REFS entry that the generation node understands.

    Chain multiple SeedanceAssetRef nodes via existing_refs to build a list
    of asset-based references."""

    CATEGORY = "Seedance AM/Advanced"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "asset_id": ("STRING", {"forceInput": True}),
                "role":     (["first_frame", "last_frame", "reference_image"],),
            },
            "optional": {
                "existing_refs": ("ANYFAST_IMAGE_REFS", {"forceInput": True}),
            }
        }

    RETURN_TYPES = ("ANYFAST_IMAGE_REFS",)
    RETURN_NAMES = ("anyfast_refs",)
    FUNCTION     = "build_ref"

    def build_ref(self, asset_id, role, existing_refs=None):
        asset_id = asset_id.strip()
        if asset_id.lower().startswith("asset://"):
            raw = asset_id.split("://", 1)[1]
        else:
            raw = asset_id
        asset_id = f"asset://{raw}"

        entry = {
            "type":      "image_url",
            "image_url": {"url": asset_id},
            "role":      role,
        }

        refs = list(existing_refs) if existing_refs else []
        if role in ("first_frame", "last_frame"):
            refs.insert(0, entry)
        else:
            refs.append(entry)

        print(f"[Seedance/AnyFast] Asset ref: role={role}  url={asset_id}")
        return (refs,)


# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

RES_V2       = ["1080p", "720p", "480p"]
RES_V2_ULTRA = ["2k", "1080p", "720p"]
RATIO_V2     = ["16:9", "9:16", "4:3", "3:4", "1:1", "21:9", "adaptive"]
MAX_DURATION = 15


# --------------------------------------------------------------------------- #
# API Key node
# --------------------------------------------------------------------------- #

class SeedanceApiKey:
    CATEGORY = "Seedance AM/Core"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "api_key":  ("STRING", {"default": "", "multiline": False}),
                "base_url": ("STRING", {"default": "https://www.anyfast.ai", "multiline": False}),
            }
        }

    RETURN_TYPES = ("SEEDANCE_API",)
    RETURN_NAMES = ("api",)
    FUNCTION = "configure"

    def configure(self, api_key, base_url):
        return ({"api_key": api_key, "provider": "anyfast", "base_url": base_url or "https://www.anyfast.ai"},)


# --------------------------------------------------------------------------- #
# Reference Images node — collect multiple reference images
# --------------------------------------------------------------------------- #

class SeedanceRefImages:
    """Send up to 9 reference images to any Seedance 2.0 node.

    image_1 is required. Connect image_2 through image_9 as needed."""

    CATEGORY = "Seedance AM/References"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image_1": ("IMAGE",),
            },
            "optional": {
                "image_2": ("IMAGE",),
                "image_3": ("IMAGE",),
                "image_4": ("IMAGE",),
                "image_5": ("IMAGE",),
                "image_6": ("IMAGE",),
                "image_7": ("IMAGE",),
                "image_8": ("IMAGE",),
                "image_9": ("IMAGE",),
            }
        }

    RETURN_TYPES = ("SEEDANCE_IMAGE_LIST",)
    RETURN_NAMES = ("reference_images",)
    FUNCTION     = "collect"

    def collect(self, image_1, image_2=None, image_3=None, image_4=None,
                image_5=None, image_6=None, image_7=None, image_8=None, image_9=None):
        images = [image_1]
        for img in [image_2, image_3, image_4, image_5, image_6, image_7, image_8, image_9]:
            if img is not None:
                images.append(img)
        print(f"[Seedance] RefImages: {len(images)} image(s) collected")
        return (images,)


# --------------------------------------------------------------------------- #
# Reference Video / Audio loader nodes
# --------------------------------------------------------------------------- #

def _list_files(extensions):
    """Return files found in ComfyUI input directory with given extensions."""
    try:
        input_dir = folder_paths.get_input_directory()
        files = [
            f for f in sorted(os.listdir(input_dir))
            if os.path.splitext(f)[1].lower() in extensions
        ]
        return files if files else ["none"]
    except Exception:
        return ["none"]


def _video_input_to_path(video_input):
    """Extract a usable file path from a ComfyUI VIDEO object.

    Returns (path, is_temp). When is_temp is True the caller must delete path
    after use — the video was in memory and had to be written to a temp file."""
    import tempfile
    source = video_input.get_stream_source()
    if isinstance(source, str):
        return source, False
    source.seek(0)
    tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    tmp.write(source.read())
    tmp.close()
    return tmp.name, True


def _audio_dict_to_wav(audio_dict):
    """Save a ComfyUI AUDIO dict {waveform, sample_rate} to a temp WAV file.

    Returns the temp path — caller is responsible for deleting it."""
    import tempfile
    try:
        import torchaudio
    except ImportError:
        raise RuntimeError(
            "torchaudio is required for AUDIO input — it should already be present in ComfyUI."
        )
    waveform    = audio_dict["waveform"]
    sample_rate = audio_dict["sample_rate"]
    if waveform.dim() == 3:
        waveform = waveform[0]
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    torchaudio.save(tmp.name, waveform.cpu(), sample_rate)
    return tmp.name


class SeedanceReferenceVideo:
    """Prepare a reference video for Seedance generation.

    Uploads to a public host (catbox → litterbox → 0x0.st) so AnyFast can
    fetch it. Connect one of:
    - A ComfyUI Load Video node to the 'video' input, OR
    - Pick a file from the 'video_file' dropdown, OR
    - Paste an absolute path into 'video_path'."""

    CATEGORY = "Seedance AM/References"

    @classmethod
    def INPUT_TYPES(cls):
        files = ["none"] + _list_files([".mp4", ".mov", ".avi", ".webm"])
        return {
            "required": {},
            "optional": {
                "video_path": ("STRING", {"default": "", "placeholder": "C:\\Users\\...\\video.mp4"}),
                "video_file": (files,),
                "video":      ("VIDEO", {"forceInput": True}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("reference_video",)
    FUNCTION     = "upload"

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        if kwargs.get("video") is not None:
            return float("nan")
        return kwargs.get("video_path", "") or kwargs.get("video_file", "")

    def upload(self, video_path=None, video_file=None, video=None):
        cleanup   = False
        file_path = None

        if video is not None:
            file_path, cleanup = _video_input_to_path(video)
            print(f"[Seedance] Using Load Video node input: {file_path}")
        elif video_path and video_path.strip().strip('"').strip("'") not in ("", "none"):
            file_path = video_path.strip().strip('"').strip("'")
            print(f"[Seedance] Using video_path: {file_path}")
        elif video_file and video_file != "none":
            file_path = os.path.join(folder_paths.get_input_directory(), video_file)
            print(f"[Seedance] Using video_file dropdown: {video_file}")
        else:
            raise ValueError(
                "Connect a Load Video node, pick from 'video_file', or paste a path in 'video_path'."
            )

        try:
            with open(file_path, "rb") as f:
                file_bytes = f.read()
            filename  = os.path.basename(file_path)
            video_url = _upload_to_temp_host(file_bytes, filename)
            print(f"[Seedance] Reference video → {video_url}")
            return (video_url,)
        finally:
            if cleanup and file_path and os.path.exists(file_path):
                os.remove(file_path)


class SeedanceReferenceAudio:
    """Prepare a reference audio track for Seedance generation.

    Encodes as base64 data URI (<10 MB) or uploads to catbox (>10 MB).
    No API connection required.

    Connect one of:
    - Paste an absolute path into 'audio_path' (Windows: right-click file → Copy as path), OR
    - A ComfyUI Load Audio node to the 'audio' input, OR
    - Pick a file from the 'audio_file' dropdown (files in the ComfyUI input directory)."""

    CATEGORY = "Seedance AM/References"

    @classmethod
    def INPUT_TYPES(cls):
        files = ["none"] + _list_files([".mp3", ".wav", ".ogg", ".flac", ".m4a"])
        return {
            "required": {},
            "optional": {
                "audio_path": ("STRING", {"default": "", "placeholder": "C:\\Users\\...\\audio.mp3"}),
                "audio_file": (files,),
                "audio":      ("AUDIO", {"forceInput": True}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("reference_audio",)
    FUNCTION     = "upload"

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        if kwargs.get("audio") is not None:
            return float("nan")
        return kwargs.get("audio_path", "") or kwargs.get("audio_file", "")

    def upload(self, audio_path=None, audio_file=None, audio=None):
        cleanup   = False
        file_path = None

        if audio is not None:
            file_path = _audio_dict_to_wav(audio)
            cleanup   = True
            print(f"[Seedance] Using Load Audio node input (saved to temp WAV)")
        elif audio_path and audio_path.strip().strip('"').strip("'") not in ("", "none"):
            file_path = audio_path.strip().strip('"').strip("'")
            print(f"[Seedance] Using audio_path: {file_path}")
        elif audio_file and audio_file != "none":
            file_path = os.path.join(folder_paths.get_input_directory(), audio_file)
            print(f"[Seedance] Using audio_file dropdown: {audio_file}")
        else:
            raise ValueError(
                "Provide a file path in 'audio_path', connect a Load Audio node, "
                "or pick a file from the 'audio_file' dropdown."
            )

        try:
            with open(file_path, "rb") as f:
                file_bytes = f.read()
            ext      = os.path.splitext(file_path)[1].lower()
            mime_map = {".mp3": "audio/mpeg", ".wav": "audio/wav",
                        ".ogg": "audio/ogg",  ".flac": "audio/flac", ".m4a": "audio/mp4"}
            mime     = mime_map.get(ext, "audio/wav")
            if len(file_bytes) <= 10 * 1024 * 1024:
                audio_url = f"data:{mime};base64,{base64.b64encode(file_bytes).decode('ascii')}"
                print(f"[Seedance] Reference audio → base64 ({len(file_bytes)//1024} KB)")
            else:
                audio_url = _upload_to_temp_host(file_bytes, os.path.basename(file_path))
                print(f"[Seedance] Reference audio → {audio_url}")
            return (audio_url,)
        finally:
            if cleanup and file_path and os.path.exists(file_path):
                os.remove(file_path)


# --------------------------------------------------------------------------- #
# Upload Asset node — handles group creation + upload in one step
# --------------------------------------------------------------------------- #

class SeedanceUploadAsset:
    """Upload a single asset to AnyFast Asset Management manually.

    On the Direct channel only Image assets work reliably. Video and Audio
    asset types (volc-asset-video / volc-asset-audio) are not available on
    Direct — use SeedanceReferenceVideo / SeedanceReferenceAudio instead.

    For uploading face images in bulk, prefer SeedanceFaceRef which handles
    the full group + upload + wait + cache flow automatically."""

    CATEGORY = "Seedance AM/Advanced"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "api":        ("SEEDANCE_API",),
                "asset_type": (["Image", "Video", "Audio"],),
                "name":       ("STRING", {"default": "asset"}),
                "group_name": ("STRING", {"default": "comfyui-assets"}),
            },
            "optional": {
                "image":             ("IMAGE",),
                "file_path":         ("STRING", {"forceInput": True}),
                "existing_group_id": ("STRING", {"forceInput": True}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("asset_id", "group_id")
    FUNCTION     = "upload"

    def upload(self, api, asset_type, name, group_name, image=None, file_path=None, existing_group_id=None):
        if image is None and not (file_path and file_path.strip()):
            raise ValueError("Connect either an image or a file_path (for video/audio).")

        group_id  = _ensure_group(api, group_name, existing_group_id)
        asset_uri, _, group_id = _upload_asset(api, asset_type, name, group_id,
                                               image_tensor=image, file_path=file_path)
        _wait_for_asset_active(api, asset_uri, group_id)
        _stabilize_anyfast_asset(asset_type)
        print(f"[Seedance Assets] Uploaded {asset_type}: {asset_uri}  group_id={group_id}")
        return (asset_uri, group_id)


# --------------------------------------------------------------------------- #
# Human Identity Asset node
# — Streamlines the ID-verification workflow for real-human video generation
# — First use: upload portrait → API may return a verification link (liveness
#   check on phone/browser < 30 s) → save the output group_id for future runs
# — Subsequent uses: pass the saved group_id via existing_group_id to skip
#   re-verification; the API compares facial features automatically
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# Seedance 2.0 generation nodes
# — T2V when no first_frame connected; I2V when first_frame connected
# — reference_images: connect SeedanceRefImages output (1–9 style refs)
# — reference_video / reference_audio: connect SeedanceUploadAsset output
# — AnyFast: images are embedded as base64 data URIs automatically
# --------------------------------------------------------------------------- #

class _V2Base:
    CATEGORY    = "Seedance AM/Core"
    RESOLUTIONS = RES_V2
    MODEL_ID    = "seedance"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "api":            ("SEEDANCE_API",),
                "prompt":         ("STRING", {"multiline": True, "default": ""}),
                "resolution":     (cls.RESOLUTIONS,),
                "ratio":          (RATIO_V2,),
                "duration":       ("INT", {"default": 5, "min": 4, "max": MAX_DURATION, "step": 1}),
                "generate_audio": ("BOOLEAN", {"default": True}),
                "watermark":      ("BOOLEAN", {"default": False}),
                "seed":           ("INT", {"default": -1, "min": -1, "max": 2147483647}),
            },
            "optional": {
                # Frame control
                "first_frame":      ("IMAGE",),
                "last_frame":       ("IMAGE",),
                # Style / context references — connect SeedanceRefImages (up to 9 images)
                "reference_images": ("SEEDANCE_IMAGE_LIST",),
                # Reference video/audio — connect SeedanceReferenceVideo / SeedanceReferenceAudio
                "reference_video":  ("STRING", {"forceInput": True}),
                "reference_audio":  ("STRING", {"forceInput": True}),
                # Face/person refs — connect SeedanceFaceRef (routes through AnyFast asset system)
                "anyfast_refs":     ("ANYFAST_IMAGE_REFS", {"forceInput": True,
                                                             "tooltip": "AnyFast only — prepared face/person refs from SeedanceFaceRef"}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING", "IMAGE")
    RETURN_NAMES = ("video_url", "task_id", "first_frame")
    FUNCTION     = "generate"
    OUTPUT_NODE  = True

    def generate(self, api, prompt, resolution, ratio, duration, generate_audio,
                 watermark, seed, first_frame=None, last_frame=None,
                 reference_images=None, reference_video=None, reference_audio=None,
                 anyfast_refs=None):

        # Seedance requires @image1, @video1, @audio1 tags in the prompt so the
        # model knows how to use each reference. Auto-append any missing tags.
        prompt_lower = prompt.lower()
        img_start = 1
        if anyfast_refs:
            # Count only reference_image role entries; first/last frame don't use @image tags
            ref_img_count = sum(1 for e in anyfast_refs if e.get("role") == "reference_image")
            for i in range(img_start, img_start + ref_img_count):
                tag = f"@image{i}"
                if tag not in prompt_lower:
                    prompt = prompt + f" {tag}"
                    prompt_lower = prompt.lower()
        elif reference_images:
            for i in range(img_start, img_start + len(reference_images)):
                tag = f"@image{i}"
                if tag not in prompt_lower:
                    prompt = prompt + f" {tag}"
                    prompt_lower = prompt.lower()
        if reference_video and reference_video.strip():
            if "@video1" not in prompt_lower:
                prompt = prompt + " @video1"
                prompt_lower = prompt.lower()
        if reference_audio and reference_audio.strip():
            if "@audio1" not in prompt_lower:
                prompt = prompt + " @audio1"
                prompt_lower = prompt.lower()
            # AnyFast requires at least one image or video reference alongside audio
            has_other_ref = (
                anyfast_refs
                or reference_images
                or (reference_video and reference_video.strip())
            )
            if not has_other_ref:
                raise ValueError(
                    "AnyFast requires at least one image (or video) reference alongside reference_audio.\n"
                    "Connect a reference image via anyfast_refs (SeedanceFaceRef)\n"
                    "or via reference_images (SeedanceRefImages), or add a reference_video as well."
                )

        print(f"[Seedance] Final prompt: {prompt}")

        content = [{"type": "text", "text": prompt}]

        if anyfast_refs:
            print(f"[Seedance/AnyFast] Using {len(anyfast_refs)} prepared image ref(s)")
            has_frame_control = any(
                e.get("role") in ("first_frame", "last_frame") for e in anyfast_refs
            )
            has_reference_roles = any(
                e.get("role") == "reference_image" for e in anyfast_refs
            )
            if has_frame_control and (
                has_reference_roles
                or (reference_video and reference_video.strip())
                or (reference_audio and reference_audio.strip())
            ):
                raise ValueError(
                    "AnyFast does not support mixing first/last frame control with multimodal "
                    "references in the same request. Use either frame control or references."
                )
            only_first_frame = (
                len(anyfast_refs) == 1
                and anyfast_refs[0].get("role") == "first_frame"
                and anyfast_refs[0].get("type") == "image_url"
                and not (reference_video and reference_video.strip())
                and not (reference_audio and reference_audio.strip())
            )
            for entry in anyfast_refs:
                normalized = dict(entry)
                if only_first_frame:
                    normalized.pop("role", None)
                content.append(normalized)
        else:
            if first_frame is not None:
                content.append({
                    "type":      "image_url",
                    "image_url": {"url": _tensor_to_b64(first_frame)},
                    "role":      "first_frame",
                })
            if last_frame is not None:
                content.append({
                    "type":      "image_url",
                    "image_url": {"url": _tensor_to_b64(last_frame)},
                    "role":      "last_frame",
                })
            if reference_images is not None:
                for img_tensor in reference_images:
                    content.append({
                        "type":      "image_url",
                        "image_url": {"url": _tensor_to_b64(img_tensor)},
                        "role":      "reference_image",
                    })

        if reference_video and reference_video.strip():
            content.append({
                "type":      "video_url",
                "video_url": {"url": reference_video.strip()},
                "role":      "reference_video",
            })
        if reference_audio and reference_audio.strip():
            content.append({
                "type":      "audio_url",
                "audio_url": {"url": reference_audio.strip()},
                "role":      "reference_audio",
            })

        payload = {
            "model":          self.MODEL_ID,
            "content":        content,
            "resolution":     resolution,
            "ratio":          ratio,
            "duration":       duration,
            "generate_audio": generate_audio,
            "watermark":      watermark,
        }
        if seed != -1:
            payload["seed"] = seed

        url, task_id, frame = _submit_and_poll(api, payload)
        return (url, task_id, frame)


class Seedance2(_V2Base):
    """Seedance 2.0 — Text/Image to Video (480 / 720 / 1080p, up to 15s, with audio)."""
    RESOLUTIONS = RES_V2
    MODEL_ID    = "seedance"


class Seedance2Fast(_V2Base):
    """Seedance 2.0 Fast — Same capabilities as standard, faster generation."""
    RESOLUTIONS = RES_V2
    MODEL_ID    = "seedance-fast"


class Seedance2Ultra(_V2Base):
    """Seedance 2.0 Ultra — Highest quality (720p / 1080p / 2k, up to 15s, with audio)."""
    RESOLUTIONS = RES_V2_ULTRA
    MODEL_ID    = "seedance-2.0-ultra"


# --------------------------------------------------------------------------- #
# Extend node — continue a previously generated video
# Requires AnyFast to expose POST /v1/video/extend.  If the endpoint returns
# a 404 / 405 error, the feature is not yet available on your AnyFast plan.
# --------------------------------------------------------------------------- #

class SeedanceExtend:
    """Extend a previously generated Seedance video by submitting its task_id.

    Wire the task_id output of any generation node here to seamlessly continue
    the clip. Returns the extended video_url, the new task_id, and the first
    frame of the extended video for further chaining."""

    CATEGORY = "Seedance AM/Core"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "api":            ("SEEDANCE_API",),
                "task_id":        ("STRING", {"forceInput": True}),
                "model":          (["seedance", "seedance-fast", "seedance-2.0-ultra"],),
                "prompt":         ("STRING", {"multiline": True, "default": ""}),
                "duration":       ("INT",    {"default": 5, "min": 4, "max": MAX_DURATION, "step": 1}),
                "resolution":     (["2k", "1080p", "720p", "480p"],),
                "generate_audio": ("BOOLEAN", {"default": True}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING", "IMAGE")
    RETURN_NAMES = ("video_url", "task_id", "first_frame")
    FUNCTION     = "extend"
    OUTPUT_NODE  = True

    def extend(self, api, task_id, model, prompt, duration, resolution, generate_audio):
        base_url = api["base_url"].rstrip("/")
        api_key  = api["api_key"].strip()

        if not api_key:
            raise ValueError("API key is empty — paste your AnyFast key in the Seedance API Key node.")

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model":          model,
            "request_id":     task_id,
            "prompt":         prompt,
            "duration":       duration,
            "resolution":     resolution,
            "generate_audio": generate_audio,
        }
        r = requests.post(f"{base_url}/v1/video/extend", json=payload,
                          headers=headers, timeout=300)
        if not r.ok:
            raise RuntimeError(
                f"Seedance Extend error {r.status_code}: {r.text}\n"
                "If you see 404/405, the /v1/video/extend endpoint may not be "
                "available on your AnyFast plan yet."
            )

        new_task_id = r.json()["id"]
        print(f"[Seedance Extend] Job submitted — task_id={new_task_id}")

        video_url = _poll_v2(base_url, api_key, new_task_id)
        frame     = _first_frame(video_url)
        return (video_url, new_task_id, frame)


# --------------------------------------------------------------------------- #
# Save Video node — downloads video_url and saves to ComfyUI output folder
# --------------------------------------------------------------------------- #

class SeedanceSaveVideo:
    """Download and save the generated video to the ComfyUI output folder.

    Saves the generated video and returns a local preview when supported by
    the current ComfyUI UI helpers."""

    CATEGORY = "Seedance AM/Core"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "video_url":       ("STRING", {"forceInput": True}),
                "filename_prefix": ("STRING", {"default": "seedance"}),
                "save_to":         (["output", "input"], {"default": "output"}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("saved_path",)
    OUTPUT_NODE  = True
    FUNCTION     = "save"

    def save(self, video_url, filename_prefix, save_to):
        output_dir = folder_paths.get_output_directory() if save_to == "output" else folder_paths.get_input_directory()
        timestamp  = int(time.time())
        filename   = f"{filename_prefix}_{timestamp}.mp4"
        filepath   = os.path.join(output_dir, filename)
        subfolder  = ""

        print(f"[Seedance] Downloading video -> {filepath}")
        r = requests.get(video_url, stream=True, timeout=300)
        if not r.ok:
            raise RuntimeError(f"Failed to download video: {r.status_code}")

        with open(filepath, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)

        print(f"[Seedance] Saved: {filename}")
        if comfy_ui is not None and comfy_io is not None:
            folder_type = comfy_io.FolderType.output if save_to == "output" else comfy_io.FolderType.input
            preview_ui = comfy_ui.PreviewVideo(
                [comfy_ui.SavedResult(filename, subfolder, folder_type)]
            ).as_dict()
        else:
            entry = {"filename": filename, "subfolder": subfolder, "type": save_to}
            preview_ui = {"gifs": [entry], "videos": [entry]}

        return {
            "ui": {
                "text": [filepath],
                **preview_ui,
            },
            "result": (filepath,),
        }


# --------------------------------------------------------------------------- #
# Show Text node — display any STRING output directly in the node body
# --------------------------------------------------------------------------- #

class SeedanceShowText:
    """Display any text value (asset_id, group_id, verify_url, video_url…)
    directly inside the node so you can read and copy it without extra nodes."""

    CATEGORY    = "Seedance AM/Debug"
    OUTPUT_NODE = True

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"text": ("STRING", {"forceInput": True})}}

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("text",)
    FUNCTION     = "show"

    def show(self, text):
        return {"ui": {"text": [str(text)]}, "result": (str(text),)}


# --------------------------------------------------------------------------- #
# Registration
# --------------------------------------------------------------------------- #

NODE_CLASS_MAPPINGS = {
    # Config
    "SeedanceApiKey":      SeedanceApiKey,
    # 2.0 generation
    "Seedance2":           Seedance2,
    "Seedance2Fast":       Seedance2Fast,
    "Seedance2Ultra":      Seedance2Ultra,
    # References
    "SeedanceReferenceVideo":   SeedanceReferenceVideo,
    "SeedanceReferenceAudio":   SeedanceReferenceAudio,
    "SeedanceRefImages":        SeedanceRefImages,
    # Face / asset
    "SeedanceFaceRef":          SeedanceFaceRef,
    "SeedanceAssetRef":         SeedanceAssetRef,
    "SeedanceUploadAsset":      SeedanceUploadAsset,
    # Extend
    "SeedanceExtend":      SeedanceExtend,
    # Output
    "SeedanceSaveVideo":   SeedanceSaveVideo,
    "SeedanceShowText":    SeedanceShowText,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    # Config
    "SeedanceApiKey":      "Seedance AM - API Key",
    # 2.0 generation
    "Seedance2":           "Seedance AM 2.0 - Standard",
    "Seedance2Fast":       "Seedance AM 2.0 - Fast",
    "Seedance2Ultra":      "Seedance AM 2.0 - Ultra",
    # References
    "SeedanceReferenceVideo":   "Seedance AM - Reference Video",
    "SeedanceReferenceAudio":   "Seedance AM - Reference Audio",
    "SeedanceRefImages":        "Seedance AM - Reference Images (9 slots)",
    # Face / asset
    "SeedanceFaceRef":          "Seedance AM - Face / Person Reference (asset)",
    "SeedanceAssetRef":         "Seedance AM - Asset Reference",
    "SeedanceUploadAsset":      "Seedance AM - Upload Asset",
    # Extend
    "SeedanceExtend":      "Seedance AM - Extend Video",
    # Output
    "SeedanceSaveVideo":   "Seedance AM - Save Video",
    "SeedanceShowText":    "Seedance AM - Show Text",
}


