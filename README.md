# ComfyUI-Seedance AM

Generate videos with ByteDance Seedance 2.0 inside ComfyUI.

Supports both `anyfast` and `fal.ai` providers with working local image, video, and audio reference flows.

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
| 1080p / 2K | Yes | 720p max |
| Extend video | Yes | No |

## Nodes

| Node | Category | What it does |
|---|---|---|
| `Seedance AM - API Key` | Core | Configure provider (`anyfast` or `fal.ai`) and API key |
| `Seedance AM 2.0 - Standard` | Core | Main generation: T2V, I2V, references |
| `Seedance AM 2.0 - Fast` | Core | Faster generation variant |
| `Seedance AM 2.0 - Ultra` | Core | Highest quality, up to 2K |
| `Seedance AM - AnyFast Image Upload` | AnyFast | Prepare AnyFast image refs inline from local IMAGE inputs; returns `ANYFAST_IMAGE_REFS` |
| `Seedance AM - Extend Video` | Core | Extend a previous generation using its `task_id` |
| `Seedance AM - Reference Images (9 slots)` | References | Collect up to 9 local images for fal.ai reference workflows |
| `Seedance AM - Reference Video` | References | Pick a local video, upload it, get an `Asset://` ID |
| `Seedance AM - Reference Audio` | References | Pick a local audio file, upload it, get an `Asset://` ID |
| `Seedance AM - Upload Asset` | Advanced | Generic uploader for image, video, or audio assets |
| `Seedance AM - Save Video` | Core | Download and preview the generated mp4 |
| `Seedance AM - Show Text` | Debug | Display any string value in-node |
| `Seedance AM - Text Input (Legacy)` | Legacy | Kept for backwards compatibility |
| `Seedance AM - Image Batch (Legacy)` | Legacy | Kept for backwards compatibility |

## AnyFast Image References

For local image refs on AnyFast, this plugin prepares them inline from ComfyUI IMAGE tensors. The **Seedance AM - AnyFast Image Upload** node handles this.

How it works:
1. Connects to the same API key as your generation node
2. Converts each image to a data URI
3. Assigns the correct Seedance role: `first_frame`, `last_frame`, `reference_image`
4. Returns `ANYFAST_IMAGE_REFS` ready for generation

Workflow:

```text
SeedanceApiKey -> SeedanceAnyfastImageUpload -> anyfast_refs -> Seedance2 -> SeedanceSaveVideo
```

Notes:
- `first_frame` on `Seedance2` should stay disconnected when using `anyfast_refs`
- This node is for local image guidance only; it does not create persistent AnyFast asset IDs

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
| `resolution` | `480p`, `720p`, `1080p` (Standard/Fast); `720p`, `1080p`, `2K` (Ultra) |
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
| `01_t2v_anyfast.json` | AnyFast | Simplest text-to-video |
| `01_t2v_fal.json` | fal.ai | Simplest text-to-video |
| `03_anyfast_first_frame.json` | AnyFast | Image-to-video using the dedicated AnyFast image ref node |
| `04_anyfast_reference_images.json` | AnyFast | Reference images using the dedicated AnyFast image ref node |
| `05_fal_image_to_video.json` | fal.ai | Image-to-video with direct `first_frame` connector |
| `06_fal_reference_images.json` | fal.ai | Reference images using `SeedanceRefImages` |
| `09_anyfast_save_to_input_for_vhs.json` | AnyFast | Save the generated mp4 into ComfyUI `input` so `VHS_LoadVideoPath` can load it by path |

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

## License

Apache 2.0
