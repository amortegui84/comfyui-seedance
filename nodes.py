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
    # Video/audio asset still uploading: "asset is still processing and is not available yet"
    if "still processing" in txt or "not available yet" in txt:
        return True
    # AnyFast spreads assets across channels and replicates them lazily. An asset
    # that is Active can still be missing from the channel the generation lands
    # on: 'asset "..." copy on channel 391 is not ready (status="Processing")'.
    # It arrives as a 503, and it clears on its own within a few seconds. This is
    # the common case for a CACHED asset, because a cache hit skips the
    # wait-for-Active poll that would otherwise have given it time to settle.
    if "asset_copy_not_ready" in txt or ("copy on channel" in txt and "not ready" in txt):
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


def _submit_and_poll(api, payload, poll_timeout=1200):
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
        # 400 for "asset not found", 503 for "copy on channel not ready" — both
        # mean the same thing: wait and ask again.
        if r.status_code in (400, 503) and _is_anyfast_asset_not_ready_error(r.text):
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
                "AnyFast rejected an image: real-person face detected.\n"
                "\n"
                "This applies to ANY photograph containing recognisable people — not just\n"
                "portraits. A location shot with a crowd, bystanders or faces in the\n"
                "background triggers it too, which is easy to miss when the image is\n"
                "meant as scenery.\n"
                "\n"
                "Every such image has to travel as an asset:// reference. Move it off\n"
                "reference_images (SeedanceRefImages sends base64, which AnyFast blocks for\n"
                "real people) and onto SeedanceFaceRef → anyfast_refs.\n"
                "\n"
                "To keep your @imageN numbering, chain rather than replace: wire your\n"
                "existing refs into the new node's existing_refs input, so the images stay\n"
                "in the same order they are in now."
            )
        if "model_not_found" in r.text.lower() or "no available channel" in r.text.lower():
            model_name = payload.get("model", "?")
            raise RuntimeError(
                f"AnyFast has no available channel for model '{model_name}'.\n"
                "Enable the model's channel in the AnyFast Console (some models require the Direct plan)."
            )
        raise RuntimeError(f"Seedance API error {r.status_code}: {r.text}")
    if not r.ok:
        raise RuntimeError(f"Seedance API error {r.status_code}: {r.text}")

    resp_json = r.json()
    print(f"[Seedance] Submit response keys: {list(resp_json.keys()) if isinstance(resp_json, dict) else resp_json}")
    task_id = _extract_id(resp_json, "id", "Id", "task_id", "taskId", "ID")
    print(f"[Seedance] Job submitted — task_id={task_id}")

    video_url = _poll_v2(base_url, api_key, task_id, timeout=poll_timeout)
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


# Cache of resolved asset-group GroupType, keyed by (base_url, group_id).
# ListAssets on the current AnyFast channel requires Filter.GroupType (groups
# resolve to "AIGC"); caching it lets repeated asset waits include GroupType on
# the first call and avoid the guaranteed "GroupType is missing" 400.
_GROUP_TYPE_CACHE = {}


def _list_asset_group_type(base_url, headers, group_id):
    """Resolve GroupType for an AnyFast asset group if ListAssets requires it.

    Returns the GroupType string (e.g. "AIGC") or None if the group has no type.
    Caches successful lookups in _GROUP_TYPE_CACHE. Raises on API errors."""
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
            resolved = str(group_type).strip()
            _GROUP_TYPE_CACHE[(base_url, group_id)] = resolved
            return resolved
    return None


def _resolve_group_type(base_url, headers, group_id):
    """Best-effort GroupType lookup used before the first ListAssets call.

    Reads the cache first, then falls back to ListAssetGroups. Returns None
    (so callers omit GroupType, the older typeless-group behavior) if the type
    cannot be resolved — never raises, so it can't break a working flow."""
    cached = _GROUP_TYPE_CACHE.get((base_url, group_id))
    if cached:
        return cached
    try:
        return _list_asset_group_type(base_url, headers, group_id)
    except Exception as e:
        print(f"[Seedance Assets] Could not pre-resolve GroupType for {group_id}: {e}")
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

        if "pixelcounttoosmall" in txt or "pixel count" in txt:
            raise RuntimeError(
                "Video resolution is too small for AnyFast.\n"
                "Minimum: ~640×640 px (409,600 total pixels).\n"
                "Maximum: ~1920×1088 px (2,086,876 total pixels).\n"
                "Use a higher resolution video."
            )
        if "pixelcounttoobig" in txt or ("pixel count" in txt and "large" in txt):
            raise RuntimeError(
                "Video resolution is too large for AnyFast.\n"
                "Maximum: ~1920×1088 px (2,086,876 total pixels).\n"
                "Use a lower resolution video."
            )
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
    # Resolve GroupType up front (cached) so the first ListAssets call already
    # includes it and we avoid the guaranteed "GroupType is missing" 400 that the
    # current AnyFast channel returns. Falls back to None (omit) for older
    # typeless-group channels; the in-loop fallback below is kept as a safety net.
    resolved_group_type = _resolve_group_type(base_url, headers, group_id)
    if resolved_group_type:
        print(f"[Seedance Assets] Using GroupType={resolved_group_type} for group {group_id}")

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


# Seconds to wait after an asset reports Active, per asset type. Only images
# needed it; see _stabilize_anyfast_asset for why this is now 5 and not 20.
ASSET_SETTLE_DEFAULTS = {"Image": 5}


def _stabilize_anyfast_asset(asset_type):
    """Allow extra backend propagation time after Active for some asset types.

    This is the fourth layer of insurance against the same race: _upload_asset
    already sleeps 5s, _wait_for_asset_active polls until the asset reports
    Active, and _submit_and_poll retries the generation up to 12 times when
    AnyFast answers "asset not ready". Paying a fixed 20s here on top of all
    that cost ~35-40s per new image — six minutes for a batch of nine.

    Now 5s by default: enough to cover the common case, with the existing submit
    retry absorbing the rare miss (a retry costs ~10s once, versus 20s always).
    Raise SEEDANCE_ASSET_SETTLE if your channel turns out to need the old
    behaviour; setting it to 20 restores the previous timing exactly.
    """
    settle_delays = dict(ASSET_SETTLE_DEFAULTS)
    try:
        override = int(os.environ.get("SEEDANCE_ASSET_SETTLE", "").strip())
        settle_delays = {k: override for k in settle_delays}
    except (TypeError, ValueError):
        pass
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


# --------------------------------------------------------------------------- #
# Identity store — one JSON file per named person/subject
#
# The hash cache below answers "have I uploaded THIS exact image before?".
# The identity store answers "what is my-subject's asset id?", which is the question
# you actually ask when building a workflow. One file per identity so a single
# identity can be copied to another machine, renamed by renaming the file, and
# synced through a shared folder without merge conflicts.
#
# Location: $SEEDANCE_IDENTITIES_DIR, else ComfyUI/user/seedance/identities.
# It has to be an environment variable rather than a node input because the
# identity dropdown is built in INPUT_TYPES, before any node connection exists.
# Point it at a synced folder (OneDrive, Dropbox) to carry identities between
# machines.
# --------------------------------------------------------------------------- #

def _identities_dir():
    override = os.environ.get("SEEDANCE_IDENTITIES_DIR", "").strip()
    if override:
        path = override
    else:
        try:
            base = folder_paths.get_user_directory()
        except Exception:
            base = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(base, "seedance", "identities")
    try:
        os.makedirs(path, exist_ok=True)
    except Exception as e:
        print(f"[Seedance Identity] Warning: could not create {path}: {e}")
    return path


def _identity_slug(name):
    """Filesystem-safe file stem. Keeps the name readable so the folder stays
    browsable — 'Ana María' becomes 'ana-maria.json'.

    Accents are folded to ASCII on purpose: these files are meant to be synced
    between machines, and non-ASCII filenames still trip up cloud sync clients
    and cross-OS copies. The display name inside the file keeps its accents."""
    import unicodedata
    decomposed = unicodedata.normalize("NFKD", str(name))
    ascii_only = "".join(c for c in decomposed if not unicodedata.combining(c))
    slug = re.sub(r"[^A-Za-z0-9\-_. ]+", "", ascii_only).strip()
    slug = re.sub(r"\s+", "-", slug).strip("-.")
    return slug.lower() or "unnamed"


def _list_identities():
    """Identity names available for the dropdown, from the store on disk."""
    try:
        names = []
        for fn in os.listdir(_identities_dir()):
            if fn.lower().endswith(".json"):
                names.append(os.path.splitext(fn)[0])
        return sorted(names)
    except Exception:
        return []


