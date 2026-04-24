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


def _submit_and_poll(api, payload):
    base_url = api["base_url"].rstrip("/")
    api_key  = api["api_key"].strip()

    if not api_key:
        raise ValueError("API key is empty — paste your AnyFast key in the Seedance API Key node.")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    r = requests.post(f"{base_url}/v1/video/generations", json=payload, headers=headers, timeout=60)

    if not r.ok:
        raise RuntimeError(f"Seedance API error {r.status_code}: {r.text}")

    task_id = r.json()["id"]
    print(f"[Seedance] Job submitted — task_id={task_id}")

    return _poll_v2(base_url, api_key, task_id), task_id


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


def _ensure_group(api, group_name):
    """Create an asset group and return its ID."""
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


def _upload_asset(api, asset_type, name, group_id, image_tensor=None, file_path=None):
    """Upload an image tensor or a local file to Seedance Asset Management."""
    base_url = api["base_url"].rstrip("/")
    api_key  = api["api_key"].strip()
    headers  = {"Authorization": f"Bearer {api_key}"}

    model_map = {"Image": "volc-asset",       "Video": "volc-asset-video", "Audio": "volc-asset-audio"}
    mime_map  = {"Image": "image/png",         "Video": "video/mp4",        "Audio": "audio/mpeg"}

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
    data  = {"GroupId": group_id, "Name": name, "model": model_map[asset_type]}

    r = requests.post(f"{base_url}/volc/asset/CreateAsset",
                      files=files, data=data, headers=headers, timeout=120)
    if not r.ok:
        raise RuntimeError(f"Asset upload failed {r.status_code}: {r.text}")

    raw_id = _extract_id(r.json(), "AssetId", "asset_id", "id", "ID")
    return f"Asset://{raw_id}"


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
                "base_url": ("STRING", {"default": "https://www.anyfast.ai", "multiline": False}),
            }
        }

    RETURN_TYPES = ("SEEDANCE_API",)
    RETURN_NAMES = ("api",)
    FUNCTION = "configure"

    def configure(self, api_key, base_url):
        return ({"api_key": api_key, "base_url": base_url},)


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
# Upload Asset node — handles group creation + upload in one step
# --------------------------------------------------------------------------- #

class SeedanceUploadAsset:
    """Upload an image, video, or audio to Seedance Asset Management.

    Returns an Asset:// ID to wire into reference_video or reference_audio
    on any Seedance 2.0 generation node. An asset group is created
    automatically — you don't need a separate Create Group node."""

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
                "image":     ("IMAGE",),
                "file_path": ("STRING", {"forceInput": True}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("asset_id",)
    FUNCTION     = "upload"

    def upload(self, api, asset_type, name, group_name, image=None, file_path=None):
        if image is None and not (file_path and file_path.strip()):
            raise ValueError("Connect either an image or a file_path (for video/audio).")

        group_id = _ensure_group(api, group_name)
        asset_id = _upload_asset(api, asset_type, name, group_id,
                                 image_tensor=image, file_path=file_path)
        print(f"[Seedance Assets] Uploaded {asset_type}: {asset_id}")
        return (asset_id,)


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
            }
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("video_url", "task_id")
    FUNCTION     = "generate"
    OUTPUT_NODE  = True

    def generate(self, api, prompt, resolution, ratio, duration, generate_audio,
                 watermark, seed, first_frame=None, last_frame=None,
                 reference_images=None, reference_video=None, reference_audio=None):

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

        url, task_id = _submit_and_poll(api, payload)
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
    "SeedanceUploadAsset": SeedanceUploadAsset,
    # Utilities
    "SeedanceImageBatch":  SeedanceImageBatch,
    "SeedanceRefImages":   SeedanceRefImages,
    # Output
    "SeedanceSaveVideo":   SeedanceSaveVideo,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    # Config
    "SeedanceApiKey":      "Seedance — API Key",
    # 2.0 generation
    "Seedance2":           "Seedance 2.0 — Standard",
    "Seedance2Fast":       "Seedance 2.0 — Fast",
    "Seedance2Ultra":      "Seedance 2.0 — Ultra",
    # Assets
    "SeedanceUploadAsset": "Seedance — Upload Asset",
    # Utilities
    "SeedanceImageBatch":  "Seedance — Image Batch (References)",
    "SeedanceRefImages":   "Seedance — Reference Images (9 slots)",
    # Output
    "SeedanceSaveVideo":   "Seedance — Save Video",
}
