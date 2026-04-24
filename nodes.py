import os
import time
import base64
import io
import requests
import numpy as np
from PIL import Image

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


def _poll(base_url, api_key, task_id, timeout=600, interval=5):
    """Polling for Seedance 1.0 — response nested in data.data."""
    headers = {"Authorization": f"Bearer {api_key}"}
    url = f"{base_url}/v1/video/generations/{task_id}"
    deadline = time.time() + timeout

    time.sleep(3)  # job is always queued right after submit

    while time.time() < deadline:
        r = requests.get(url, headers=headers, timeout=30)
        r.raise_for_status()
        body = r.json()
        inner = body.get("data", {})
        status = inner.get("status", "")

        print(f"[Seedance 1.0] task_id={task_id}  status={status}")

        if status == "SUCCESS":
            return inner["data"]["video_url"]
        if status == "FAILED":
            raise RuntimeError(f"Seedance generation failed: {inner.get('fail_reason', 'unknown')}")

        time.sleep(interval)

    raise TimeoutError(f"Seedance timed out after {timeout}s (task_id={task_id})")


def _poll_v2(base_url, api_key, task_id, timeout=600, interval=5):
    """Polling for Seedance 2.0 — status and video_url at root level."""
    headers = {"Authorization": f"Bearer {api_key}"}
    url = f"{base_url}/v1/video/generations/{task_id}"
    deadline = time.time() + timeout

    time.sleep(3)

    while time.time() < deadline:
        r = requests.get(url, headers=headers, timeout=30)
        r.raise_for_status()
        body = r.json()
        status = body.get("status", "")

        print(f"[Seedance 2.0] task_id={task_id}  status={status}")

        if status == "completed":
            return body["video_url"]
        if status == "failed":
            raise RuntimeError(f"Seedance 2.0 generation failed: {body.get('error', 'unknown')}")

        time.sleep(interval)

    raise TimeoutError(f"Seedance 2.0 timed out after {timeout}s (task_id={task_id})")


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


def _upload_asset(api, asset_type, name, group_id, image_tensor=None, file_path=None):
    """Upload an image tensor or a local file to Seedance Asset Management."""
    base_url = api["base_url"].rstrip("/")
    api_key  = api["api_key"].strip()
    headers  = {"Authorization": f"Bearer {api_key}"}

    model_map = {"Image": "volc-asset", "Video": "volc-asset-video", "Audio": "volc-asset-audio"}
    mime_map  = {"Image": "image/png",  "Video": "video/mp4",         "Audio": "audio/mpeg"}

    if image_tensor is not None:
        img_np = (image_tensor[0].numpy() * 255).clip(0, 255).astype(np.uint8)
        pil    = Image.fromarray(img_np).convert("RGB")
        buf    = io.BytesIO()
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
    data  = {"GroupId": group_id, "Name": name, "model": model_map[asset_type]}

    r = requests.post(f"{base_url}/volc/asset/CreateAsset",
                      files=files, data=data, headers=headers, timeout=120)
    if not r.ok:
        raise RuntimeError(f"Asset upload failed {r.status_code}: {r.text}")

    raw_id = _extract_id(r.json(), "AssetId", "asset_id", "id", "ID")
    return f"Asset://{raw_id}"


def _submit_and_poll(api, payload, version=1):
    base_url = api["base_url"].rstrip("/")
    api_key = api["api_key"].strip()

    if not api_key:
        raise ValueError("Seedance API key is empty — enter your AnyFast key in the SeedanceApiKey node.")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    r = requests.post(f"{base_url}/v1/video/generations", json=payload, headers=headers, timeout=60)

    if not r.ok:
        raise RuntimeError(f"Seedance API error {r.status_code}: {r.text}")

    task_id = r.json()["id"]
    print(f"[Seedance {version}.0] Job submitted — task_id={task_id}")

    poll_fn = _poll_v2 if version == 2 else _poll
    video_url = poll_fn(base_url, api_key, task_id)
    return video_url, task_id


# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

# Seedance 1.0
RES_PRO  = ["1080p", "720p", "480p"]
RES_FAST = ["720p", "480p"]
RATIO    = ["16:9", "9:16"]
MAX_DURATION = 5

# Seedance 2.0
RES_V2         = ["1080p", "720p", "480p"]   # standard & fast
RES_V2_ULTRA   = ["2K", "1080p", "720p"]     # ultra only (no 480p, adds 2K)
RATIO_V2       = ["16:9", "9:16", "4:3", "3:4", "1:1", "21:9", "adaptive"]
MAX_DURATION_V2 = 15


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
                "base_url": ("STRING", {"default": "https://www.anyfast.ai", "multiline": False}),
            }
        }

    RETURN_TYPES = ("SEEDANCE_API",)
    RETURN_NAMES = ("api",)
    FUNCTION = "configure"

    def configure(self, api_key, base_url):
        return ({"api_key": api_key, "base_url": base_url},)


