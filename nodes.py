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

        print(f"[Seedance] task_id={task_id}  status={status}")

        if status == "SUCCESS":
            return inner["data"]["video_url"]
        if status == "FAILED":
            raise RuntimeError(f"Seedance generation failed: {inner.get('fail_reason', 'unknown')}")

        time.sleep(interval)

    raise TimeoutError(f"Seedance timed out after {timeout}s (task_id={task_id})")


def _submit_and_poll(api, payload):
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
    print(f"[Seedance] Job submitted — task_id={task_id}")

    video_url = _poll(base_url, api_key, task_id)
    return video_url, task_id


# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

RES_PRO  = ["1080p", "720p", "480p"]
RES_FAST = ["720p", "480p"]
RATIO    = ["16:9", "9:16"]
MAX_DURATION = 5


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
    "SeedanceApiKey":    SeedanceApiKey,
    "SeedanceT2V":       SeedanceT2V,
    "SeedanceT2VFast":   SeedanceT2VFast,
    "SeedanceI2V":       SeedanceI2V,
    "SeedanceI2VFast":   SeedanceI2VFast,
    "SeedanceSaveVideo": SeedanceSaveVideo,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SeedanceApiKey":    "Seedance — API Key",
    "SeedanceT2V":       "Seedance — Text→Video (Pro)",
    "SeedanceT2VFast":   "Seedance — Text→Video (Fast)",
    "SeedanceI2V":       "Seedance — Image→Video (Pro)",
    "SeedanceI2VFast":   "Seedance — Image→Video (Fast)",
    "SeedanceSaveVideo": "Seedance — Save Video",
}
