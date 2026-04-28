# ComfyUI-Seedance AM

Generate videos with ByteDance Seedance 2.0 inside ComfyUI.

Supports both `anyfast` and `fal.ai` providers with text-to-video, image-to-video, and multimodal reference workflows (image + video + audio).
Connect ComfyUI's built-in **Load Video** and **Load Audio** nodes directly to the reference nodes — no manual file picking required.

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
Seedance AM - API Key → Seedance AM 2.0 - Standard → Seedance AM - Save Video
```

1. Add **Seedance AM - API Key**, paste your key, pick `anyfast` or `fal.ai`
2. Add **Seedance AM 2.0 - Standard**, write a prompt
3. Connect `video_url` → **Seedance AM - Save Video**
4. Run — no image inputs needed for text-to-video

## Provider Overview

| Feature | AnyFast | fal.ai |
|---|---|---|
| Text to video | ✓ | ✓ |
| Image-to-video (first frame) | Via asset upload → `anyfast_refs` | Direct `first_frame` IMAGE connector |
| Reference images | `SeedanceRefImages` → `reference_images` or `anyfast_refs` | `SeedanceRefImages` → `reference_images` |
| Reference video + audio | ✓ via asset upload | ✓ |
| Resolutions | 480p / 720p / 1080p (Standard/Fast); 720p / 1080p / 2k (Ultra) | 720p max |
| Extend video | ✓ | — |

## Nodes

| Node | Category | What it does |
|---|---|---|
| `Seedance AM - API Key` | Core | Configure provider (`anyfast` or `fal.ai`) and API key |
| `Seedance AM 2.0 - Standard` | Core | Main generation: T2V, I2V, multimodal references — model `seedance` |
| `Seedance AM 2.0 - Fast` | Core | Faster generation variant — model `seedance-fast` |
| `Seedance AM 2.0 - Ultra` | Core | Highest quality — model `seedance-2.0-ultra`, supports 2k resolution |
| `Seedance AM - AnyFast Image Upload (base64)` | AnyFast | Encode images as base64 data URIs for first_frame / last_frame / reference_image roles |
| `Seedance AM - Asset Reference` | AnyFast | Wrap an `asset://` ID into `ANYFAST_IMAGE_REFS`; chain multiple via `existing_refs` |
| `Seedance AM - Upload Asset` | Advanced | Upload image/video/audio to AnyFast storage; waits for `Active` status; returns `asset_id` + `group_id` |
| `Seedance AM - Reference Video` | References | Upload a video file to AnyFast and return an `asset://` ID; accepts Load Video node or dropdown |
| `Seedance AM - Reference Audio` | References | Upload audio to AnyFast and return an `asset://` ID; accepts Load Audio node or dropdown |
| `Seedance AM - Reference Images (9 slots)` | References | Collect up to 9 images as `SEEDANCE_IMAGE_LIST` for the `reference_images` port |
| `Seedance AM - Extend Video` | Core | Extend a previous generation by wiring its `task_id` |
| `Seedance AM - Save Video` | Core | Download and preview the generated mp4 |
| `Seedance AM - Show Text` | Debug | Display any string value (asset_id, group_id, video_url…) inside the node |
| `Seedance AM - Text Input (Legacy)` | Legacy | Kept for backwards compatibility |
| `Seedance AM - Image Batch (Legacy)` | Legacy | Kept for backwards compatibility |

## AnyFast — Image References

### Option A — Direct (SeedanceRefImages, base64)

Simplest path. Images are encoded as base64 data URIs and embedded directly in the generation request. No upload, no asset ID.

```text
SeedanceApiKey → api
LoadImage×N → SeedanceRefImages → reference_images → Seedance2 → video_url → SeedanceSaveVideo
```

- Connect up to 9 `Load Image` nodes to `image_1` … `image_9`
- Leave `anyfast_refs` **disconnected** — if it is connected, `reference_images` is ignored
- `@image1` … `@imageN` tags are **auto-appended** to the prompt; no manual step needed

### Option B — Asset upload (first_frame / last_frame, persistent IDs)

Use this when you need a specific image as the first or last frame, or when you want a reusable asset stored on AnyFast.

```text
SeedanceApiKey → api
LoadImage → SeedanceUploadAsset → asset_id → SeedanceAssetRef(role=first_frame) → anyfast_refs → Seedance2
```

- `SeedanceUploadAsset` creates the asset group, uploads the image, and **polls until the asset reaches `Active` status** before returning — no manual waiting needed
- Save the `group_id` output with `SeedanceShowText` and feed it back via `existing_group_id` on subsequent runs to skip group re-creation
- Chain multiple `SeedanceAssetRef` nodes via `existing_refs` to combine several assets in one generation
- Mix asset refs and base64 refs: connect `SeedanceAnyfastImageUpload` output → `existing_refs` on `SeedanceAssetRef`

## AnyFast — Reference Video and Audio

```text
Load Video → SeedanceReferenceVideo(api) → reference_video → Seedance2
Load Audio → SeedanceReferenceAudio(api)  → reference_audio → Seedance2
```

