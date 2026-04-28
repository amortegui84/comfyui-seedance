# ComfyUI-Seedance AM

Generate videos with ByteDance Seedance 2.0 inside ComfyUI.

Supports both `anyfast` and `fal.ai` providers with text-to-video, image-to-video, and reference workflows.
Connect ComfyUI's built-in `Load Video` and `Load Audio` nodes directly to the reference nodes.

## Install

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/amortegui84/comfyui-seedance
cd comfyui-seedance
pip install -r requirements.txt
```

Restart ComfyUI after installation. `opencv-python` is only needed for the `first_frame` IMAGE output pin on generation nodes.

## Quick Start

```text
Seedance AM - API Key -> Seedance AM 2.0 - Standard -> Seedance AM - Save Video
```

1. Add `Seedance AM - API Key`, paste your key, pick `anyfast` or `fal.ai`.
2. Add `Seedance AM 2.0 - Standard`, write a prompt.
3. Connect `video_url` -> `Seedance AM - Save Video`.
4. Run with no image inputs for text-to-video.

## Provider Overview

| Feature | AnyFast | fal.ai |
|---|---|---|
| Text to video | Yes | Yes |
| Image-to-video (first frame) | Via base64/data URI -> `anyfast_refs` | Direct `first_frame` IMAGE connector |
| Reference images | `SeedanceRefImages` -> `reference_images` or `anyfast_refs` | `SeedanceRefImages` -> `reference_images` |
| Reference video + audio | Yes via asset upload | Yes |
| Resolutions | 480p / 720p / 1080p (Standard/Fast); 720p / 1080p / 2k (Ultra) | 720p max |
| Extend video | Yes | No |

## Nodes

| Node | Category | What it does |
|---|---|---|
| `Seedance AM - API Key` | Core | Configure provider (`anyfast` or `fal.ai`) and API key |
| `Seedance AM 2.0 - Standard` | Core | Main generation node using model `seedance` |
| `Seedance AM 2.0 - Fast` | Core | Faster generation variant using model `seedance-fast` |
| `Seedance AM 2.0 - Ultra` | Core | Highest quality variant using model `seedance-2.0-ultra` |
| `Seedance AM - AnyFast Image Upload (base64)` | AnyFast | Encode `first_frame`, `last_frame`, or `reference_image` inputs as base64/data URI refs |
| `Seedance AM - Asset Reference` | AnyFast | Wrap an `asset://` ID into `ANYFAST_IMAGE_REFS`; chain with `existing_refs` |
| `Seedance AM - Upload Asset` | Advanced | Upload image/video/audio to AnyFast storage; waits for `Active`; returns `asset_id` and `group_id` |
| `Seedance AM - Reference Video` | References | Upload a video file to AnyFast and return an `asset://` ID |
| `Seedance AM - Reference Audio` | References | Upload audio to AnyFast and return an `asset://` ID |
| `Seedance AM - Reference Images (9 slots)` | References | Collect up to 9 images as `SEEDANCE_IMAGE_LIST` |
| `Seedance AM - Extend Video` | Core | Extend a previous generation by wiring its `task_id` |
| `Seedance AM - Save Video` | Core | Download and preview the generated mp4 |
| `Seedance AM - Show Text` | Debug | Display any string value inside the node |

## AnyFast Workflows

### Text to Video

```text
SeedanceApiKey -> Seedance2 -> SeedanceSaveVideo
```

This is the known-good baseline.

### Image to Video (recommended in this repo)

```text
LoadImage -> SeedanceAnyfastImageUpload(first_frame) -> anyfast_refs -> Seedance2
```

Why this is the recommended path here:

- It stays in the same direct `image_url` style that already works for `reference_image`.
- In testing, this path has behaved more reliably than the asset-backed `first_frame` path.
- It matches the Seedance guide's direct `image_url` image-to-video pattern.

Important:

- Do not mix `first_frame` / `last_frame` with `reference_image`, `reference_video`, or `reference_audio` in the same request.
- `first_frame` and `last_frame` do not use `@image` tags.

### Reference Images

Option A: direct `reference_images` input

```text
LoadImage x N -> SeedanceRefImages -> reference_images -> Seedance2
```

Option B: AnyFast structured refs

```text
LoadImage x N -> SeedanceAnyfastImageUpload(ref_image_1..N) -> anyfast_refs -> Seedance2
```

Notes:

