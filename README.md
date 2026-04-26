# ComfyUI-Seedance AM

Generate videos with ByteDance Seedance 2.0 inside ComfyUI.

Supports both `anyfast` and `fal.ai` providers with clean local image, video, and audio reference flows.

## Install

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/amortegui84/comfyui-seedance
cd comfyui-seedance
pip install -r requirements.txt
```

Restart ComfyUI after installation. `opencv-python` is only needed for the `first_frame` IMAGE output pin.

## Quick Start

```
Seedance AM - API Key → Seedance AM 2.0 - Standard → Seedance AM - Save Video
```

1. Add **Seedance AM - API Key** — paste your key, pick `anyfast` or `fal.ai`
2. Add **Seedance AM 2.0 - Standard**
3. Add **Seedance AM - Save Video**, connect `video_url`
4. Run

For text-to-video leave all image inputs disconnected. For image-to-video on fal.ai, connect a `Load Image` node to `first_frame`. For image-to-video on AnyFast, use the dedicated **Seedance AM - AnyFast Image Upload** node (see below).

## Provider Overview

| Feature | AnyFast | fal.ai |
|---|---|---|
| Text to video | Yes | Yes |
| Image to video (first frame) | Via AnyFast Image Upload node | Direct IMAGE connector |
| Reference images (local tensors) | Via AnyFast Image Upload node | Direct IMAGE connectors |
| Reference audio / video assets | Yes | Yes |
| 1080p / 2K | Yes | 720p max |
| Real human ID generation | Via official ByteDance node | No |
| Extend video | Yes | No |

## Nodes

| Node | Category | What it does |
|---|---|---|
| `Seedance AM - API Key` | Core | Configure provider (anyfast or fal.ai) and API key |
| `Seedance AM 2.0 - Standard` | Core | Main generation — T2V, I2V, reference, real-human |
| `Seedance AM 2.0 - Fast` | Core | Faster generation variant |
| `Seedance AM 2.0 - Ultra` | Core | Highest quality, up to 2K |
| `Seedance AM - AnyFast Image Upload` | AnyFast | Upload local images to AnyFast asset storage via multipart; returns Asset:// URIs ready for generation |
| `Seedance AM - Extend Video` | Core | Extend a previous generation using its `task_id` |
| `Seedance AM - Reference Images (9 slots)` | References | Collect up to 9 local images for fal.ai reference workflows |
| `Seedance AM - Reference Video` | References | Pick a local video, upload it, get an Asset:// ID |
| `Seedance AM - Reference Audio` | References | Pick a local audio file, upload it, get an Asset:// ID |
| `Seedance AM - Upload Asset` | Advanced | Generic uploader for image, video, or audio assets |
| `Seedance AM - Create Human Asset` | Identity | Upload a portrait for identity-verified real-human generation (AnyFast) |
| `Seedance AM - Identity Input` | Identity | Store and route `asset_id` and `group_id` together |
| `Seedance AM - Save Video` | Core | Download and preview the generated mp4 |
| `Seedance AM - Show Text` | Debug | Display any string value in-node |
| `Seedance AM - Text Input (Legacy)` | Legacy | Kept for backwards compatibility |
| `Seedance AM - Image Batch (Legacy)` | Legacy | Kept for backwards compatibility |

## AnyFast — Image References

AnyFast requires images to be uploaded to asset storage before generation. The **Seedance AM - AnyFast Image Upload** node handles this.

**How it works:**
1. Connects to the same API key as your generation node
2. Uploads each image via multipart form (the documented AnyFast method)
3. Creates a group to hold the assets and waits for propagation
4. Returns `ANYFAST_IMAGE_REFS` — a pre-built content list with `Asset://` URIs and correct roles

**Workflow:**
```
SeedanceApiKey ─┬─→ SeedanceAnyfastImageUpload (first_frame / last_frame / ref_image_1..9)
                │         ↓ anyfast_refs
                └─→ Seedance2 ─→ SeedanceSaveVideo
```

**Notes:**
- `first_frame` input on Seedance2 should stay **disconnected** when using `anyfast_refs`
- `propagation_wait` (default 5s) gives AnyFast time to commit the asset to storage before generation
- Increase to 10–15s if generation still returns "asset not found" errors
- The same group is reused within a session; pass `existing_group_id` to reuse across sessions

