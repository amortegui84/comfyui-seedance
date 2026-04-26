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
| Real human ID generation | Via Seedance AM - Create Human Asset | No |
| Extend video | Yes | No |

## Nodes

| Node | Category | What it does |
|---|---|---|
| `Seedance AM - API Key` | Core | Configure provider (anyfast or fal.ai) and API key |
| `Seedance AM 2.0 - Standard` | Core | Main generation — T2V, I2V, reference, real-human |
| `Seedance AM 2.0 - Fast` | Core | Faster generation variant |
| `Seedance AM 2.0 - Ultra` | Core | Highest quality, up to 2K |
| `Seedance AM - AnyFast Image Upload` | AnyFast | Prepare AnyFast image refs inline from local IMAGE inputs; returns `ANYFAST_IMAGE_REFS` for generation |
| `Seedance AM - Extend Video` | Core | Extend a previous generation using its `task_id` |
| `Seedance AM - Reference Images (9 slots)` | References | Collect up to 9 local images for fal.ai reference workflows |
| `Seedance AM - Reference Video` | References | Pick a local video, upload it, get an Asset:// ID |
| `Seedance AM - Reference Audio` | References | Pick a local audio file, upload it, get an Asset:// ID |
| `Seedance AM - Upload Asset` | Advanced | Generic uploader for image, video, or audio assets |
| `Seedance AM - Create Human Asset` | Identity | Create or reuse an AnyFast real-human identity asset and return `asset_id`, `group_id`, `verify_url` |
| `Seedance AM - Identity Input` | Identity | Store and route `asset_id` and `group_id` together |
| `Seedance AM - Save Video` | Core | Download and preview the generated mp4 |
| `Seedance AM - Show Text` | Debug | Display any string value in-node |
| `Seedance AM - Text Input (Legacy)` | Legacy | Kept for backwards compatibility |
| `Seedance AM - Image Batch (Legacy)` | Legacy | Kept for backwards compatibility |

## AnyFast — Image References

For local image refs on AnyFast, this plugin prepares them inline from ComfyUI IMAGE tensors. The **Seedance AM - AnyFast Image Upload** node handles this.

**How it works:**
1. Connects to the same API key as your generation node
2. Converts each image to a data URI
3. Assigns the correct Seedance role (`first_frame`, `last_frame`, `reference_image`)
4. Returns `ANYFAST_IMAGE_REFS` — a pre-built content list ready for generation

**Workflow:**
```
SeedanceApiKey ─┬─→ SeedanceAnyfastImageUpload (first_frame / last_frame / ref_image_1..9)
                │         ↓ anyfast_refs
                └─→ Seedance2 ─→ SeedanceSaveVideo
```

**Notes:**
- `first_frame` input on Seedance2 should stay **disconnected** when using `anyfast_refs`
- This node is for local image guidance only; it does not create persistent AnyFast asset IDs
- Use **Seedance AM - Create Human Asset** when you need a reusable AnyFast human identity asset

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

Use the built-in AnyFast identity flow in this plugin. Do not mix it with identity assets created by other ComfyUI nodes or other providers.

1. Load the portrait image
2. Run **Seedance AM - Create Human Asset**
3. Complete `verify_url` if the node asks for liveness verification
4. Feed the returned `asset_id` and `group_id` into **Seedance AM - Identity Input**
5. Connect `asset_id -> Seedance AM 2.0 - Standard.human_asset_id`
6. Connect `group_id -> Seedance AM 2.0 - Standard.group_id`

AnyFast asset IDs are token-scoped. An `asset_id` created outside AnyFast asset management may return `asset not found`.

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
| `human_asset_id` | Verified AnyFast real-human `asset_id` from **Seedance AM - Create Human Asset** |
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
| `07_anyfast_human_id_with_ref_images.json` | AnyFast | **Human ID + reference images in the same generation** |
| `02_generate_with_existing_real_human_id.json` | AnyFast | Generate with a saved AnyFast `asset_id` and matching `group_id` |
| `08_anyfast_create_human_asset.json` | AnyFast | Full AnyFast-only real-human flow: create identity asset, verify if needed, then generate |
| `09_anyfast_save_to_input_for_vhs.json` | AnyFast | Save the generated mp4 into ComfyUI `input` so `VHS_LoadVideoPath` can load it by path |
| `seedance_manual_asset_generation_workflow.json` | AnyFast | Paste an `asset_id` manually and generate |

## Human ID + Reference Images (AnyFast)

You can combine a verified human identity asset with additional style/context reference images in the same generation.

**Workflow:** `07_anyfast_human_id_with_ref_images.json`

```
SeedanceApiKey ─┬─→ SeedanceAnyfastImageUpload (ref_image_1..9)
                │         ↓ anyfast_refs
                └─→ Seedance2 ─→ SeedanceSaveVideo
SeedanceIdentityInput → asset_id → human_asset_id → Seedance2
SeedanceIdentityInput → group_id → group_id → Seedance2
```

**How it works:**
- `human_asset_id` is always placed first in the payload (`@image1`)
- Reference images from `anyfast_refs` follow (`@image2`, `@image3`, …)
- Tags are auto-appended if missing from the prompt

**Prompt example:**
```
A cinematic video of the person from @image1 with the visual style of @image2, natural motion.
```

**Notes:**
- `first_frame` / `last_frame` / `reference_images` inputs on Seedance2 should stay **disconnected** when using `anyfast_refs`
- The `asset_id` from **Seedance AM - Create Human Asset** can be pasted directly into `SeedanceIdentityInput` — the `Asset://` prefix is added automatically if missing
- The matching `group_id` must also be passed into `Seedance2.group_id` for AnyFast real-human generation

## Video Output

`Seedance AM - Save Video` downloads the mp4 and previews it directly in the node.

Recommended loader for follow-up processing: `VHS_LoadVideoPath` from `ComfyUI-VideoHelperSuite`.

Why this one:
- `Seedance AM - Save Video` returns a full `saved_path`
- `VHS_LoadVideoPath` accepts an arbitrary file path directly
- You do not have to manually browse for the latest mp4 in `input`

Recommended chain:

```text
Seedance2 -> SeedanceSaveVideo(save_to=input) -> saved_path -> VHS_LoadVideoPath
```

If you prefer built-in ComfyUI nodes, set `save_to = input` and then pick the file manually in `LoadVideo`.

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
- The real-human flow should use **Seedance AM - Create Human Asset** so the asset is created inside AnyFast asset management

## License

Apache 2.0