def _load_identity(name):
    path = os.path.join(_identities_dir(), f"{_identity_slug(name)}.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[Seedance Identity] Could not read {path}: {e}")
        return None


def _save_identity(record):
    path = os.path.join(_identities_dir(), f"{_identity_slug(record['identity'])}.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(record, f, indent=2, ensure_ascii=False)
        print(f"[Seedance Identity] Saved {record['identity']} → {path}")
    except Exception as e:
        print(f"[Seedance Identity] Warning: could not save {path}: {e}")
    return path


THUMB_SIZE = 320   # px, longest side — big enough to recognise a face in a preview


def _identity_thumbs_dir(identity, create=False):
    path = os.path.join(_identities_dir(), f"{_identity_slug(identity)}.thumbs")
    if create:
        try:
            os.makedirs(path, exist_ok=True)
        except Exception as e:
            print(f"[Seedance Identity] Warning: could not create {path}: {e}")
    return path


def _save_identity_thumb(identity, asset_uri, image_tensor):
    """Keep a small local copy of an uploaded image so the Identity node can show
    what it is about to send. AnyFast only ever returns an asset:// id, so without
    this the node is blind — you would be picking references you cannot see."""
    if image_tensor is None:
        return None
    try:
        arr = (image_tensor[0].numpy() * 255).clip(0, 255).astype(np.uint8)
        pil = Image.fromarray(arr).convert("RGB")
        pil.thumbnail((THUMB_SIZE, THUMB_SIZE))
        name = f"{asset_uri.split('://')[-1]}.png"
        path = os.path.join(_identity_thumbs_dir(identity, create=True), name)
        pil.save(path, format="PNG")
        return name
    except Exception as e:
        print(f"[Seedance Identity] Warning: could not save thumbnail: {e}")
        return None


def _load_identity_thumbs(identity, assets):
    """Stack the saved thumbnails into one IMAGE batch, in reference order.

    Entries with no thumbnail (identities imported from the old hash cache, which
    only ever stored ids) become grey placeholders so the batch still lines up
    one-to-one with the references."""
    thumbs_dir = _identity_thumbs_dir(identity)
    frames = []
    for asset in assets:
        arr = None
        thumb = asset.get("thumb")
        if thumb:
            path = os.path.join(thumbs_dir, thumb)
            if os.path.exists(path):
                try:
                    pil = Image.open(path).convert("RGB")
                    arr = np.asarray(pil, dtype=np.float32) / 255.0
                except Exception as e:
                    print(f"[Seedance Identity] Could not read {path}: {e}")
        if arr is None:
            arr = np.full((THUMB_SIZE, THUMB_SIZE, 3), 0.25, dtype=np.float32)
        frames.append(arr)

    if not frames:
        return _blank_frame()

    # A ComfyUI IMAGE batch needs identical dimensions, and references are rarely
    # the same shape — letterbox each onto a common square canvas.
    canvas = np.zeros((len(frames), THUMB_SIZE, THUMB_SIZE, 3), dtype=np.float32)
    for i, arr in enumerate(frames):
        h, w = arr.shape[:2]
        scale = min(THUMB_SIZE / max(h, 1), THUMB_SIZE / max(w, 1), 1.0)
        nh, nw = max(1, int(h * scale)), max(1, int(w * scale))
        if (nh, nw) != (h, w):
            arr = np.asarray(
                Image.fromarray((arr * 255).astype(np.uint8)).resize((nw, nh)),
                dtype=np.float32,
            ) / 255.0
        top, left = (THUMB_SIZE - nh) // 2, (THUMB_SIZE - nw) // 2
        canvas[i, top:top + nh, left:left + nw] = arr

    if torch is not None:
        return torch.from_numpy(canvas)
    return canvas


def _parse_selection(select, count):
    """Turn '1,3,5' or '1-3,8' into zero-based indices. Empty selects everything.

    One-based on purpose: the preview shows the references as @image1, @image2 …
    so the numbers you type are the numbers you read off the screen."""
    text = (select or "").strip()
    if not text:
        return list(range(count))

    chosen = []
    for part in re.split(r"[,\s]+", text):
        if not part:
            continue
        match = re.fullmatch(r"(\d+)\s*-\s*(\d+)", part)
        if match:
            lo, hi = int(match.group(1)), int(match.group(2))
            if lo > hi:
                lo, hi = hi, lo
            chosen.extend(range(lo, hi + 1))
        elif part.isdigit():
            chosen.append(int(part))
        else:
            raise ValueError(
                f"Could not read '{part}' in select. Use numbers, ranges and commas, "
                f"like '1,3,5' or '1-3,8'."
            )

    out, seen = [], set()
    for number in chosen:
        if not (1 <= number <= count):
            raise ValueError(
                f"select asks for image {number}, but this identity has {count}. "
                f"Valid range is 1-{count}."
            )
        if number not in seen:
            seen.add(number)
            out.append(number - 1)
    return out


def _record_identity_asset(identity, asset_uri, role, group_id, image_hash=None,
                           image_tensor=None):
    """Add or refresh one asset inside an identity's record, keeping the file
    stable so it stays readable and diffable."""
    record = _load_identity(identity) or {
        "identity": identity,
        "group_id": group_id,
        "notes":    "",
        "assets":   [],
    }
    if group_id:
        record["group_id"] = group_id

    entry = {
        "asset_id":    asset_uri,
        "role":        role,
        "image_sha":   image_hash,
        "thumb":       _save_identity_thumb(identity, asset_uri, image_tensor),
        "uploaded_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    # A cache hit re-records without the tensor; keep the thumbnail already on disk.
    if entry["thumb"] is None:
        previous = next((a for a in record.get("assets", [])
                         if a.get("asset_id") == asset_uri), None)
        if previous:
            entry["thumb"] = previous.get("thumb")
    # Update in place rather than remove-and-append: the list order decides which
    # asset becomes @image1, @image2 ... so re-recording one image of an identity
    # must not silently reshuffle the prompt tags of every workflow using it.
    assets = record.get("assets", [])
    for i, existing in enumerate(assets):
        if existing.get("asset_id") == asset_uri:
            assets[i] = entry
            break
    else:
        assets.append(entry)
    record["assets"] = assets
    _save_identity(record)
    return record


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

    Set `identity` to name the subject (e.g. 'my-subject'). That writes an identity file
    you can reload later from the Identity node by picking the name from a dropdown,
    with no image connected and no upload — and the file holds the raw asset:// ids
    so you can copy one into a script or into SeedanceAssetRef. See the Identity
    node for where the files live and how to sync them between machines.

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
                # Declared LAST on purpose. ComfyUI serialises widget values as a
                # positional array, so inserting a widget anywhere but the end
                # shifts every saved workflow's values by one.
                "identity": ("STRING", {"default": "",
                                        "tooltip": "Name this person/subject (e.g. 'my-subject'). Saves the "
                                                   "asset ids to an identity file you can reuse later "
                                                   "with the Identity node, on any machine. Leave empty "
                                                   "to keep the old hash-cache-only behaviour."}),
            }
        }

    RETURN_TYPES  = ("ANYFAST_IMAGE_REFS", "STRING", "STRING")
    RETURN_NAMES  = ("anyfast_refs", "group_id", "asset_ids")
    OUTPUT_NODE   = True
    FUNCTION      = "upload"

    def upload(self, api, group_name, identity="", existing_group_id=None, force_reupload=False,
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

        # Defensive: a workflow saved against a build with a different widget order
        # could hand us a non-string here. Treat anything that is not text as unset.
        identity = identity.strip() if isinstance(identity, str) else ""
        cache    = {} if force_reupload else _load_asset_cache()

        # Resolve the group lazily. Creating one costs an API call plus a 3s
        # propagation wait, and the old code paid it on every run even when every
        # image came straight from cache — which is how 28 images ended up spread
        # across 8 throwaway groups. Prefer, in order: an explicitly wired group,
        # the group this identity already lives in, and only then a new one.
        group_id = existing_group_id.strip() if existing_group_id else None
        if not group_id and identity:
            saved = _load_identity(identity)
            if saved and saved.get("group_id"):
                group_id = saved["group_id"]
                print(f"[Seedance Assets] Reusing group from identity '{identity}': {group_id}")

        refs     = list(existing_refs) if existing_refs else []
        asset_id_list = []

        for idx, (img_tensor, role) in enumerate(images_with_roles):
            cache_key = _image_asset_cache_key(img_tensor, api["base_url"])

            if not force_reupload and cache_key in cache:
                asset_uri = cache[cache_key]["asset_id"]
                group_id  = group_id or cache[cache_key].get("group_id")
                print(f"[Seedance Assets] Cache hit — reusing {asset_uri} (role={role}, skipping upload)")
            else:
                # First real upload of this run — now a group is actually needed.
                group_id   = _ensure_group(api, group_name, group_id)
                asset_name = f"{identity or 'face'}_{role}_{idx + 1}"
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

            if identity:
                _record_identity_asset(identity, asset_uri, role, group_id,
                                       image_hash=cache_key, image_tensor=img_tensor)

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


class SeedanceIdentity:
    """Reuse a saved person/subject by name — no image, no upload, no pasting IDs.

    Pick an identity that SeedanceFaceRef saved earlier and this emits the same
    anyfast_refs a fresh upload would, instantly. Nothing is sent to AnyFast.

    Seeing what you are sending: wire the `preview` output to a Preview Image
    node. It shows every image the identity holds, in order, so the numbers you
    type into `select` are the numbers you can see. `select` takes '1,4,8' or
    '1-3,8'; leave it empty to send all of them.

    Adding another photo later: run SeedanceFaceRef again with the SAME identity
    name and the new image connected. It is appended to the identity rather than
    replacing it, and existing images are not re-uploaded.

    Identities live as one JSON file each in
    $SEEDANCE_IDENTITIES_DIR (default: ComfyUI/user/seedance/identities).
    Point that variable at a synced folder to use the same identities on
    another machine. Each file also carries the raw asset:// ids, so you can
    open it and copy an id into a script or into SeedanceAssetRef.

    Chain several of these via existing_refs to combine identities in one shot.
    Restart ComfyUI (or refresh the node list) after adding a new identity for
    it to appear in the dropdown."""

    CATEGORY = "Seedance AM/References"

    @classmethod
    def INPUT_TYPES(cls):
        known = _list_identities()
        return {
            "required": {
                "identity": (known if known else ["<no identities saved yet>"], {
                    "tooltip": "Saved identities. Create them with SeedanceFaceRef's identity field.",
                }),
                "role": (["reference_image", "first_frame", "last_frame"], {
                    "tooltip": "How the model should use these images. reference_image = "
                               "identity/style (@imageN); first/last_frame = literal frame.",
                }),
            },
            "optional": {
                "existing_refs": ("ANYFAST_IMAGE_REFS", {"forceInput": True,
                                                         "tooltip": "Chain another Identity or FaceRef node here."}),
                "limit": ("INT", {"default": 0, "min": 0, "max": 30,
                                  "tooltip": "Use at most the first N images. 0 = all. "
                                             "Ignored when 'select' is filled in."}),
                # Declared last: ComfyUI serialises widget values positionally.
                "select": ("STRING", {"default": "",
                                      "tooltip": "Which images to attach, 1-based, e.g. '1,4,8' or "
                                                 "'1-3,8'. Empty = all of them. Wire the preview "
                                                 "output to a Preview Image node to see which is "
                                                 "which — they are shown in this same order."}),
            }
        }

    RETURN_TYPES = ("ANYFAST_IMAGE_REFS", "STRING", "STRING", "IMAGE")
    RETURN_NAMES = ("anyfast_refs", "group_id", "asset_ids", "preview")
    OUTPUT_NODE  = True
    FUNCTION     = "load"

    @classmethod
    def IS_CHANGED(cls, identity, **kwargs):
        # Re-run when the identity file changes on disk (e.g. a new image was
        # added to it) instead of serving a stale cached execution.
        path = os.path.join(_identities_dir(), f"{_identity_slug(identity)}.json")
        try:
            return f"{path}:{os.path.getmtime(path)}"
        except Exception:
            return identity

    def load(self, identity, role, existing_refs=None, limit=0, select=""):
        record = _load_identity(identity)
        if not record:
            known = _list_identities()
            raise ValueError(
                f"No saved identity called '{identity}'.\n"
                f"Folder: {_identities_dir()}\n"
                + (f"Available: {', '.join(known)}" if known else
                   "Nothing saved yet — run SeedanceFaceRef once with an identity name set.")
            )

        all_assets = record.get("assets", [])
        if not all_assets:
            raise ValueError(f"Identity '{identity}' has no assets recorded in its file.")

        # The preview always shows every image the identity holds, numbered the way
        # `select` expects — otherwise you would be choosing indices blind.
        preview = _load_identity_thumbs(identity, all_assets)

        if select and select.strip():
            picked = _parse_selection(select, len(all_assets))
        elif limit:
            picked = list(range(min(limit, len(all_assets))))
        else:
            picked = list(range(len(all_assets)))
        assets = [all_assets[i] for i in picked]

        refs = list(existing_refs) if existing_refs else []
        asset_id_list = []
        for asset in assets:
            asset_uri = asset["asset_id"]
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

        group_id = record.get("group_id") or ""
        asset_ids_text = "\n".join(asset_id_list)
        chosen = ", ".join(str(i + 1) for i in picked)
        print(f"[Seedance Identity] '{identity}' → {len(asset_id_list)} of {len(all_assets)} "
              f"asset(s) [{chosen}], role={role} (no upload)")
        ui_text = (f"{identity}: using {len(asset_id_list)}/{len(all_assets)} → {chosen}\n"
                   f"group_id: {group_id}\n{asset_ids_text}")
        return {"ui": {"text": [ui_text]},
                "result": (refs, group_id, asset_ids_text, preview)}


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
# Seedance 2.5 — LIVE on AnyFast. Verified 2026-08-07 against GET /v1/models and
# docs.anyfast.ai/guides/model-api/bytedance/seedance-2-5.
#   * Exactly ONE model id: "seedance-2.5". There is no Fast / Ultra / Pro tier.
#   * 2.5 trades resolution for length: 480p / 720p ONLY (no 1080p, 2k or 4k),
#     but up to 30s in a single pass and up to 50 references.
#   * duration accepts -1 (model picks the length) or 4–30.
RES_V25      = ["720p", "480p"]
RATIO_V2     = ["16:9", "9:16", "4:3", "3:4", "1:1", "21:9", "adaptive"]
MAX_DURATION     = 15   # Seedance 2.0
MAX_DURATION_V25 = 30   # Seedance 2.5 — 30s single-pass max

# Content-array reference caps, per AnyFast's per-model schema. Exceeding them is a
# 400 from the API, so the nodes reject it locally with a message that names the cap.
REF_LIMITS_V2  = {"image": 9,  "video": 3,  "audio": 3}    # content: 1–16 items
REF_LIMITS_V25 = {"image": 30, "video": 10, "audio": 10}   # content: 1–51 items

# Every model AnyFast exposes for Seedance 2.x, with the limits that differ between
# them. This is the single source of truth: the unified `SeedanceVideo` node reads
# it at request time, and web/js/model_variants.js mirrors it to narrow the
# resolution dropdown in the UI. Adding a future Seedance model = one entry here
# (plus the matching entry in the .js).
_SPEC_V2 = {
    "resolutions":  RES_V2,
    "duration_min": 4,
    "duration_max": MAX_DURATION,
    "ref_limits":   REF_LIMITS_V2,
    "audio_only":   False,
    "poll_timeout": 1200,
}
MODEL_SPECS = {
    "seedance-2.0":       dict(_SPEC_V2),
    "seedance-2.0-fast":  dict(_SPEC_V2),
    "seedance-2.0-mini":  dict(_SPEC_V2),
    "seedance-2.0-ultra": dict(_SPEC_V2, resolutions=RES_V2_ULTRA),
    "seedance-2.5":       {
        "resolutions":  RES_V25,
        "duration_min": -1,          # -1 = let the model choose the length
        "duration_max": MAX_DURATION_V25,
        "ref_limits":   REF_LIMITS_V25,
        "audio_only":   True,        # 2.5 can generate from audio alone
        "poll_timeout": 2400,        # 30s clips outlast the 2.0 20-minute budget
    },
}

# Union of every resolution any model supports, 720p first so the default is valid
# for all of them. The per-model list is enforced in generate().
RES_ALL = ["720p", "1080p", "480p", "2k"]


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
    """Send reference images to any Seedance generation node.

    image_1 is required. Connect image_2 through image_9 as needed.

    For more than 9 images, chain collectors: wire this node's output into the
    next one's existing_images input. Seedance 2.0 caps out at 9 reference
    images, Seedance 2.5 at 30 — the generation node rejects anything over its
    own limit before the request is sent."""

    CATEGORY = "Seedance AM/References"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image_1": ("IMAGE",),
            },
            "optional": {
                "existing_images": ("SEEDANCE_IMAGE_LIST", {"forceInput": True,
                                                            "tooltip": "Chain another Reference Images node here "
                                                                       "to go past 9 images (Seedance 2.5)."}),
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
                image_5=None, image_6=None, image_7=None, image_8=None, image_9=None,
                existing_images=None):
        images = list(existing_images) if existing_images else []
        images.append(image_1)
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


