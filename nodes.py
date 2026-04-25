import os
import time
import base64
import io
import tempfile
import requests
import numpy as np
from PIL import Image

try:
    import torch
except ImportError:
    torch = None

import folder_paths


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


def _poll_v2(base_url, api_key, task_id, timeout=600, interval=5):
    """Poll Seedance 2.0 — status and video_url are at root level."""
    headers  = {"Authorization": f"Bearer {api_key}"}
    url      = f"{base_url}/v1/video/generations/{task_id}"
    deadline = time.time() + timeout

    time.sleep(3)

    while time.time() < deadline:
        r    = requests.get(url, headers=headers, timeout=30)
        r.raise_for_status()
        body = r.json()
        status = body.get("status", "")

        print(f"[Seedance] task_id={task_id}  status={status}")

        if status == "completed":
            return body["video_url"]
        if status == "failed":
            raise RuntimeError(f"Seedance generation failed: {body.get('error', 'unknown')}")

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


def _submit_and_poll(api, payload):
    base_url = api["base_url"].rstrip("/")
    api_key  = api["api_key"].strip()

    if not api_key:
        raise ValueError("API key is empty — paste your AnyFast key in the Seedance API Key node.")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    r = requests.post(f"{base_url}/v1/video/generations", json=payload, headers=headers, timeout=300)

    if not r.ok:
        raise RuntimeError(f"Seedance API error {r.status_code}: {r.text}")

    task_id = r.json()["id"]
    print(f"[Seedance] Job submitted — task_id={task_id}")

    video_url = _poll_v2(base_url, api_key, task_id)
    frame     = _first_frame(video_url)
    return video_url, task_id, frame


# --------------------------------------------------------------------------- #
# fal.ai provider
# --------------------------------------------------------------------------- #

_FAL_BASE     = "https://fal.run"
_FAL_QUEUE    = "https://queue.fal.run"
_FAL_APP_BASE = "bytedance/seedance-2.0"

# Maps our MODEL_ID → fal.ai endpoint path segment
_FAL_VARIANT  = {
    "seedance":        "",          # standard
    "seedance-fast":   "fast/",     # fast
    "seedance-2.0-ultra": "",       # no ultra on fal — falls back to standard
}

# Maps our ratio values → fal.ai aspect_ratio values
_FAL_RATIO_MAP = {"adaptive": "auto"}


