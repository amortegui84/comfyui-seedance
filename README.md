# ComfyUI-Seedance AM

Generate videos with ByteDance Seedance 2.0 inside ComfyUI.

Supports both `anyfast` and `fal.ai` providers with working local image, video, and audio reference flows.
Connect ComfyUI's built-in **Load Video** and **Load Audio** nodes directly to the reference nodes — no manual file picking required.

## Install

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/amortegui84/comfyui-seedance
cd comfyui-seedance
pip install -r requirements.txt
```

Restart ComfyUI after installation. `opencv-python` is only needed for the `first_frame` IMAGE output pin.

## Quick Start

```text
Seedance AM - API Key -> Seedance AM 2.0 - Standard -> Seedance AM - Save Video
```

1. Add **Seedance AM - API Key** and paste your key
2. Pick `anyfast` or `fal.ai`
3. Add **Seedance AM 2.0 - Standard**
4. Connect `video_url` to **Seedance AM - Save Video**
5. Run

For text-to-video leave all image inputs disconnected. For image-to-video on `fal.ai`, connect a `Load Image` node to `first_frame`. For image references on `anyfast`, use **Seedance AM - AnyFast Image Upload**.

## Provider Overview

| Feature | AnyFast | fal.ai |
|---|---|---|
| Text to video | Yes | Yes |
| Image to video (first frame) | Via AnyFast Image Upload node | Direct IMAGE connector |
| Reference images (local tensors) | Via AnyFast Image Upload node | Direct IMAGE connectors |
| Reference audio / video assets | Yes | Yes |
| 1080p / 2K | 1080p works; `2K / Ultra` depends on AnyFast channel availability | 720p max |
| Extend video | Yes | No |

## Nodes

| Node | Category | What it does |
|---|---|---|
| `Seedance AM - API Key` | Core | Configure provider (`anyfast` or `fal.ai`) and API key |
| `Seedance AM 2.0 - Standard` | Core | Main generation: T2V, I2V, references |
| `Seedance AM 2.0 - Fast` | Core | Faster generation variant |
| `Seedance AM 2.0 - Ultra` | Core | Highest quality option, but `2K / Ultra` availability depends on AnyFast channel access |
| `Seedance AM - AnyFast Image Upload (base64)` | AnyFast | Prepare image refs as base64 data URIs — no upload, no asset ID, instant |
| `Seedance AM - Asset Reference` | AnyFast | Wrap an `asset://` ID from Upload Asset into `ANYFAST_IMAGE_REFS`; chain multiple via `existing_refs` |
| `Seedance AM - Extend Video` | Core | Extend a previous generation using its `task_id` |
| `Seedance AM - Reference Images (9 slots)` | References | Collect up to 9 local images for fal.ai reference workflows |
| `Seedance AM - Reference Video` | References | Upload a video to AnyFast and get an `asset://` ID; accepts a **Load Video** node or the dropdown |
| `Seedance AM - Reference Audio` | References | Upload audio to AnyFast and get an `asset://` ID; accepts a **Load Audio** node or the dropdown |
| `Seedance AM - Upload Asset` | Advanced | Upload image, video, or audio to AnyFast asset storage; returns `asset_id` and `group_id` |
| `Seedance AM - Save Video` | Core | Download and preview the generated mp4 |
| `Seedance AM - Show Text` | Debug | Display any string value in-node |
| `Seedance AM - Text Input (Legacy)` | Legacy | Kept for backwards compatibility |
| `Seedance AM - Image Batch (Legacy)` | Legacy | Kept for backwards compatibility |

## AnyFast Image References

There are two ways to send images to AnyFast generation:

### Option A — Base64 (fast, no upload)

**Seedance AM - AnyFast Image Upload (base64)** converts images to data URIs on the fly. Nothing is uploaded to AnyFast storage; the image bytes are embedded directly in the request.

```text
SeedanceApiKey -> SeedanceAnyfastImageUpload -> anyfast_refs -> Seedance2 -> SeedanceSaveVideo
```

- `first_frame` on `Seedance2` should stay disconnected when using `anyfast_refs`
- Good for quick tests and style reference images

### Option B — Asset upload (persistent, reusable)

**Seedance AM - Upload Asset** uploads the image to AnyFast storage and returns a permanent `asset://` ID. **Seedance AM - Asset Reference** then wraps that ID into `ANYFAST_IMAGE_REFS` so the generation node can use it.

```text
LoadImage -> SeedanceUploadAsset -> asset_id -> SeedanceAssetRef(role=first_frame) -> anyfast_refs -> Seedance2
```

- The `group_id` output from `SeedanceUploadAsset` can be saved and passed back via `existing_group_id` to skip group re-creation on subsequent runs
- Chain multiple `SeedanceAssetRef` nodes via `existing_refs` to combine several assets
- Mix with base64 refs: connect `SeedanceAnyfastImageUpload` output to `existing_refs` on `SeedanceAssetRef`