# --------------------------------------------------------------------------- #
# Text → Video
# --------------------------------------------------------------------------- #

class _T2VBase:
    CATEGORY    = "Seedance"
    RESOLUTIONS = RES_PRO
    MODEL_ID    = "doubao-seedance-1-0-pro-250528"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "api":          ("SEEDANCE_API",),
                "prompt":       ("STRING", {"multiline": True, "default": ""}),
                "resolution":   (cls.RESOLUTIONS,),
                "ratio":        (RATIO,),
                "duration":     ("INT", {"default": 5, "min": 2, "max": MAX_DURATION, "step": 1}),
                "seed":         ("INT", {"default": -1, "min": -1, "max": 2147483647}),
                "watermark":    ("BOOLEAN", {"default": False}),
                "camera_fixed": ("BOOLEAN", {"default": False}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("video_url", "task_id")
    FUNCTION     = "generate"
    OUTPUT_NODE  = True

    def generate(self, api, prompt, resolution, ratio, duration, seed, watermark, camera_fixed):
        payload = {
            "model":        self.MODEL_ID,
            "content":      [{"type": "text", "text": prompt}],
            "resolution":   resolution,
            "ratio":        ratio,
            "duration":     duration,
            "watermark":    watermark,
            "camera_fixed": camera_fixed,
        }
        if seed != -1:
            payload["seed"] = seed

        url, task_id = _submit_and_poll(api, payload)
        return (url, task_id)


class SeedanceT2V(_T2VBase):
    """Seedance 1.0 Pro — Text to Video (480 / 720 / 1080p)."""
    RESOLUTIONS = RES_PRO
    MODEL_ID    = "doubao-seedance-1-0-pro-250528"


class SeedanceT2VFast(_T2VBase):
    """Seedance 1.0 Pro Fast — Text to Video (480 / 720p)."""
    RESOLUTIONS = RES_FAST
    MODEL_ID    = "doubao-seedance-1-0-pro-fast-251015"


# --------------------------------------------------------------------------- #
# Image → Video — Pro (first frame + optional last frame)
# --------------------------------------------------------------------------- #

class SeedanceI2V:
    """Seedance 1.0 Pro — Image to Video.
    first_frame required. last_frame optional — constrains the ending shot."""

    CATEGORY = "Seedance"
    MODEL_ID  = "doubao-seedance-1-0-pro-250528"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "api":          ("SEEDANCE_API",),
                "first_frame":  ("IMAGE",),
                "prompt":       ("STRING", {"multiline": True, "default": ""}),
                "resolution":   (RES_PRO,),
                "duration":     ("INT", {"default": 5, "min": 2, "max": MAX_DURATION, "step": 1}),
                "seed":         ("INT", {"default": -1, "min": -1, "max": 2147483647}),
                "watermark":    ("BOOLEAN", {"default": False}),
                "camera_fixed": ("BOOLEAN", {"default": False}),
            },
            "optional": {
                "last_frame": ("IMAGE",),
            }
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("video_url", "task_id")
    FUNCTION     = "generate"
    OUTPUT_NODE  = True

    def generate(self, api, first_frame, prompt, resolution, duration, seed,
                 watermark, camera_fixed, last_frame=None):

        content = [
            {"type": "text", "text": prompt},
            {
                "type":      "image_url",
                "image_url": {"url": _tensor_to_b64(first_frame)},
                "role":      "first_frame",
            },
        ]
        if last_frame is not None:
            content.append({
                "type":      "image_url",
                "image_url": {"url": _tensor_to_b64(last_frame)},
                "role":      "last_frame",
            })

        payload = {
            "model":        self.MODEL_ID,
            "content":      content,
            "resolution":   resolution,
            "ratio":        "adaptive",
            "duration":     duration,
            "watermark":    watermark,
            "camera_fixed": camera_fixed,
        }
        if seed != -1:
            payload["seed"] = seed

        url, task_id = _submit_and_poll(api, payload)
        return (url, task_id)


# --------------------------------------------------------------------------- #
# Image → Video — Fast (first frame only, no last_frame)
# --------------------------------------------------------------------------- #