# Reference media limits, per AnyFast's own model docs. 2.5 doubled the length
# ceiling; the 2-second floor and the format list are the same for both, and a
# clip under 2s is rejected outright rather than padded.
MEDIA_LIMITS = {
    "seedance-2.0": {"audio_max": 15.0, "video_max": 15.0, "video_mb": 50},
    "seedance-2.5": {"audio_max": 30.0, "video_max": 30.0, "video_mb": 200},
}
MEDIA_MIN_SECONDS = 2.0
AUDIO_MAX_MB      = 15

# Offered on the reference nodes. "seedance-2.0" is the safe default: 15s plays
# on both models, while a 30s clip prepared for 2.5 is rejected by 2.0.
# Plain ASCII on purpose: these strings are compared by value between the saved
# workflow, the frontend and the backend, and a non-ASCII character in that path
# is one encoding mismatch away from "value not available".
MEDIA_TARGETS = ["seedance-2.0 (max 15s, safe for both)",
                 "seedance-2.5 (max 30s)",
                 "no trim"]


def _target_limits(target):
    """Map the reference nodes' target dropdown onto MEDIA_LIMITS."""
    if str(target).startswith("seedance-2.5"):
        return MEDIA_LIMITS["seedance-2.5"]
    if str(target).startswith("no trim"):
        return None
    return MEDIA_LIMITS["seedance-2.0"]