Each node uploads the file, waits for `Active` status, and returns an `asset://` ID. If no Load node is connected the dropdown inside the node falls back to files in the ComfyUI input directory.

`@video1` and `@audio1` tags are **auto-appended** to the prompt if missing.

## fal.ai — Image References

fal.ai accepts ComfyUI IMAGE tensors directly — no upload step needed.

Image-to-video (first frame):

```text
LoadImage → Seedance2.first_frame
```

Reference images:

```text
LoadImage×N → SeedanceRefImages → Seedance2.reference_images
```

`@image1` … `@imageN` tags are auto-appended to the prompt.

## Key Parameters

| Parameter | Values / Notes |
|---|---|
| `prompt` | Text description. `@image1`–`@image9`, `@video1`, `@audio1` tags are auto-added for each reference connected |
| `resolution` | `480p` / `720p` / `1080p` (Standard/Fast) · `720p` / `1080p` / `2k` (Ultra) |
| `ratio` | `16:9` · `9:16` · `4:3` · `3:4` · `1:1` · `21:9` · `adaptive` |
| `duration` | 4–15 seconds |
| `generate_audio` | Auto-generate synced voice, sound effects, and music |
| `watermark` | Add ByteDance watermark (AnyFast only) |
| `seed` | `-1` for random; any integer for reproducible results |
| `first_frame` | Direct IMAGE input — fal.ai only; for AnyFast use `anyfast_refs` via `SeedanceAssetRef` |
| `last_frame` | Direct IMAGE input — fal.ai only; for AnyFast use `anyfast_refs` via `SeedanceAssetRef` |
| `reference_images` | `SEEDANCE_IMAGE_LIST` from `SeedanceRefImages`; works for both providers; ignored when `anyfast_refs` is connected |
| `anyfast_refs` | `ANYFAST_IMAGE_REFS` — AnyFast only; overrides `first_frame`, `last_frame`, `reference_images` when connected |

## Reference Tags in Prompts

Seedance uses `@` tags to tell the model how to use each reference:

| Tag | Reference type |
|---|---|
| `@image1` … `@image9` | Image references (reference_image role) |
| `@video1` | Reference video |
| `@audio1` | Reference audio |

Tags are auto-appended to the prompt if missing. Writing them explicitly in the prompt gives you control over placement and phrasing.

**Note:** `first_frame` and `last_frame` roles do **not** use `@image` tags — they control start/end frames of the video directly.

## Example Workflows

| File | Provider | Description |
|---|---|---|
| `anyfast/01_t2v.json` | AnyFast | Text-to-video (simplest) |
| `anyfast/03_first_frame.json` | AnyFast | Legacy/experimental first-frame via base64 refs; prefer asset upload |
| `anyfast/04_reference_images.json` | AnyFast | Reference images via AnyFast Image Upload (base64) |
| `anyfast/09_anyfast_save_to_input_for_vhs.json` | AnyFast | Save mp4 to `input` folder for VHS reload |
| `anyfast/10_anyfast_video_audio_refs.json` | AnyFast | Reference video + audio via Load Video / Load Audio |
| `anyfast/11_anyfast_asset_first_frame.json` | AnyFast | Recommended first-frame workflow: upload image as asset, wait for `Active`, then generate |
| `fal/01_t2v.json` | fal.ai | Text-to-video (simplest) |
| `fal/05_image_to_video.json` | fal.ai | Image-to-video with direct `first_frame` connector |
| `fal/06_reference_images.json` | fal.ai | Reference images using `SeedanceRefImages` |

## Video Output

`Seedance AM - Save Video` downloads the mp4 and previews it directly in the node.

Recommended chain for follow-up processing with [ComfyUI-VideoHelperSuite](https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite):

```text
Seedance2 → SeedanceSaveVideo(save_to=input) → saved_path → VHS_LoadVideoPath
```

## AnyFast Notes

- API key and base URL: `https://www.anyfast.ai`
- Asset creation (Upload Asset, Reference Video, Reference Audio) automatically waits for `Active` status before returning — the generation request is only sent once the asset is ready
- AnyFast support confirmed that assets are supported for `first_frame`; this is the recommended workflow for image-to-video on AnyFast
- If generation submit times out after 600s, the node now fails with a clear message and does not auto-resubmit, to avoid duplicate generations if AnyFast already accepted the job
- `group_id` from `SeedanceUploadAsset` can be reused across runs via `existing_group_id` to avoid creating a new group each time
- Asset URIs are normalized to lowercase `asset://...`
- `ListAssets` is tried first with `GroupIds`; if your AnyFast backend requires `GroupType`, the node resolves it via `ListAssetGroups` and retries automatically
- `seedance-2.0-ultra` with `2k` resolution requires your AnyFast channel to have Ultra capacity allocated; if not available you will get a `model_not_found` style error — use Standard or Fast as fallback

## fal.ai Notes

- API keys: `https://fal.ai/dashboard`
- Provider selector must be `fal.ai` in the API Key node
- fal.ai does not support `anyfast_refs`
- fal.ai tops out at 720p

## License

Apache 2.0