class SeedanceI2VFast:
    """Seedance 1.0 Pro Fast — Image to Video (480 / 720p).
    Only first_frame is supported — last_frame is not available on the Fast model."""

    CATEGORY = "Seedance"
    MODEL_ID  = "doubao-seedance-1-0-pro-fast-251015"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "api":          ("SEEDANCE_API",),
                "first_frame":  ("IMAGE",),
                "prompt":       ("STRING", {"multiline": True, "default": ""}),
                "resolution":   (RES_FAST,),
                "duration":     ("INT", {"default": 5, "min": 2, "max": MAX_DURATION, "step": 1}),
                "seed":         ("INT", {"default": -1, "min": -1, "max": 2147483647}),
                "watermark":    ("BOOLEAN", {"default": False}),
                "camera_fixed": ("BOOLEAN", {"default": False}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("video_url", "task_id")
    FUNCTION     = "generate"
    OUTPUT_NODE  = True

    def generate(self, api, first_frame, prompt, resolution, duration, seed,
                 watermark, camera_fixed):

        content = [
            {"type": "text", "text": prompt},
            {
                "type":      "image_url",
                "image_url": {"url": _tensor_to_b64(first_frame)},
                "role":      "first_frame",
            },
        ]

        payload = {
            "model":        self.MODEL_ID,
            "content":      content,
            "resolution":   resolution,
            "ratio":        "adaptive",
            "duration":     duration,
            "watermark":    watermark,
            "camera_fixed": camera_fixed,
        }
        if seed != -1:
            payload["seed"] = seed

        url, task_id = _submit_and_poll(api, payload)
        return (url, task_id)


# --------------------------------------------------------------------------- #
# Image Batch node — collect multiple reference images for 2.0 nodes
# --------------------------------------------------------------------------- #

class SeedanceImageBatch:
    """Collect 1–9 reference images for Seedance 2.0.
    Increase inputcount to add more slots. Connect output to
    reference_images on any Seedance 2.0 generation node."""

    CATEGORY = "Seedance"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "inputcount": ("INT", {"default": 2, "min": 1, "max": 9, "step": 1}),
                "image_1":    ("IMAGE",),
                "image_2":    ("IMAGE",),
            }
        }

    RETURN_TYPES = ("SEEDANCE_IMAGE_LIST",)
    RETURN_NAMES = ("reference_images",)
    FUNCTION     = "batch"

    def batch(self, inputcount, **kwargs):
        images = []
        for i in range(1, inputcount + 1):
            img = kwargs.get(f"image_{i}")
            if img is not None:
                images.append(img)
        if not images:
            raise ValueError("[Seedance] ImageBatch: no images connected.")
        print(f"[Seedance] ImageBatch: {len(images)} image(s) collected")
        return (images,)


# --------------------------------------------------------------------------- #
# Asset Management nodes
# --------------------------------------------------------------------------- #