## Reference Video and Audio (AnyFast)

Connect ComfyUI's built-in nodes directly — no manual file picker needed:

```text
Load Video -> SeedanceReferenceVideo -> reference_video -> Seedance2
Load Audio -> SeedanceReferenceAudio -> reference_audio -> Seedance2
```

Each node uploads the file to AnyFast asset storage and returns an `asset://` ID. If no Load node is connected, the dropdown inside the node falls back to files in the ComfyUI input directory.

Add `@video1` and `@audio1` in the prompt so the model knows how to use the references.

## fal.ai Image References

fal.ai accepts local ComfyUI IMAGE tensors directly. No upload step needed.

Image to video:

```text
LoadImage -> Seedance2.first_frame
```

Reference images:

```text
LoadImage -> SeedanceRefImages -> Seedance2.reference_images
```

Add `@image1`, `@image2`, etc. to the prompt so the model knows how to use each reference.

## Key Parameters

| Parameter | Meaning |
|---|---|
| `prompt` | Main text prompt. Use `@image1`...`@image9`, `@video1`, `@audio1` tags for references |
| `resolution` | `480p`, `720p`, `1080p` (Standard/Fast); `720p`, `1080p`, `2K` (Ultra, only when AnyFast has an available channel for that model) |
| `ratio` | `16:9`, `9:16`, `4:3`, `3:4`, `1:1`, `21:9`, `adaptive` |
| `duration` | 4-15 seconds |
| `generate_audio` | Generate synced ambient audio |
| `watermark` | Add ByteDance watermark (AnyFast only) |
| `seed` | `-1` for random; any value for reproducible results |
| `first_frame` | fal.ai direct I2V only when not using `anyfast_refs` |
| `last_frame` | fal.ai direct last-frame control only when not using `anyfast_refs` |
| `reference_images` | fal.ai only |
| `anyfast_refs` | Prepared image refs from **AnyFast Image Upload** |

## Example Workflows

| File | Provider | Description |
|---|---|---|
| `anyfast/01_t2v.json` | AnyFast | Simplest text-to-video |
| `anyfast/03_first_frame.json` | AnyFast | Image-to-video via AnyFast Image Upload (base64) |
| `anyfast/04_reference_images.json` | AnyFast | Reference images via AnyFast Image Upload (base64) |
| `anyfast/09_anyfast_save_to_input_for_vhs.json` | AnyFast | Save mp4 to `input` folder for VHS reload |
| `anyfast/10_anyfast_video_audio_refs.json` | AnyFast | **Reference video + audio via Load Video / Load Audio nodes** |
| `anyfast/11_anyfast_asset_first_frame.json` | AnyFast | **Upload image as AnyFast asset, use as first frame via Asset Reference** |
| `fal/01_t2v.json` | fal.ai | Simplest text-to-video |
| `fal/05_image_to_video.json` | fal.ai | Image-to-video with direct `first_frame` connector |
| `fal/06_reference_images.json` | fal.ai | Reference images using `SeedanceRefImages` |

## Video Output

`Seedance AM - Save Video` downloads the mp4 and previews it directly in the node.

Recommended loader for follow-up processing: `VHS_LoadVideoPath` from `ComfyUI-VideoHelperSuite`.

Recommended chain:

```text
Seedance2 -> SeedanceSaveVideo(save_to=input) -> saved_path -> VHS_LoadVideoPath
```

If you prefer built-in ComfyUI nodes, set `save_to = input` and then pick the file manually in `LoadVideo`.

## Reference Tags in Prompts

Seedance uses `@` tags in the prompt to tell the model how to use each reference:

- `@image1` ... `@image9` for style or content image references
- `@video1` for reference video
- `@audio1` for reference audio

Tags are auto-appended if missing, but writing them explicitly in the prompt usually gives better control.

## fal.ai Notes

- API keys come from `https://fal.ai/dashboard`
- Provider selector must be set to `fal.ai` in the API Key node
- fal.ai does not support `anyfast_refs`
- fal.ai tops out at `720p`

## AnyFast Notes

- API key and base URL come from `https://www.anyfast.ai`
- `anyfast_refs` is the supported path for local image references
- `reference_video` and `reference_audio` asset flows work directly
- `seedance-2.0-ultra` / `2K` may fail with `model_not_found` if your AnyFast token/group has no available channel for that model
- This is currently a provider-side availability issue; the plugin does not expose a documented request parameter to force `Auto Select`, `Aggregate`, `Direct`, or another channel from inside ComfyUI
- For reliable AnyFast usage today, prefer `Standard` or `Fast`

## License

Apache 2.0