def _fal_generate(api, params):
    """Submit a generation job to fal.ai and return (video_url, task_id, first_frame).

    Dispatches to the right fal.ai endpoint (T2V / I2V / R2V) based on params.
    Images are sent as base64 data URIs; fal.ai accepts them for all image fields."""
    api_key  = api["api_key"].strip()
    if not api_key:
        raise ValueError("API key is empty — paste your fal.ai key in the Seedance API Key node.")

    headers = {
        "Authorization": f"Key {api_key}",
        "Content-Type":  "application/json",
    }

    model_id = params.get("model_id", "seedance")
    variant  = _FAL_VARIANT.get(model_id, "")

    # --- determine endpoint ---
    first_frame     = params.get("first_frame")
    last_frame      = params.get("last_frame")
    ref_images      = params.get("reference_images") or []
    ref_video       = (params.get("reference_video") or "").strip()
    ref_audio       = (params.get("reference_audio") or "").strip()

    has_references  = bool(ref_images or ref_video or ref_audio)
    has_first_frame = first_frame is not None

    if has_references:
        endpoint = f"{variant}reference-to-video"
    elif has_first_frame:
        endpoint = f"{variant}image-to-video"
    else:
        endpoint = f"{variant}text-to-video"

    app_id = f"{_FAL_APP_BASE}/{endpoint}"

    # --- build payload ---
    ratio      = _FAL_RATIO_MAP.get(params["ratio"], params["ratio"])
    resolution = params["resolution"]   # fal.ai uses same strings: 480p / 720p
    duration   = str(params["duration"])

    payload = {
        "prompt":         params["prompt"],
        "resolution":     resolution,
        "aspect_ratio":   ratio,
        "duration":       duration,
        "generate_audio": params["generate_audio"],
    }
    if params.get("seed", -1) != -1:
        payload["seed"] = params["seed"]

    # I2V: start / end frames
    if has_first_frame:
        payload["image_url"] = _tensor_to_b64(first_frame)
    if last_frame is not None:
        payload["end_image_url"] = _tensor_to_b64(last_frame)

    # R2V: reference arrays
    if ref_images:
        payload["image_urls"] = [_tensor_to_b64(img) for img in ref_images]
    if ref_video:
        payload["video_urls"] = [ref_video]
    if ref_audio:
        payload["audio_urls"] = [ref_audio]

    print(f"[Seedance/fal.ai] Submitting to {app_id}")

    # Submit to async queue
    r = requests.post(f"{_FAL_QUEUE}/{app_id}", json=payload, headers=headers, timeout=60)
    if not r.ok:
        raise RuntimeError(f"fal.ai submission error {r.status_code}: {r.text}")

    task_id = r.json()["request_id"]
    print(f"[Seedance/fal.ai] Job submitted — request_id={task_id}")

    # Poll for completion
    status_url = f"{_FAL_QUEUE}/fal-ai/queue/requests/{task_id}/status"
    result_url = f"{_FAL_QUEUE}/fal-ai/queue/requests/{task_id}"
    deadline   = time.time() + 600
    time.sleep(3)

    while time.time() < deadline:
        r = requests.get(status_url, headers=headers, timeout=30)
        r.raise_for_status()
        status = r.json().get("status", "")
        print(f"[Seedance/fal.ai] request_id={task_id}  status={status}")

        if status == "COMPLETED":
            r = requests.get(result_url, headers=headers, timeout=30)
            r.raise_for_status()
            video_url = r.json()["video"]["url"]
            frame     = _first_frame(video_url)
            return video_url, task_id, frame

        if status in ("FAILED", "ERROR"):
            raise RuntimeError(f"fal.ai generation failed: {r.json()}")

        time.sleep(5)

    raise TimeoutError(f"fal.ai timed out after 600s (request_id={task_id})")


# --------------------------------------------------------------------------- #
# Asset Management helpers
# --------------------------------------------------------------------------- #

def _extract_id(resp_json, *keys):
    """Try several field name candidates; raise with raw response if none found."""
    for k in keys:
        if k in resp_json:
            return resp_json[k]
    nested = resp_json.get("data", {})
    for k in keys:
        if k in nested:
            return nested[k]
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

    group_id = _extract_id(r.json(), "GroupId", "group_id", "id", "ID")
    print(f"[Seedance Assets] Group ready: {group_id}")
    return group_id


def _upload_asset(api, asset_type, name, group_id=None, image_tensor=None, file_path=None):
    """Upload an image tensor or a local file to Seedance Asset Management.

    Returns (asset_uri, verify_url, resolved_group_id) where verify_url may be
    None if the API does not require a liveness check for this upload."""
    base_url = api["base_url"].rstrip("/")
    api_key  = api["api_key"].strip()
    headers  = {"Authorization": f"Bearer {api_key}"}

    model_map = {"Image": "volc-asset", "Video": "volc-asset-video", "Audio": "volc-asset-audio"}
    mime_map  = {"Image": "image/png",  "Video": "video/mp4",       "Audio": "audio/mpeg"}

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

    files = {"file": (filename, file_bytes, mime_map[asset_type])}
    data  = {"Name": name, "model": model_map[asset_type]}
    if group_id:
        data["GroupId"] = group_id

    r = requests.post(f"{base_url}/volc/asset/CreateAsset",
                      files=files, data=data, headers=headers, timeout=120)
    if not r.ok:
        raise RuntimeError(f"Asset upload failed {r.status_code}: {r.text}")

    resp = r.json()
    raw_id     = _extract_id(resp, "AssetId", "asset_id", "id", "ID")
    verify_url = _extract_verify_url(resp)
    resolved_group_id = group_id or _extract_optional_id(resp, "GroupId", "group_id", "GroupID")

    if verify_url:
        print(f"[Seedance Assets] *** IDENTITY VERIFICATION REQUIRED ***")
        print(f"[Seedance Assets] Open this link on your phone or browser (< 30 s): {verify_url}")
        if resolved_group_id:
            print(f"[Seedance Assets] After completing the liveness check, save your Group ID: {resolved_group_id}")

    return f"Asset://{raw_id}", verify_url, resolved_group_id


# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

RES_V2       = ["1080p", "720p", "480p"]
RES_V2_ULTRA = ["2K", "1080p", "720p"]
RATIO_V2     = ["16:9", "9:16", "4:3", "3:4", "1:1", "21:9", "adaptive"]
MAX_DURATION = 15


# --------------------------------------------------------------------------- #
# API Key node
# --------------------------------------------------------------------------- #

class SeedanceApiKey:
    CATEGORY = "Seedance"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "api_key":  ("STRING", {"default": "", "multiline": False}),
                "provider": (["anyfast", "fal.ai"],),
                "base_url": ("STRING", {"default": "https://www.anyfast.ai", "multiline": False,
                                        "tooltip": "Only used for the 'anyfast' provider. Ignored for fal.ai."}),
            }
        }

    RETURN_TYPES = ("SEEDANCE_API",)
    RETURN_NAMES = ("api",)
    FUNCTION = "configure"

    def configure(self, api_key, provider, base_url):
        return ({"api_key": api_key, "provider": provider, "base_url": base_url},)


# --------------------------------------------------------------------------- #
# Image Batch node — collect multiple reference images
# --------------------------------------------------------------------------- #

class SeedanceImageBatch:
    """Legacy — kept so existing workflows don't break. Use SeedanceRefImages instead."""
    CATEGORY = "Seedance"

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"image_1": ("IMAGE",)}, "optional": {"image_2": ("IMAGE",)}}

    RETURN_TYPES = ("SEEDANCE_IMAGE_LIST",)
    RETURN_NAMES = ("reference_images",)
    FUNCTION     = "batch"

    def batch(self, image_1, image_2=None):
        images = [image_1]
        if image_2 is not None:
            images.append(image_2)
        return (images,)


class SeedanceRefImages:
    """Send up to 9 reference images to any Seedance 2.0 node.

    image_1 is required. Connect image_2 through image_9 as needed."""

    CATEGORY = "Seedance"

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