class SeedanceCreateGroup:
    """Create a Seedance Asset Group. Run once; wire the group_id to upload nodes."""
    CATEGORY = "Seedance/Assets"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "api":  ("SEEDANCE_API",),
                "name": ("STRING", {"default": "comfyui-assets"}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("group_id",)
    FUNCTION     = "create"

    def create(self, api, name):
        base_url = api["base_url"].rstrip("/")
        api_key  = api["api_key"].strip()
        headers  = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

        r = requests.post(f"{base_url}/volc/asset/CreateAssetGroup",
                          json={"model": "volc-asset", "Name": name},
                          headers=headers, timeout=30)
        if not r.ok:
            raise RuntimeError(f"CreateAssetGroup failed {r.status_code}: {r.text}")

        group_id = _extract_id(r.json(), "GroupId", "group_id", "id", "ID")
        print(f"[Seedance Assets] Group created: {group_id}")
        return (group_id,)


class SeedanceUploadAsset:
    """Upload an image, video, or audio file to Seedance Asset Management.
    Returns an Asset:// ID ready to use in 2.0 generation nodes."""
    CATEGORY = "Seedance/Assets"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "api":        ("SEEDANCE_API",),
                "group_id":   ("STRING", {"forceInput": True}),
                "asset_type": (["Image", "Video", "Audio"],),
                "name":       ("STRING", {"default": "asset"}),
            },
            "optional": {
                "image":     ("IMAGE",),
                "file_path": ("STRING", {"forceInput": True}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("asset_id",)
    FUNCTION     = "upload"

    def upload(self, api, group_id, asset_type, name, image=None, file_path=None):
        if image is None and not (file_path and file_path.strip()):
            raise ValueError("Connect either an image or a file_path (for video/audio).")
        asset_id = _upload_asset(api, asset_type, name, group_id.strip(),
                                 image_tensor=image, file_path=file_path)
        print(f"[Seedance Assets] Uploaded {asset_type}: {asset_id}")
        return (asset_id,)


# --------------------------------------------------------------------------- #
# Seedance 2.0 nodes
# — Flexible: T2V when no image connected, I2V when first_frame connected
# — Supports reference_image for style/context anchoring
# — generate_audio available on all 2.0 models
# --------------------------------------------------------------------------- #

class _V2Base:
    CATEGORY    = "Seedance"
    RESOLUTIONS = RES_V2
    MODEL_ID    = "seedance"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "api":             ("SEEDANCE_API",),
                "prompt":          ("STRING", {"multiline": True, "default": ""}),
                "resolution":      (cls.RESOLUTIONS,),
                "ratio":           (RATIO_V2,),
                "duration":        ("INT", {"default": 5, "min": 4, "max": MAX_DURATION_V2, "step": 1}),
                "generate_audio":  ("BOOLEAN", {"default": True}),
                "watermark":       ("BOOLEAN", {"default": False}),
                "seed":            ("INT", {"default": -1, "min": -1, "max": 2147483647}),
            },
            "optional": {
                # Image inputs — pass IMAGE tensor (base64 inline) or leave empty
                "first_frame":       ("IMAGE",),
                "last_frame":        ("IMAGE",),
                "reference_image":   ("IMAGE",),
                # Multiple reference images via SeedanceImageBatch node
                "reference_images":  ("SEEDANCE_IMAGE_LIST",),
                # Asset ID inputs — connect output of SeedanceUploadAsset node
                "reference_video":   ("STRING", {"forceInput": True}),  # Asset://...
                "reference_audio":   ("STRING", {"forceInput": True}),  # Asset://...
            }
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("video_url", "task_id")
    FUNCTION     = "generate"
    OUTPUT_NODE  = True

    def generate(self, api, prompt, resolution, ratio, duration, generate_audio,
                 watermark, seed, first_frame=None, last_frame=None,
                 reference_image=None, reference_images=None,
                 reference_video=None, reference_audio=None):

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
        if reference_image is not None:
            content.append({
                "type":      "image_url",
                "image_url": {"url": _tensor_to_b64(reference_image)},
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

        url, task_id = _submit_and_poll(api, payload, version=2)
        return (url, task_id)


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
# Save Video node — downloads video_url and saves to ComfyUI output folder
# --------------------------------------------------------------------------- #

class SeedanceSaveVideo:
    """Downloads the generated video and saves it to the ComfyUI output folder."""

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
            raise RuntimeError(f"[Seedance] Failed to download video: {r.status_code}")

        with open(filepath, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)

        print(f"[Seedance] Saved: {filename}")
        return {"ui": {"videos": [{"filename": filename, "subfolder": "", "type": "output"}]}}


# --------------------------------------------------------------------------- #
# Registration
# --------------------------------------------------------------------------- #

NODE_CLASS_MAPPINGS = {
    # Config
    "SeedanceApiKey":       SeedanceApiKey,
    # 1.0
    "SeedanceT2V":          SeedanceT2V,
    "SeedanceT2VFast":      SeedanceT2VFast,
    "SeedanceI2V":          SeedanceI2V,
    "SeedanceI2VFast":      SeedanceI2VFast,
    # 2.0
    "Seedance2":            Seedance2,
    "Seedance2Fast":        Seedance2Fast,
    "Seedance2Ultra":       Seedance2Ultra,
    # Asset Management
    "SeedanceCreateGroup":  SeedanceCreateGroup,
    "SeedanceUploadAsset":  SeedanceUploadAsset,
    # Utilities
    "SeedanceImageBatch":   SeedanceImageBatch,
    # Output
    "SeedanceSaveVideo":    SeedanceSaveVideo,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    # Config
    "SeedanceApiKey":       "Seedance — API Key",
    # 1.0
    "SeedanceT2V":          "Seedance 1.0 — Text→Video (Pro)",
    "SeedanceT2VFast":      "Seedance 1.0 — Text→Video (Fast)",
    "SeedanceI2V":          "Seedance 1.0 — Image→Video (Pro)",
    "SeedanceI2VFast":      "Seedance 1.0 — Image→Video (Fast)",
    # 2.0
    "Seedance2":            "Seedance 2.0 — Standard",
    "Seedance2Fast":        "Seedance 2.0 — Fast",
    "Seedance2Ultra":       "Seedance 2.0 — Ultra",
    # Asset Management
    "SeedanceCreateGroup":  "Seedance — Create Asset Group",
    "SeedanceUploadAsset":  "Seedance — Upload Asset",
    # Utilities
    "SeedanceImageBatch":   "Seedance — Image Batch (References)",
    # Output
    "SeedanceSaveVideo":    "Seedance — Save Video",
}