def _media_duration_seconds(file_path):
    """Duration in seconds, or None if nothing on this machine can read it.

    torchaudio.info was removed in recent torchaudio builds — it raised
    'module torchaudio has no attribute info' here, which the old code swallowed,
    so oversized audio sailed straight through to a 400. Each route is tried in
    turn instead of trusting one."""
    try:
        import torchaudio
        info = torchaudio.info(file_path)
        return info.num_frames / info.sample_rate
    except Exception:
        pass
    try:
        import soundfile as sf
        with sf.SoundFile(file_path) as handle:
            return len(handle) / handle.samplerate
    except Exception:
        pass
    try:
        import torchaudio
        waveform, sample_rate = torchaudio.load(file_path)
        return waveform.shape[-1] / sample_rate
    except Exception:
        pass
    # ffmpeg prints "Duration: HH:MM:SS.ss" to stderr even with no output file.
    try:
        import subprocess
        ffmpeg = _find_ffmpeg()
        if ffmpeg:
            result = subprocess.run([ffmpeg, "-i", file_path], capture_output=True, text=True)
            match = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", result.stderr or "")
            if match:
                hours, minutes, seconds = match.groups()
                return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    except Exception:
        pass
    return None


def _check_media_floor(file_path, duration, kind):
    """Seedance rejects references shorter than 2s. Say so before spending a call."""
    if duration is not None and duration < MEDIA_MIN_SECONDS:
        raise ValueError(
            f"{kind} reference is {duration:.2f}s — Seedance requires at least "
            f"{MEDIA_MIN_SECONDS:.0f}s. Use a longer clip.\n{file_path}"
        )


_AUDIO_MAX_SECONDS = 15.0   # legacy default, kept for the AUDIO-dict path


def _audio_dict_to_wav(audio_dict, target="seedance-2.0"):
    """Save a ComfyUI AUDIO dict {waveform, sample_rate} to a temp WAV file.

    Trims to the target model's ceiling if needed. Returns temp path — caller
    deletes it."""
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
    duration = waveform.shape[-1] / sample_rate
    if duration < MEDIA_MIN_SECONDS:
        raise ValueError(
            f"Audio is {duration:.2f}s — Seedance requires at least "
            f"{MEDIA_MIN_SECONDS:.0f}s. Use a longer clip."
        )
    limits = _target_limits(target)
    max_seconds = limits["audio_max"] if limits else None
    if max_seconds and duration > max_seconds:
        print(f"[Seedance] Audio {duration:.2f}s exceeds the {max_seconds:.0f}s limit for "
              f"{target} — trimming")
        waveform = waveform[..., :int(max_seconds * sample_rate)]
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    torchaudio.save(tmp.name, waveform.cpu(), sample_rate)
    return tmp.name


def _trim_audio_file_if_needed(file_path, target="seedance-2.0"):
    """Prepare an audio file for the chosen Seedance model.

    Trims anything over the target's ceiling (15s on 2.0, 30s on 2.5) and
    refuses anything under the 2s floor. Returns (path, needs_cleanup); path is
    the original when no work was needed."""
    limits = _target_limits(target)
    if limits is None:
        return file_path, False

    max_seconds = limits["audio_max"]
    duration = _media_duration_seconds(file_path)
    if duration is None:
        print("[Seedance] Could not read the audio duration on this machine — sending as is. "
              f"If AnyFast rejects it, trim the clip to under {max_seconds:.0f}s yourself.")
        return file_path, False

    _check_media_floor(file_path, duration, "Audio")
    if duration <= max_seconds:
        print(f"[Seedance] Audio {duration:.2f}s — within the {max_seconds:.0f}s limit for {target}")
        return file_path, False

    print(f"[Seedance] Audio {duration:.2f}s exceeds the {max_seconds:.0f}s limit for "
          f"{target} — trimming")
    try:
        import tempfile
        import torchaudio
        waveform, sample_rate = torchaudio.load(file_path)
        waveform = waveform[..., :int(max_seconds * sample_rate)]
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp.close()
        torchaudio.save(tmp.name, waveform.cpu(), sample_rate)
        return tmp.name, True
    except Exception as e:
        # ffmpeg can do the same cut without torchaudio.
        try:
            import subprocess
            import tempfile
            ffmpeg = _find_ffmpeg()
            if not ffmpeg:
                raise RuntimeError("ffmpeg not found") from e
            tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            tmp.close()
            subprocess.run([ffmpeg, "-y", "-i", file_path, "-t", str(max_seconds), tmp.name],
                           capture_output=True, check=True)
            return tmp.name, True
        except Exception as e2:
            raise RuntimeError(
                f"Audio is {duration:.2f}s, over the {max_seconds:.0f}s limit for {target}, "
                f"and it could not be trimmed automatically ({e2}). Trim it yourself, or "
                f"install ffmpeg (pip install imageio-ffmpeg)."
            ) from e2


def _prepare_video_for_target(file_path, target):
    """Trim a reference video to the target model's ceiling and check the floor.

    Returns (path, needs_cleanup). Cutting video needs ffmpeg; without it the
    file goes through untouched and AnyFast decides, which at least fails with a
    clear message rather than silently truncating."""
    limits = _target_limits(target)
    if limits is None:
        return file_path, False

    max_seconds = limits["video_max"]
    size_mb = os.path.getsize(file_path) / (1024 * 1024)
    if size_mb > limits["video_mb"]:
        raise ValueError(
            f"Reference video is {size_mb:.1f} MB — {target} allows "
            f"{limits['video_mb']} MB. Re-export it smaller.\n{file_path}"
        )

    duration = _media_duration_seconds(file_path)
    if duration is None:
        print("[Seedance] Could not read the video duration — sending as is.")
        return file_path, False

    _check_media_floor(file_path, duration, "Video")
    if duration <= max_seconds:
        print(f"[Seedance] Video {duration:.2f}s, {size_mb:.1f} MB — within the limits for {target}")
        return file_path, False

    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        raise ValueError(
            f"Reference video is {duration:.2f}s — {target} allows {max_seconds:.0f}s, and "
            f"ffmpeg was not found to trim it. Install it (pip install imageio-ffmpeg) or "
            f"trim the clip yourself.\n{file_path}"
        )

    print(f"[Seedance] Video {duration:.2f}s exceeds the {max_seconds:.0f}s limit for "
          f"{target} — trimming")
    import subprocess
    import tempfile
    tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    tmp.close()
    # Re-encode rather than stream-copy: a copy cuts at the nearest keyframe and
    # can overshoot the limit, which is exactly what we are trying to avoid.
    result = subprocess.run(
        [ffmpeg, "-y", "-i", file_path, "-t", str(max_seconds),
         "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", tmp.name],
        capture_output=True, text=True,
    )
    if result.returncode != 0 or not os.path.exists(tmp.name):
        raise RuntimeError(f"ffmpeg could not trim the video:\n{(result.stderr or '')[-500:]}")
    return tmp.name, True