- Connect up to 9 images.
- `@image1` .. `@imageN` tags are auto-appended if missing.
- Leave `anyfast_refs` disconnected if you want to use the plain `reference_images` port.

### Reference Video and Audio

```text
Load Video -> SeedanceReferenceVideo -> reference_video -> Seedance2
Load Audio -> SeedanceReferenceAudio -> reference_audio -> Seedance2
```

These still use uploaded AnyFast assets and are separate from image `first_frame`.

Notes:

- Each node uploads the file, waits for `Active`, and returns an `asset://` ID.
- `@video1` and `@audio1` are auto-appended if missing.

## fal.ai Workflows

### Image to Video

```text
LoadImage -> Seedance2.first_frame
```

### Reference Images

```text
LoadImage x N -> SeedanceRefImages -> Seedance2.reference_images
```

## Key Parameters

| Parameter | Notes |
|---|---|
| `prompt` | `@image1`..`@image9`, `@video1`, and `@audio1` tags are auto-added when needed |
| `resolution` | `480p` / `720p` / `1080p` (Standard/Fast); `720p` / `1080p` / `2k` (Ultra) |
| `ratio` | `16:9`, `9:16`, `4:3`, `3:4`, `1:1`, `21:9`, `adaptive` |
| `duration` | 4 to 15 seconds |
| `generate_audio` | Auto-generate synced voice, sound effects, and music |
| `watermark` | ByteDance watermark (AnyFast only) |
| `seed` | `-1` for random, any integer for reproducible results |
| `first_frame` | Direct IMAGE input for fal.ai only; for AnyFast use `SeedanceAnyfastImageUpload(first_frame)` -> `anyfast_refs` |
| `last_frame` | Direct IMAGE input for fal.ai only; for AnyFast use `SeedanceAnyfastImageUpload(last_frame)` -> `anyfast_refs` |
| `reference_images` | `SEEDANCE_IMAGE_LIST` from `SeedanceRefImages`; ignored when `anyfast_refs` is connected |
| `anyfast_refs` | AnyFast-only structured image refs; overrides direct image inputs when connected |

## Example Workflows

| File | Provider | Description |
|---|---|---|
| `anyfast/01_t2v.json` | AnyFast | Text-to-video baseline |
| `anyfast/04_reference_images.json` | AnyFast | Reference images via AnyFast Image Upload |
| `anyfast/09_anyfast_save_to_input_for_vhs.json` | AnyFast | Save mp4 to `input` folder for VHS reload |
| `anyfast/10_anyfast_video_audio_refs.json` | AnyFast | Reference video + audio via Load Video / Load Audio |
| `fal/01_t2v.json` | fal.ai | Text-to-video baseline |
| `fal/05_image_to_video.json` | fal.ai | Image-to-video with direct `first_frame` connector |
| `fal/06_reference_images.json` | fal.ai | Reference images using `SeedanceRefImages` |
| `test/test_01_t2v.json` | AnyFast | Baseline text-to-video test |
| `test/test_02b_first_frame_base64.json` | AnyFast | First-frame image-to-video via base64/data URI |
| `test/test_03_base64_refs.json` | AnyFast | Reference-image test |
| `test/test_04_reference_video_audio.json` | AnyFast | Reference video + audio test |
| `test/test_05_multimodal_refs.json` | AnyFast | Multimodal image + video + audio test |

## AnyFast Notes

- Base URL: `https://www.anyfast.ai`
- Asset creation for uploaded assets waits for `Active` before continuing.
- `ListAssets` is first tried with `GroupIds`; if the backend requires `GroupType`, the node resolves it via `ListAssetGroups` and retries.
- Asset URIs are normalized to lowercase `asset://...`.
- The Seedance guide says assets are supported for `first_frame`, but in this repo the direct base64/data-URI path is the recommended image-to-video workflow because it has been more reliable than the asset-backed first-frame flow.
- Reference video and reference audio still use uploaded AnyFast assets.
- Images that appear to contain real people can be rejected by AnyFast/Seedance with privacy-sensitive content errors.
- Image validation for AnyFast asset upload follows documented constraints: size under 30 MB, dimensions 300-6000 px, aspect ratio 0.4-2.5.
- `seedance-2.0-ultra` with `2k` requires the AnyFast channel to support Ultra capacity.

## fal.ai Notes

- API keys: `https://fal.ai/dashboard`
- Provider selector must be `fal.ai` in the API Key node.
- fal.ai does not support `anyfast_refs`.
- fal.ai tops out at 720p.

## License

Apache 2.0