## fal.ai — Image References

fal.ai accepts local ComfyUI IMAGE tensors directly. No upload step needed.

**Image to video (first frame):**
```
LoadImage → Seedance2.first_frame
```

**Reference images (style/content guidance):**
```
LoadImage → SeedanceRefImages → Seedance2.reference_images
```

Add `@image1`, `@image2` etc. to the prompt so the model knows how to use each reference.

## Real Human Flow (AnyFast)

The recommended path uses the official ByteDance ComfyUI node for identity verification:

1. Use `ByteDanceCreateImageAsset` (official ComfyUI node) to create and verify the person ID
2. Feed the returned `asset_id` into **Seedance AM - Identity Input**
3. Connect `asset_id → Seedance AM 2.0 - Standard.human_asset_id`

For portrait upload without the official node, use **Seedance AM - Create Human Asset** which handles the verification link flow.

## Key Parameters

| Parameter | Meaning |
|---|---|
| `prompt` | Main text prompt. Use `@image1`…`@image9`, `@video1`, `@audio1` tags for references |
| `resolution` | `480p`, `720p`, `1080p` (Standard/Fast); `720p`, `1080p`, `2K` (Ultra) |
| `ratio` | `16:9`, `9:16`, `4:3`, `3:4`, `1:1`, `21:9`, `adaptive` |
| `duration` | 4–15 seconds |
| `generate_audio` | Generate synced ambient audio |
| `watermark` | Add ByteDance watermark (AnyFast only) |
| `seed` | `-1` for random; any value for reproducible results |
| `first_frame` | fal.ai only direct I2V (AnyFast uses `anyfast_refs`) |
| `last_frame` | fal.ai only direct last-frame control (AnyFast uses `anyfast_refs`) |
| `reference_images` | fal.ai only (AnyFast uses `anyfast_refs`) |
| `human_asset_id` | Verified real-human `asset_id` — AnyFast only |
| `anyfast_refs` | Pre-uploaded image refs from **AnyFast Image Upload** — AnyFast only |

## Example Workflows

| File | Provider | Description |
|---|---|---|
| `01_t2v_anyfast.json` | AnyFast | Simplest text-to-video |
| `01_t2v_fal.json` | fal.ai | Simplest text-to-video |
| `03_anyfast_first_frame.json` | AnyFast | Image-to-video using the dedicated AnyFast upload node |
| `04_anyfast_reference_images.json` | AnyFast | Reference images using the dedicated AnyFast upload node |
| `05_fal_image_to_video.json` | fal.ai | Image-to-video with direct first_frame connector |
| `06_fal_reference_images.json` | fal.ai | Reference images using SeedanceRefImages |
| `02_generate_with_existing_real_human_id.json` | AnyFast | Generate with a saved verified `asset_id` |
| `seedance_manual_asset_generation_workflow.json` | AnyFast | Paste an `asset_id` manually and generate |
| `seedance_hybrid_official_id_our_generation.json` | AnyFast | Official ByteDance ID creation + Seedance AM generation |

## Video Output

`Seedance AM - Save Video` downloads the mp4 and previews it directly in the node.

To use ComfyUI's native `LoadVideo` afterwards, set `save_to = input` instead of `output`.

## Reference Tags in Prompts

Seedance uses `@` tags in the prompt to tell the model how to use each reference:

- `@image1` … `@image9` — style or content image references
- `@video1` — reference video
- `@audio1` — reference audio

Tags are auto-appended if missing, but writing them explicitly in the prompt gives better results.

## fal.ai Notes

- API keys come from `https://fal.ai/dashboard`
- Provider selector must be set to `fal.ai` in the API Key node
- fal.ai does not support `human_asset_id`, asset groups, or `anyfast_refs`
- fal.ai tops out at `720p` (no 1080p or 2K)

## AnyFast Notes

- API key and base URL come from `https://www.anyfast.ai`
- `anyfast_refs` is the stable path for local image references
- `reference_video` and `reference_audio` asset flows work directly
- The real-human flow uses the official ByteDance verification node

## License

Apache 2.0