class SeedanceReferenceVideo:
    """Upload a reference video to AnyFast assets and return an asset:// URI.

    Connect api + a video source. Optionally pass an existing_group_id to
    reuse a group across runs (saves the CreateAssetGroup round-trip).
    The group_id output shows the group used — save it for next time.

    Video source — connect one of:
    - A ComfyUI Load Video node to the 'video' input, OR
    - Pick a file from the 'video_file' dropdown, OR
    - Paste an absolute path into 'video_path'."""

    CATEGORY = "Seedance AM/References"

    @classmethod
    def INPUT_TYPES(cls):
        files = ["none"] + _list_files([".mp4", ".mov", ".avi", ".webm"])
        return {
            "required": {
                "api": ("SEEDANCE_API",),
            },
            "optional": {
                "existing_group_id": ("STRING", {"forceInput": True}),
                "video_path": ("STRING", {"default": "", "placeholder": "C:\\Users\\...\\video.mp4"}),
                "video_file": (files,),
                "video":      ("VIDEO", {"forceInput": True}),
                # Appended last — ComfyUI serialises widget values positionally.
                "target":     (MEDIA_TARGETS, {
                    "tooltip": "Which model this clip is for. Seedance 2.0 accepts 2-15s up to "
                               "50 MB, 2.5 accepts 2-30s up to 200 MB. Over-long clips are "
                               "trimmed for you when ffmpeg is available."}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("reference_video", "group_id")
    FUNCTION     = "upload"
    OUTPUT_NODE  = True

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        if kwargs.get("video") is not None:
            return float("nan")
        return kwargs.get("video_path", "") or kwargs.get("video_file", "")

    def upload(self, api, existing_group_id=None, video_path=None, video_file=None, video=None,
               target=MEDIA_TARGETS[0]):
        cleanup   = False
        file_path = None

        if video is not None:
            file_path, cleanup = _video_input_to_path(video)
            print(f"[Seedance] Using Load Video node input: {file_path}")
        elif video_path and video_path.strip().strip('"').strip("'") not in ("", "none"):
            file_path = video_path.strip().strip('"').strip("'")
            if not os.path.isabs(file_path) and os.sep not in file_path and "/" not in file_path:
                file_path = os.path.join(folder_paths.get_input_directory(), file_path)
            print(f"[Seedance] Using video_path: {file_path}")
        elif video_file and video_file != "none":
            file_path = os.path.join(folder_paths.get_input_directory(), video_file)
            print(f"[Seedance] Using video_file dropdown: {video_file}")
        else:
            raise ValueError(
                "Connect a Load Video node, pick from 'video_file', or paste a path in 'video_path'."
            )

        try:
            file_path, prepared = _prepare_video_for_target(file_path, target)
            cleanup = cleanup or prepared
            filename = os.path.basename(file_path)
            group_id = _ensure_group(api, "seedance-video-refs", existing_group_id)
            asset_uri, _, _ = _upload_asset(api, "Video", filename,
                                            group_id=group_id, file_path=file_path)
            print(f"[Seedance] Reference video → {asset_uri}  group={group_id}")
            return {"ui": {"text": [group_id]}, "result": (asset_uri, group_id)}
        finally:
            if cleanup and file_path and os.path.exists(file_path):
                os.remove(file_path)


class SeedanceReferenceAudio:
    """Prepare a reference audio clip for Seedance generation.

    reference_audio is a VOICE / RHYTHM STYLE reference — it tells the model
    what the voice should sound like (timbre, delivery) or what rhythm to follow.
    It does NOT become the audio track of the output video automatically.

    TWO USE CASES:
    1. Lip-sync with cloned voice  →  keep generate_audio=True, write dialogue in
       double quotes in the prompt:  @audio1. "Say this out loud."
       Seedance generates speech in the voice style of your clip and syncs the lips.

    2. Embed exact audio in video  →  set generate_audio=False and also connect
       this node's output to SaveVideo's reference_audio input.
       SaveVideo will mux the file in after generation.

    Audio source — connect one of:
    - A ComfyUI Load Audio node to the 'audio' input, OR
    - Paste an absolute path into 'audio_path', OR
    - Pick a file from the 'audio_file' dropdown.

    Files ≤ 10 MB are sent as base64; larger files are uploaded to a temp host.
    Audio is auto-trimmed to 15 s if it exceeds the API limit."""

    CATEGORY = "Seedance AM/References"

    @classmethod
    def INPUT_TYPES(cls):
        files = ["none"] + _list_files([".mp3", ".wav", ".ogg", ".flac", ".m4a"])
        return {
            "required": {},
            "optional": {
                # Link inputs, not widgets — adding them cannot shift the saved
                # positional widget values of existing workflows.
                "api":               ("SEEDANCE_API",),
                "existing_group_id": ("STRING", {"forceInput": True}),
                "audio_file": (files,),
                "audio_path": ("STRING", {"default": "", "placeholder": "C:\\Users\\...\\audio.mp3"}),
                "audio":      ("AUDIO", {"forceInput": True}),
                # Appended last — ComfyUI serialises widget values positionally.
                "target":     (MEDIA_TARGETS, {
                    "tooltip": "Which model this clip is for. Seedance 2.0 accepts 2-15s, "
                               "2.5 accepts 2-30s; anything longer is trimmed for you. "
                               "Leave on 2.0 if you might use either."}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("reference_audio", "group_id")
    FUNCTION     = "upload"

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        if kwargs.get("audio") is not None:
            return float("nan")
        return kwargs.get("audio_path", "") or kwargs.get("audio_file", "")

    def upload(self, api=None, existing_group_id=None, audio_path=None, audio_file=None,
               audio=None, target=MEDIA_TARGETS[0]):
        cleanup   = False
        file_path = None

        if audio is not None:
            file_path = _audio_dict_to_wav(audio, target=target)
            cleanup   = True
            print(f"[Seedance] Using Load Audio node input (saved to temp WAV)")
        elif audio_path and audio_path.strip().strip('"').strip("'") not in ("", "none"):
            file_path = audio_path.strip().strip('"').strip("'")
            if not os.path.isabs(file_path) and os.sep not in file_path and "/" not in file_path:
                file_path = os.path.join(folder_paths.get_input_directory(), file_path)
            print(f"[Seedance] Using audio_path: {file_path}")
            file_path, cleanup = _trim_audio_file_if_needed(file_path, target=target)
        elif audio_file and audio_file != "none":
            file_path = os.path.join(folder_paths.get_input_directory(), audio_file)
            print(f"[Seedance] Using audio_file dropdown: {audio_file}")
            file_path, cleanup = _trim_audio_file_if_needed(file_path, target=target)
        else:
            raise ValueError(
                "Provide a file path in 'audio_path', connect a Load Audio node, "
                "or pick a file from the 'audio_file' dropdown."
            )

        try:
            with open(file_path, "rb") as f:
                file_bytes = f.read()
            size_mb = len(file_bytes) / (1024 * 1024)
            if size_mb > AUDIO_MAX_MB:
                raise ValueError(
                    f"Audio is {size_mb:.1f} MB — Seedance allows {AUDIO_MAX_MB} MB. "
                    f"Export it smaller or shorter.\n{file_path}"
                )

            # Preferred route: the AnyFast asset system, the same one images and
            # video already use. Base64 audio is listed as supported but is
            # rejected by some channels with "Invalid base64 audio_url", so it is
            # only the fallback for when no api is connected.
            if api is not None:
                group_id  = _ensure_group(api, "seedance-audio-refs", existing_group_id)
                name      = os.path.splitext(os.path.basename(file_path))[0] or "reference-audio"
                asset_uri, _verify, group_id = _upload_asset(
                    api, "Audio", name, group_id=group_id, file_path=file_path
                )
                _wait_for_asset_active(api, asset_uri, group_id)
                print(f"[Seedance] Reference audio → {asset_uri}  group={group_id}")
                return {"ui": {"text": [f"{asset_uri}\ngroup_id: {group_id}"]},
                        "result": (asset_uri, group_id)}

            ext      = os.path.splitext(file_path)[1].lower()
            mime_map = {".mp3": "audio/mpeg", ".wav": "audio/wav",
                        ".ogg": "audio/ogg",  ".flac": "audio/flac", ".m4a": "audio/mp4"}
            mime     = mime_map.get(ext, "audio/wav")
            if len(file_bytes) <= 10 * 1024 * 1024:
                audio_url = f"data:{mime};base64,{base64.b64encode(file_bytes).decode('ascii')}"
                print(f"[Seedance] Reference audio → base64 ({len(file_bytes)//1024} KB). "
                      "Connect 'api' to upload it as an asset instead if this is rejected.")
            else:
                audio_url = _upload_to_temp_host(file_bytes, os.path.basename(file_path))
                print(f"[Seedance] Reference audio → {audio_url}")
            return {"ui": {"text": ["base64 (no api connected)"]},
                    "result": (audio_url, "")}
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

def _split_ref_urls(value):
    """Split a reference STRING input into a list of URLs, ONE PER LINE.

    Seedance 2.5 accepts up to 10 video and 10 audio references, but the node
    exposes a single STRING socket for each, so several references travel down
    one socket separated by newlines. A lone URL is unaffected.

    Newlines only — never commas. A base64 data URI is
    'data:audio/mpeg;base64,AAAA...', so splitting on commas tore it in half and
    sent the fragment after the comma as a second, malformed reference. AnyFast
    answered with 'content[N].audio_url.url ... is not valid: invalid url'.
    Query strings and some CDN URLs contain commas too."""
    if not value:
        return []
    return [part.strip() for part in str(value).splitlines() if part.strip()]


class _V2Base:
    CATEGORY         = "Seedance AM/Core"
    RESOLUTIONS      = RES_V2
    MODEL_ID         = "seedance"
    DURATION_DEFAULT = 5          # 2.5 subclasses raise this — longer durations supported
    DURATION_MAX     = MAX_DURATION
    DURATION_MIN     = 4          # 2.5 lowers this to -1 ("let the model choose")
    REF_LIMITS       = REF_LIMITS_V2
    AUDIO_ONLY_OK    = False      # 2.5 can generate from an audio reference alone
    POLL_TIMEOUT     = 1200       # 2.5 raises this — 30s clips take longer to render

    def _spec(self, model=None):
        """Limits to enforce for this request.

        The legacy one-model-per-node classes answer from their class attributes.
        The unified SeedanceVideo node overrides this to look the limits up from
        the model the user picked in the dropdown."""
        return {
            "model_id":     self.MODEL_ID,
            "resolutions":  self.RESOLUTIONS,
            "duration_min": self.DURATION_MIN,
            "duration_max": self.DURATION_MAX,
            "ref_limits":   self.REF_LIMITS,
            "audio_only":   self.AUDIO_ONLY_OK,
            "poll_timeout": self.POLL_TIMEOUT,
        }

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "api":            ("SEEDANCE_API",),
                "prompt":         ("STRING", {"multiline": True, "default": ""}),
                "resolution":     (cls.RESOLUTIONS,),
                "ratio":          (RATIO_V2,),
                "duration":       ("INT", {"default": cls.DURATION_DEFAULT, "min": cls.DURATION_MIN,
                                           "max": cls.DURATION_MAX, "step": 1,
                                           "tooltip": "Clip length in seconds. On Seedance 2.5, -1 lets the "
                                                      "model choose (required for edit tasks)."}),
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
                # reference_audio: voice/rhythm style reference — does NOT become the audio track.
                # For lip-sync: keep generate_audio=True, write dialogue in double quotes in prompt.
                # To embed exact audio: set generate_audio=False + connect to SaveVideo too.
                "reference_video":  ("STRING", {"forceInput": True,
                                                "tooltip": "Video reference URL. One URL per line to send several "
                                                           "(2.0: up to 3, 2.5: up to 10)."}),
                "reference_audio":  ("STRING", {"forceInput": True,
                                                "tooltip": "Audio reference URL. One URL per line to send several "
                                                           "(2.0: up to 3, 2.5: up to 10)."}),
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
                 anyfast_refs=None, **kwargs):

        # I2V (start the video from a literal first_frame) and R2V (style/identity,
        # video or audio references) are mutually exclusive — they cannot be mixed in
        # one request. The anyfast_refs path enforces this internally for asset-based
        # refs; this guard covers the direct first_frame IMAGE input as well.
        if first_frame is not None and (
            reference_images or anyfast_refs or reference_video or reference_audio
        ):
            raise ValueError(
                "Cannot mix I2V (first_frame) with R2V references (reference_images, "
                "anyfast_refs, reference_video, reference_audio). Use one mode at a time."
            )

        spec     = self._spec(kwargs.get("model"))
        model_id = spec["model_id"]

        # The unified node offers every resolution any model supports, so the one
        # the user picked may not be valid for the model they picked.
        if resolution not in spec["resolutions"]:
            raise ValueError(
                f"{model_id} does not support {resolution}. "
                f"Supported: {', '.join(spec['resolutions'])}."
            )

        # duration = -1 means "let the model choose the length" and is 2.5-only. The
        # widget min already blocks it on 2.0, but a converted/primitive input can
        # still feed any integer, so validate the value itself.
        if duration == -1:
            if spec["duration_min"] != -1:
                raise ValueError(
                    f"duration = -1 (automatic length) is only supported by Seedance 2.5. "
                    f"Use 4–{spec['duration_max']} seconds on {model_id}."
                )
        elif not (4 <= duration <= spec["duration_max"]):
            raise ValueError(
                f"duration must be between 4 and {spec['duration_max']} seconds"
                + (" (or -1 for automatic)." if spec["duration_min"] == -1 else ".")
                + f" Got {duration}."
            )

        # One socket can carry several video/audio references (one URL per line).
        video_urls = _split_ref_urls(reference_video)
        audio_urls = _split_ref_urls(reference_audio)

        # Images can arrive through both doors at once: asset:// entries for real
        # people, plain tensors for objects and styles. They are counted and tagged
        # together — @image1..N spans the combined list, assets first.
        asset_image_count = (
            sum(1 for e in anyfast_refs if e.get("role") == "reference_image")
            if anyfast_refs else 0
        )
        direct_image_count = len(reference_images) if reference_images else 0
        image_ref_count = asset_image_count + direct_image_count

        limits = spec["ref_limits"]
        for kind, count in (("image", image_ref_count),
                            ("video", len(video_urls)),
                            ("audio", len(audio_urls))):
            if count > limits[kind]:
                raise ValueError(
                    f"{model_id} accepts at most {limits[kind]} {kind} reference(s), got {count}."
                )

        # Seedance requires @image1, @video1, @audio1 tags in the prompt so the
        # model knows how to use each reference. Auto-append any missing tags.
        prompt_lower = prompt.lower()
        # Only reference_image entries get an @imageN tag; first/last frame do not.
        for i in range(1, image_ref_count + 1):
            tag = f"@image{i}"
            if tag not in prompt_lower:
                prompt = prompt + f" {tag}"
                prompt_lower = prompt.lower()
        for i in range(1, len(video_urls) + 1):
            tag = f"@video{i}"
            if tag not in prompt_lower:
                prompt = prompt + f" {tag}"
                prompt_lower = prompt.lower()
        for i in range(1, len(audio_urls) + 1):
            tag = f"@audio{i}"
            if tag not in prompt_lower:
                prompt = prompt + f" {tag}"
                prompt_lower = prompt.lower()

        if audio_urls and not spec["audio_only"]:
            # Seedance 2.0 needs at least one image or video reference alongside audio.
            # Seedance 2.5 lifted this — it can generate from an audio reference alone.
            has_other_ref = anyfast_refs or reference_images or video_urls
            if not has_other_ref:
                raise ValueError(
                    "Seedance 2.0 requires at least one image (or video) reference alongside reference_audio.\n"
                    "Connect a reference image via anyfast_refs (SeedanceFaceRef)\n"
                    "or via reference_images (SeedanceRefImages), add a reference_video,\n"
                    "or switch to the Seedance 2.5 node, which supports audio-only generation."
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
            if only_first_frame and direct_image_count:
                raise ValueError(
                    "A single first_frame from anyfast_refs cannot be combined with "
                    "reference_images. Use frame control or references, not both."
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

        # Plain-tensor references are appended in BOTH cases. They used to sit in
        # the else branch, so connecting a face through anyfast_refs silently threw
        # away everything on reference_images — no error, just a video generated
        # without the object references the user wired in.
        if reference_images:
            for img_tensor in reference_images:
                content.append({
                    "type":      "image_url",
                    "image_url": {"url": _tensor_to_b64(img_tensor)},
                    "role":      "reference_image",
                })

        for url_value in video_urls:
            content.append({
                "type":      "video_url",
                "video_url": {"url": url_value},
                "role":      "reference_video",
            })
        for url_value in audio_urls:
            content.append({
                "type":      "audio_url",
                "audio_url": {"url": url_value},
                "role":      "reference_audio",
            })

        payload = {
            "model":          model_id,
            "content":        content,
            "resolution":     resolution,
            "ratio":          ratio,
            "duration":       duration,
            "generate_audio": generate_audio,
            "watermark":      watermark,
        }
        if seed != -1:
            payload["seed"] = seed
        payload.update(self.extra_payload(**kwargs))

        url, task_id, frame = _submit_and_poll(api, payload, poll_timeout=spec["poll_timeout"])
        return (url, task_id, frame)

    def extra_payload(self, **kwargs):
        """Model-specific payload fields. Overridden by the 2.5 node."""
        return {}


class SeedanceVideo(_V2Base):
    """Generate a video with any Seedance 2.x model.

    One node for the whole family — pick the model in the `model` dropdown
    instead of swapping nodes. The dropdown narrows `resolution` to what the
    selected model actually supports; the same limits are enforced server-side,
    so the node still refuses an impossible combination if the UI script is not
    loaded.

    | model              | resolution         | duration   | refs img/vid/aud |
    |--------------------|--------------------|------------|------------------|
    | seedance-2.0       | 480p/720p/1080p    | 4-15s      | 9 / 3 / 3        |
    | seedance-2.0-fast  | 480p/720p/1080p    | 4-15s      | 9 / 3 / 3        |
    | seedance-2.0-mini  | 480p/720p/1080p    | 4-15s      | 9 / 3 / 3        |
    | seedance-2.0-ultra | 720p/1080p/2k      | 4-15s      | 9 / 3 / 3        |
    | seedance-2.5       | 480p/720p          | -1 or 4-30 | 30 / 10 / 10     |

    Seedance 2.5 additionally supports audio-only generation and `web_search`.
    """

    CATEGORY    = "Seedance AM"
    MODEL_IDS   = list(MODEL_SPECS.keys())
    # The widgets span the UNION of what every model allows; generate() then
    # rejects a combination the selected model does not support, and the .js
    # narrows the widgets in the UI. Without the union here the widget itself
    # would clamp — a 4-15 duration slider makes 2.5's 30s unreachable whenever
    # the UI script has not loaded.
    RESOLUTIONS  = RES_ALL
    DURATION_MIN = min(s["duration_min"] for s in MODEL_SPECS.values())
    DURATION_MAX = max(s["duration_max"] for s in MODEL_SPECS.values())

    @classmethod
    def INPUT_TYPES(cls):
        types = super().INPUT_TYPES()
        required = {"api": types["required"].pop("api"),
                    "model": (cls.MODEL_IDS, {"default": "seedance-2.0",
                                              "tooltip": "Which Seedance model to call. Narrows the "
                                                         "resolution list and the duration range."})}
        required.update(types["required"])
        types["required"] = required
        types["optional"]["web_search"] = ("BOOLEAN", {
            "default": False,
            "tooltip": "Text-to-video only — let the model look up current information "
                       "(products, events, weather) before generating.",
        })
        return types

    def _spec(self, model=None):
        if model not in MODEL_SPECS:
            raise ValueError(
                f"Unknown model '{model}'. Pick one of: {', '.join(self.MODEL_IDS)}."
            )
        return dict(MODEL_SPECS[model], model_id=model)

    def extra_payload(self, web_search=False, **_ignored):
        return {"tools": [{"type": "web_search"}]} if web_search else {}


# --------------------------------------------------------------------------- #
# Legacy one-model-per-node classes.
# Superseded by SeedanceVideo. They stay registered so workflows saved against
# them keep loading and keep their exact previous behaviour (note the older
# `seedance` / `seedance-fast` aliases rather than the documented dotted ids).
# DEPRECATED hides them from the Add Node menu on ComfyUI versions that honour it.
# --------------------------------------------------------------------------- #

class Seedance2(_V2Base):
    """Seedance 2.0 — Text/Image to Video (480 / 720 / 1080p, up to 15s, with audio)."""
    RESOLUTIONS = RES_V2
    MODEL_ID    = "seedance"
    DEPRECATED  = True


class Seedance2Fast(_V2Base):
    """Seedance 2.0 Fast — Same capabilities as standard, faster generation."""
    RESOLUTIONS = RES_V2
    MODEL_ID    = "seedance-fast"
    DEPRECATED  = True


class Seedance2Ultra(_V2Base):
    """Seedance 2.0 Ultra — Highest quality (720p / 1080p / 2k, up to 15s, with audio)."""
    RESOLUTIONS = RES_V2_ULTRA
    MODEL_ID    = "seedance-2.0-ultra"
    DEPRECATED  = True


# --------------------------------------------------------------------------- #
# Seedance 2.5 generation node
# AnyFast exposes exactly ONE 2.5 model id — "seedance-2.5". There is no Fast,
# Ultra or Pro tier (verified against GET /v1/models, 2026-08-07), so 2.5 is a
# single node rather than the three-node family 2.0 needs.
# Same request shape as 2.0 (T2V / I2V / R2V, same reference + asset system), so
# it subclasses _V2Base and only adjusts the model-specific limits.
# --------------------------------------------------------------------------- #

class SeedanceV25(_V2Base):
    """Seedance 2.5 — up to 30s in a single pass, up to 50 references.

    Differences vs 2.0:
      * duration up to 30s (2.0: 15s); -1 lets the model choose the length
      * up to 50 references — 30 images, 10 videos, 10 audio (2.0: 9 / 3 / 3)
      * generates from an audio reference alone, with no image or video
      * resolution is 480p or 720p ONLY — 2.5 trades resolution for length,
        so use a 2.0 node when you need 1080p / 2k / 4k
      * web_search can ground text-to-video prompts in current information

    Task families (from the AnyFast guide) and the parameters they need:
      text-to-video / reference-to-video → any ratio, duration -1 or 4-30
      video editing (add/remove/replace)  → ratio "adaptive" AND duration -1
      video extension (continue a clip)   → ratio "adaptive"
      first/last-frame                    → ratio "adaptive"
    """

    CATEGORY         = "Seedance AM/2.5"
    RESOLUTIONS      = RES_V25
    MODEL_ID         = "seedance-2.5"
    DURATION_DEFAULT = 10
    DURATION_MIN     = -1            # -1 = let the model choose the length
    DURATION_MAX     = MAX_DURATION_V25
    REF_LIMITS       = REF_LIMITS_V25
    AUDIO_ONLY_OK    = True
    POLL_TIMEOUT     = 2400          # 30s clips render well past the 2.0 20-min budget
    DEPRECATED       = True          # superseded by SeedanceVideo (model = seedance-2.5)

    @classmethod
    def INPUT_TYPES(cls):
        types = super().INPUT_TYPES()
        types["optional"]["web_search"] = ("BOOLEAN", {
            "default": False,
            "tooltip": "Text-to-video only — let the model look up current information "
                       "(products, events, weather) before generating.",
        })
        return types

    def extra_payload(self, web_search=False, **_ignored):
        if not web_search:
            return {}
        return {"tools": [{"type": "web_search"}]}


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

    Optional reference_audio input: connect the same SeedanceReferenceAudio
    output here (alongside the generation node) to auto-mux your audio into
    the final mp4. Requires ffmpeg (included in most ComfyUI portable installs).
    Only needed when generate_audio=False and you want exact audio in the video."""

    CATEGORY = "Seedance AM/Core"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "video_url":       ("STRING", {"forceInput": True}),
                "filename_prefix": ("STRING", {"default": "seedance"}),
                "save_to":         (["output", "input"], {"default": "output"}),
            },
            "optional": {
                # Connect the same SeedanceReferenceAudio output here to embed
                # the audio in the saved video (reference_audio only drives motion,
                # it is never automatically included in the generated video).
                "reference_audio": ("STRING", {"forceInput": True}),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("saved_path",)
    OUTPUT_NODE  = True
    FUNCTION     = "save"

    def save(self, video_url, filename_prefix, save_to, reference_audio=None):
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

        # Mux reference audio into the video if provided
        if reference_audio and reference_audio.strip():
            filepath = self._mux_audio(filepath, reference_audio.strip(), output_dir, filename_prefix, timestamp)
            filename = os.path.basename(filepath)

        entry = {"filename": filename, "subfolder": subfolder, "type": save_to}
        preview_ui = {"gifs": [entry], "videos": [entry]}
        if comfy_ui is not None and comfy_io is not None:
            try:
                folder_type = comfy_io.FolderType.output if save_to == "output" else comfy_io.FolderType.input
                preview_ui = comfy_ui.PreviewVideo(
                    [comfy_ui.SavedResult(filename, subfolder, folder_type)]
                ).as_dict()
            except Exception:
                pass  # fall back to legacy format already set above

        return {
            "ui": {
                "text": [filepath],
                **preview_ui,
            },
            "result": (filepath,),
        }

    def _mux_audio(self, video_path, audio_url, output_dir, prefix, timestamp):
        """Decode or download audio_url to a temp file, mux into video, return new path."""
        import subprocess, tempfile, base64

        ffmpeg = _find_ffmpeg()
        if not ffmpeg:
            print("[Seedance] ffmpeg not found — skipping audio mux. Install imageio-ffmpeg to enable.")
            return video_path

        audio_tmp = None
        try:
            if audio_url.startswith("data:"):
                # base64 data URI — decode to temp file
                header, b64data = audio_url.split(",", 1)
                ext = ".wav"
                for fmt in ("mpeg", "mp3", "wav", "ogg", "flac", "mp4"):
                    if fmt in header:
                        ext = ".mp3" if fmt in ("mpeg", "mp3") else f".{fmt}"
                        break
                audio_tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
                audio_tmp.write(base64.b64decode(b64data))
                audio_tmp.close()
                audio_src = audio_tmp.name
                print(f"[Seedance] Muxing base64 audio into video")
            else:
                # public URL — download to temp file
                ext = os.path.splitext(audio_url.split("?")[0])[1] or ".mp3"
                audio_tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
                audio_tmp.close()
                resp = requests.get(audio_url, timeout=60)
                resp.raise_for_status()
                with open(audio_tmp.name, "wb") as f:
                    f.write(resp.content)
                audio_src = audio_tmp.name
                print(f"[Seedance] Muxing downloaded audio into video")

            out_path = os.path.join(output_dir, f"{prefix}_{timestamp}_audio.mp4")
            cmd = [
                ffmpeg, "-y",
                "-i", video_path,
                "-i", audio_src,
                "-c:v", "copy",
                "-c:a", "aac",
                "-map", "0:v:0",
                "-map", "1:a:0",
                "-shortest",
                out_path,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                print(f"[Seedance] ffmpeg mux failed:\n{result.stderr[-500:]}")
                return video_path

            # replace the silent video with the muxed one
            os.remove(video_path)
            print(f"[Seedance] Audio muxed: {os.path.basename(out_path)}")
            return out_path

        except Exception as e:
            print(f"[Seedance] Audio mux error: {e}")
            return video_path
        finally:
            if audio_tmp and os.path.exists(audio_tmp.name):
                os.remove(audio_tmp.name)


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
# Mux Audio — embed an audio file into a saved video using ffmpeg
# --------------------------------------------------------------------------- #

def _find_ffmpeg():
    """Return path to an ffmpeg executable, or None if not found."""
    import shutil
    exe = shutil.which("ffmpeg") or shutil.which("ffmpeg.exe")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    return None


class SeedanceMuxAudio:
    """Merge an audio file into a saved video using ffmpeg.

    Use this when you want an audio file embedded in the video but the audio
    is NOT going through SeedanceReferenceAudio (e.g. background music, a
    separately recorded voiceover, or a second audio pass).

    For the common case of embedding reference audio, use SaveVideo's built-in
    reference_audio input instead — it handles it automatically on save.

    Requires ffmpeg (included in most ComfyUI portable installs via imageio_ffmpeg).

    Audio source — connect one of:
    - A ComfyUI Load Audio node to the 'audio' input, OR
    - Pick a file from the 'audio_file' dropdown, OR
    - Paste an absolute path into 'audio_path'."""

    CATEGORY = "Seedance AM/Utilities"

    @classmethod
    def INPUT_TYPES(cls):
        files = ["none"] + _list_files([".mp3", ".wav", ".ogg", ".flac", ".m4a"])
        return {
            "required": {
                "video_path": ("STRING", {"forceInput": True}),
            },
            "optional": {
                "audio_file": (files,),
                "audio_path": ("STRING", {"default": "", "placeholder": "C:\\Users\\...\\audio.mp3"}),
                "audio":      ("AUDIO", {"forceInput": True}),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("video_path",)
    OUTPUT_NODE  = True
    FUNCTION     = "mux"

    def mux(self, video_path, audio_file=None, audio_path=None, audio=None):
        import subprocess, tempfile, shutil

        # --- resolve audio to a local file ---
        audio_tmp   = None
        audio_src   = None

        if audio is not None:
            audio_src = _audio_dict_to_wav(audio)
            audio_tmp = audio_src
            print(f"[Seedance Mux] Using Load Audio node input")
        elif audio_path and audio_path.strip().strip('"').strip("'") not in ("", "none"):
            audio_src = audio_path.strip().strip('"').strip("'")
            print(f"[Seedance Mux] Using audio_path: {audio_src}")
        elif audio_file and audio_file != "none":
            audio_src = os.path.join(folder_paths.get_input_directory(), audio_file)
            print(f"[Seedance Mux] Using audio_file: {audio_src}")
        else:
            raise ValueError(
                "Connect an audio source: Load Audio node, audio_path, or audio_file dropdown."
            )

        ffmpeg = _find_ffmpeg()
        if not ffmpeg:
            raise RuntimeError(
                "ffmpeg not found. Install it (pip install imageio-ffmpeg) or add it to PATH."
            )

        video_path = video_path.strip().strip('"')
        if not os.path.isfile(video_path):
            raise FileNotFoundError(f"Video file not found: {video_path}")

        out_path = video_path.replace(".mp4", "_audio.mp4")
        # avoid clobbering an existing file
        if os.path.exists(out_path):
            base, ext = os.path.splitext(out_path)
            out_path = f"{base}_{int(time.time())}{ext}"

        try:
            cmd = [
                ffmpeg,
                "-y",
                "-i", video_path,
                "-i", audio_src,
                "-c:v", "copy",
                "-c:a", "aac",
                "-map", "0:v:0",
                "-map", "1:a:0",
                "-shortest",
                out_path,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(f"ffmpeg error:\n{result.stderr[-1000:]}")
            print(f"[Seedance Mux] Saved: {os.path.basename(out_path)}")
        finally:
            if audio_tmp and os.path.exists(audio_tmp):
                os.remove(audio_tmp)

        filename  = os.path.basename(out_path)
        subfolder = ""
        entry     = {"filename": filename, "subfolder": subfolder, "type": "output"}
        return {
            "ui":     {"text": [out_path], "gifs": [entry], "videos": [entry]},
            "result": (out_path,),
        }


# --------------------------------------------------------------------------- #
# Registration
# --------------------------------------------------------------------------- #

NODE_CLASS_MAPPINGS = {
    # Config
    "SeedanceApiKey":      SeedanceApiKey,
    # Generation — one node for every Seedance 2.x model
    "SeedanceVideo":       SeedanceVideo,
    # Legacy one-model-per-node classes. Kept registered (and marked DEPRECATED)
    # so saved workflows keep loading; SeedanceVideo replaces all of them.
    "Seedance2":           Seedance2,
    "Seedance2Fast":       Seedance2Fast,
    "Seedance2Ultra":      Seedance2Ultra,
    "SeedanceV25Standard": SeedanceV25,
    # References
    "SeedanceReferenceVideo":   SeedanceReferenceVideo,
    "SeedanceReferenceAudio":   SeedanceReferenceAudio,
    "SeedanceRefImages":        SeedanceRefImages,
    # Face / asset
    "SeedanceFaceRef":          SeedanceFaceRef,
    "SeedanceIdentity":         SeedanceIdentity,
    "SeedanceAssetRef":         SeedanceAssetRef,
    "SeedanceUploadAsset":      SeedanceUploadAsset,
    # Extend
    "SeedanceExtend":      SeedanceExtend,
    # Output / utilities
    "SeedanceSaveVideo":   SeedanceSaveVideo,
    "SeedanceMuxAudio":    SeedanceMuxAudio,
    "SeedanceShowText":    SeedanceShowText,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    # Config
    "SeedanceApiKey":      "Seedance AM - API Key",
    # Generation
    "SeedanceVideo":       "Seedance AM - Video",
    # Legacy (deprecated — use Seedance AM - Video)
    "Seedance2":           "Seedance AM 2.0 - Standard (legacy)",
    "Seedance2Fast":       "Seedance AM 2.0 - Fast (legacy)",
    "Seedance2Ultra":      "Seedance AM 2.0 - Ultra (legacy)",
    "SeedanceV25Standard": "Seedance AM 2.5 (legacy)",
    # References
    "SeedanceReferenceVideo":   "Seedance AM - Reference Video",
    "SeedanceReferenceAudio":   "Seedance AM - Reference Audio",
    "SeedanceRefImages":        "Seedance AM - Reference Images (9 per node, chainable)",
    # Face / asset
    "SeedanceFaceRef":          "Seedance AM - Face / Person Reference (asset)",
    "SeedanceIdentity":         "Seedance AM - Identity (saved person)",
    "SeedanceAssetRef":         "Seedance AM - Asset Reference",
    "SeedanceUploadAsset":      "Seedance AM - Upload Asset",
    # Extend
    "SeedanceExtend":      "Seedance AM - Extend Video",
    # Output / utilities
    "SeedanceSaveVideo":   "Seedance AM - Save Video",
    "SeedanceMuxAudio":    "Seedance AM - Mux Audio into Video",
    "SeedanceShowText":    "Seedance AM - Show Text",
}