class SeedanceReferenceVideo:
    """Pick a video from your local disk, upload it, and get an Asset:// ID
    ready to wire into reference_video on any Seedance 2.0 generation node.

    Pass an existing_group_id to reuse a previously verified identity group
    and avoid creating a new one each time."""

    CATEGORY = "Seedance"

    @classmethod
    def INPUT_TYPES(cls):
        files = _list_files([".mp4", ".mov", ".avi", ".webm"])
        return {
            "required": {
                "api":        ("SEEDANCE_API",),
                "video_file": (files,),
                "name":       ("STRING", {"default": "ref_video"}),
                "group_name": ("STRING", {"default": "comfyui-assets"}),
            },
            "optional": {
                "existing_group_id": ("STRING", {"forceInput": True}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("reference_video", "group_id")
    FUNCTION     = "upload"

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return kwargs.get("video_file", "")

    def upload(self, api, video_file, name, group_name, existing_group_id=None):
        if video_file == "none":
            raise ValueError("No video found — use the 'Choose Video' button to upload one.")
        file_path = os.path.join(folder_paths.get_input_directory(), video_file)
        group_id  = _ensure_group(api, group_name, existing_group_id)
        asset_uri, _, group_id = _upload_asset(api, "Video", name, group_id, file_path=file_path)
        print(f"[Seedance] Reference video uploaded: {asset_uri}  group_id={group_id}")
        return (asset_uri, group_id)


class SeedanceReferenceAudio:
    """Pick an audio file from your local disk, upload it, and get an Asset:// ID
    ready to wire into reference_audio on any Seedance 2.0 generation node.

    Pass an existing_group_id to reuse a previously verified identity group
    and avoid creating a new one each time."""

    CATEGORY = "Seedance"

    @classmethod
    def INPUT_TYPES(cls):
        files = _list_files([".mp3", ".wav", ".ogg", ".flac", ".m4a"])
        return {
            "required": {
                "api":        ("SEEDANCE_API",),
                "audio_file": (files,),
                "name":       ("STRING", {"default": "ref_audio"}),
                "group_name": ("STRING", {"default": "comfyui-assets"}),
            },
            "optional": {
                "existing_group_id": ("STRING", {"forceInput": True}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("reference_audio", "group_id")
    FUNCTION     = "upload"

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return kwargs.get("audio_file", "")

    def upload(self, api, audio_file, name, group_name, existing_group_id=None):
        if audio_file == "none":
            raise ValueError("No audio found — use the 'Choose Audio' button to upload one.")
        file_path = os.path.join(folder_paths.get_input_directory(), audio_file)
        group_id  = _ensure_group(api, group_name, existing_group_id)
        asset_uri, _, group_id = _upload_asset(api, "Audio", name, group_id, file_path=file_path)
        print(f"[Seedance] Reference audio uploaded: {asset_uri}  group_id={group_id}")
        return (asset_uri, group_id)


# --------------------------------------------------------------------------- #
# Upload Asset node — handles group creation + upload in one step
# --------------------------------------------------------------------------- #

class SeedanceUploadAsset:
    """Upload an image, video, or audio to Seedance Asset Management.

    Returns an Asset:// ID and the Group ID. Pass an existing_group_id to
    reuse a previously verified identity group without creating a new one."""

    CATEGORY = "Seedance/Assets"

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

class SeedanceCreateHumanAsset:
    """Upload a portrait for identity-verified real human video generation.

    First run  — leave existing_group_id empty. The node will display a
    verification link directly in its preview area. Open that link on your
    phone, complete the liveness check, then copy the Group ID shown below
    and save it.

    Next runs  — paste the saved Group ID into existing_group_id. No new
    verification is needed; the API matches faces automatically."""

    CATEGORY   = "Seedance"
    OUTPUT_NODE = True

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "api":        ("SEEDANCE_API",),
                "image":      ("IMAGE",),
                "name":       ("STRING", {"default": "portrait"}),
                "group_name": ("STRING", {"default": "comfyui-human-assets"}),
            },
            "optional": {
                "existing_group_id": ("STRING", {"default": "", "multiline": False,
                                                  "tooltip": "Paste your saved Group ID to skip re-verification"}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("asset_id", "group_id", "verify_url")
    FUNCTION     = "upload"

    def upload(self, api, image, name, group_name, existing_group_id=None):
        eid = existing_group_id.strip() if existing_group_id else None

        if eid:
            group_id = eid
            asset_uri, verify_url, resolved_group_id = _upload_asset(
                api, "Image", name, group_id, image_tensor=image
            )
            group_id = resolved_group_id or group_id
        else:
            try:
                asset_uri, verify_url, group_id = _upload_asset(
                    api, "Image", name, image_tensor=image
                )
            except RuntimeError as e:
                original_error = str(e)
                group_id = _ensure_group(api, group_name, None)
                try:
                    asset_uri, verify_url, resolved_group_id = _upload_asset(
                        api, "Image", name, group_id, image_tensor=image
                    )
                except RuntimeError as retry_error:
                    raise RuntimeError(
                        "Human asset upload failed on both provider flows. "
                        f"Direct CreateAsset error: {original_error} | "
                        f"CreateAssetGroup+CreateAsset error: {retry_error}"
                    ) from retry_error
                group_id = resolved_group_id or group_id

        if not group_id:
            raise RuntimeError("Asset upload succeeded but no group_id was returned by the provider.")

        if verify_url:
            lines = [
                "⚠  VERIFICATION REQUIRED",
                "",
                "1. Copy the link below and open it on your phone:",
                verify_url,
                "",
                "2. Complete the liveness check (under 30 seconds).",
                "",
                "3. Save your Group ID for future uploads:",
                group_id,
                "",
                "4. After verifying, use the asset_id output for generation:",
                asset_uri,
            ]
        else:
            lines = [
                "✓  Ready — no verification needed",
                "",
                f"asset_id   {asset_uri}",
                f"group_id   {group_id}",
            ]

        return {"ui": {"text": lines, "verify_url": [verify_url or ""]},
                "result": (asset_uri, group_id, verify_url or "")}


# --------------------------------------------------------------------------- #
# Seedance 2.0 generation nodes
# — T2V when no first_frame connected; I2V when first_frame connected
# — reference_images: connect SeedanceImageBatch output (1–9 style refs)
# — reference_video / reference_audio: connect SeedanceUploadAsset output
# --------------------------------------------------------------------------- #

class _V2Base:
    CATEGORY    = "Seedance"
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
                # Style / context references — use SeedanceImageBatch for 1–9 images
                "reference_images": ("SEEDANCE_IMAGE_LIST",),
                # Asset references — use SeedanceUploadAsset to get Asset:// IDs
                "reference_video":  ("STRING", {"forceInput": True}),
                "reference_audio":  ("STRING", {"forceInput": True}),
                # ID-verified human asset — connect asset_id from SeedanceCreateHumanAsset
                "human_asset_id":   ("STRING", {"forceInput": True,
                                                 "tooltip": "asset_id from 'Create Human Asset (ID Verified)' — AnyFast only"}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING", "IMAGE")
    RETURN_NAMES = ("video_url", "task_id", "first_frame")
    FUNCTION     = "generate"
    OUTPUT_NODE  = True

    def generate(self, api, prompt, resolution, ratio, duration, generate_audio,
                 watermark, seed, first_frame=None, last_frame=None,
                 reference_images=None, reference_video=None, reference_audio=None,
                 human_asset_id=None):

        # Seedance requires @image1, @video1, @audio1 tags in the prompt so the
        # model knows how to use each reference. Auto-append any missing tags.
        # human_asset_id (if present) is always @image1; reference_images follow.
        img_start = 1
        if human_asset_id and human_asset_id.strip():
            if "@image1" not in prompt:
                prompt = prompt + " @image1"
            img_start = 2
        if reference_images:
            for i in range(img_start, img_start + len(reference_images)):
                tag = f"@image{i}"
                if tag not in prompt:
                    prompt = prompt + f" {tag}"
        if reference_video and reference_video.strip():
            if "@video1" not in prompt:
                prompt = prompt + " @video1"
        if reference_audio and reference_audio.strip():
            if "@audio1" not in prompt:
                prompt = prompt + " @audio1"

        print(f"[Seedance] Final prompt: {prompt}")

        content = [{"type": "text", "text": prompt}]

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
        if human_asset_id and human_asset_id.strip():
            content.append({
                "type":      "image_url",
                "image_url": {"url": human_asset_id.strip()},
                "role":      "reference_image",
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

        provider = api.get("provider", "anyfast")

        if provider == "fal.ai":
            url, task_id, frame = _fal_generate(api, {
                "model_id":        self.MODEL_ID,
                "prompt":          prompt,   # already has @ tags
                "resolution":      resolution,
                "ratio":           ratio,
                "duration":        duration,
                "generate_audio":  generate_audio,
                "seed":            seed,
                "first_frame":     first_frame,
                "last_frame":      last_frame,
                "reference_images": reference_images,
                "reference_video": reference_video or "",
                "reference_audio": reference_audio or "",
                # human_asset_id uses Asset:// URIs — not supported on fal.ai; ignored
            })
        else:
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
    """Seedance 2.0 Ultra — Highest quality (720p / 1080p / 2K, up to 15s, with audio)."""
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

    CATEGORY = "Seedance"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "api":        ("SEEDANCE_API",),
                "task_id":    ("STRING", {"forceInput": True}),
                "prompt":     ("STRING", {"multiline": True, "default": ""}),
                "duration":   ("INT",    {"default": 5, "min": 4, "max": MAX_DURATION, "step": 1}),
                "resolution": (RES_V2,),
            }
        }

    RETURN_TYPES = ("STRING", "STRING", "IMAGE")
    RETURN_NAMES = ("video_url", "task_id", "first_frame")
    FUNCTION     = "extend"
    OUTPUT_NODE  = True

    def extend(self, api, task_id, prompt, duration, resolution):
        base_url = api["base_url"].rstrip("/")
        api_key  = api["api_key"].strip()

        if not api_key:
            raise ValueError("API key is empty — paste your AnyFast key in the Seedance API Key node.")

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model":      "seedance",
            "request_id": task_id,
            "prompt":     prompt,
            "duration":   duration,
            "resolution": resolution,
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
    """Download and save the generated video to the ComfyUI output folder."""

    CATEGORY = "Seedance"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "video_url":       ("STRING", {"forceInput": True}),
                "filename_prefix": ("STRING", {"default": "seedance"}),
            }
        }

    RETURN_TYPES = ()
    OUTPUT_NODE  = True
    FUNCTION     = "save"

    def save(self, video_url, filename_prefix):
        output_dir = folder_paths.get_output_directory()
        timestamp  = int(time.time())
        filename   = f"{filename_prefix}_{timestamp}.mp4"
        filepath   = os.path.join(output_dir, filename)

        print(f"[Seedance] Downloading video → {filepath}")
        r = requests.get(video_url, stream=True, timeout=300)
        if not r.ok:
            raise RuntimeError(f"Failed to download video: {r.status_code}")

        with open(filepath, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)

        print(f"[Seedance] Saved: {filename}")
        return {"ui": {"videos": [{"filename": filename, "subfolder": "", "type": "output"}]}}


# --------------------------------------------------------------------------- #
# Show Text node — display any STRING output directly in the node body
# --------------------------------------------------------------------------- #

class SeedanceShowText:
    """Display any text value (asset_id, group_id, verify_url, video_url…)
    directly inside the node so you can read and copy it without extra nodes."""

    CATEGORY    = "Seedance"
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
# Human Asset Panel — show asset_id, group_id, verify_url in one place
# --------------------------------------------------------------------------- #

class SeedanceHumanAssetPanel:
    """Consolidate human asset outputs into one centered panel.

    Use this right after Create Human Asset so the verification link, asset_id,
    and group_id stay together in one readable block while still passing all
    values through to the rest of the graph."""

    CATEGORY    = "Seedance"
    OUTPUT_NODE = True

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "asset_id": ("STRING", {"forceInput": True}),
                "group_id": ("STRING", {"forceInput": True}),
            },
            "optional": {
                "verify_url": ("STRING", {"forceInput": True}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("asset_id", "group_id", "verify_url")
    FUNCTION     = "show"

    def show(self, asset_id, group_id, verify_url=""):
        asset_id = str(asset_id or "")
        group_id = str(group_id or "")
        verify_url = str(verify_url or "")

        lines = [
            "HUMAN ASSET PANEL",
            "",
            f"asset_id   {asset_id}",
            f"group_id   {group_id}",
        ]
        if verify_url:
            lines.extend(["", f"verify_url {verify_url}"])

        return {
            "ui": {
                "text": lines,
                "asset_id": [asset_id],
                "group_id": [group_id],
                "verify_url": [verify_url],
            },
            "result": (asset_id, group_id, verify_url),
        }


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
    # Assets
    "SeedanceCreateHumanAsset": SeedanceCreateHumanAsset,
    "SeedanceUploadAsset":      SeedanceUploadAsset,
    "SeedanceReferenceVideo":   SeedanceReferenceVideo,
    "SeedanceReferenceAudio":   SeedanceReferenceAudio,
    # Utilities
    "SeedanceImageBatch":  SeedanceImageBatch,
    "SeedanceRefImages":   SeedanceRefImages,
    # Extend
    "SeedanceExtend":      SeedanceExtend,
    # Output
    "SeedanceSaveVideo":   SeedanceSaveVideo,
    "SeedanceShowText":    SeedanceShowText,
    "SeedanceHumanAssetPanel": SeedanceHumanAssetPanel,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    # Config
    "SeedanceApiKey":      "Seedance — API Key",
    # 2.0 generation
    "Seedance2":           "Seedance 2.0 — Standard",
    "Seedance2Fast":       "Seedance 2.0 — Fast",
    "Seedance2Ultra":      "Seedance 2.0 — Ultra",
    # Assets
    "SeedanceCreateHumanAsset": "Seedance — Create Human Asset (ID Verified)",
    "SeedanceUploadAsset":      "Seedance — Upload Asset",
    "SeedanceReferenceVideo":   "Seedance — Reference Video",
    "SeedanceReferenceAudio":   "Seedance — Reference Audio",
    # Utilities
    "SeedanceImageBatch":  "Seedance — Image Batch (References)",
    "SeedanceRefImages":   "Seedance — Reference Images (9 slots)",
    # Extend
    "SeedanceExtend":      "Seedance — Extend Video",
    # Output
    "SeedanceSaveVideo":   "Seedance — Save Video",
    "SeedanceShowText":    "Seedance — Show Text",
    "SeedanceHumanAssetPanel": "Seedance — Human Asset Panel",
}
