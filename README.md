# ComfyUI-Seedance AM

Generate videos with ByteDance Seedance 2.0 inside ComfyUI.

This pack is focused on generation, references, and clean video output for:

- `anyfast`
- `fal.ai`

For real-human ID creation, the recommended path is the official ByteDance node flow inside ComfyUI, then this pack for generation.

## Recommended Node Set

Most users only need:

- `Seedance AM - API Key`
- `Seedance AM 2.0 - Standard`
- `Seedance AM - Save Video`
- `Seedance AM - Reference Images (9 slots)` when using style/reference images
- `Seedance AM - Identity Input` to keep `asset_id` and `group_id` organized

## Install

Most users should clone directly inside `ComfyUI/custom_nodes`:

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/amortegui84/comfyui-seedance
cd comfyui-seedance
pip install -r requirements.txt
```

That should leave the repo here:

```text
ComfyUI/custom_nodes/comfyui-seedance
```

If you are cloning from another location, use:

```bash
git clone https://github.com/amortegui84/comfyui-seedance ComfyUI/custom_nodes/comfyui-seedance
pip install -r ComfyUI/custom_nodes/comfyui-seedance/requirements.txt
```

Restart ComfyUI after installation.

`opencv-python` is only required for the `first_frame` output.

## Quick Start

```text
Seedance AM - API Key -> Seedance AM 2.0 - Standard -> Seedance AM - Save Video
```

1. Add `Seedance AM - API Key`
2. Paste your API key and choose `anyfast` or `fal.ai`
3. Add `Seedance AM 2.0 - Standard`
4. Add `Seedance AM - Save Video`
5. Connect `video_url -> Save Video`
6. Run

For text-to-video, leave image inputs disconnected. For image-to-video, connect a `Load Image` node to `first_frame`.

## Provider Behavior

- `anyfast` uses the `base_url` field, normally `https://www.anyfast.ai`
- local `reference_images` from ComfyUI are stable on `fal.ai`
- local `reference_images` on `anyfast` are still under investigation and should be treated as experimental
- `fal.ai` always uses `https://fal.run` internally
- `fal.ai` API keys come from `https://fal.ai/dashboard`
- if the `base_url` widget does not visibly refresh in the UI, runtime still normalizes it correctly for `fal.ai`

## Providers

| Feature | AnyFast | fal.ai |
|---|---|---|
| Text to video / image to video | Yes | Yes |
| Reference images from local ComfyUI IMAGE tensors | Experimental | Yes |
| Reference audio / video assets | Yes | Yes |
| 1080p / 2K | Yes | 720p max |
| Real human ID generation | Via official ByteDance node | No |
| Extend video | Yes | No |

## Nodes

| Node | What it does |
|---|---|
| `Seedance AM - API Key` | Main API key node for AnyFast and fal.ai |
| `Seedance AM 2.0 - Standard` | Main Seedance 2.0 generation node |
| `Seedance AM 2.0 - Fast` | Faster generation variant |
| `Seedance AM 2.0 - Ultra` | Highest quality variant, up to 2K |
| `Seedance AM - Extend Video` | Extend a previous generation using its `task_id` |
| `Seedance AM - Reference Images (9 slots)` | Collect up to 9 reference images |
| `Seedance AM - Identity Input` | Store `asset_id` and `group_id` together and output either or both |
| `Seedance AM - Reference Video` | Pick a local video from the input folder and upload it |
| `Seedance AM - Reference Audio` | Pick a local audio file from the input folder and upload it |
| `Seedance AM - Upload Asset` | Advanced generic uploader for image, audio, or video assets |
| `Seedance AM - Save Video` | Downloads the generated video, saves it locally, and previews the mp4 in-node |
| `Seedance AM - Show Text` | Generic string preview node for debugging |
| `Seedance AM - Text Input (Legacy)` | Older generic text holder kept for compatibility |

## Categories

- `Seedance AM/Core` - main generation flow
- `Seedance AM/Identity` - ID storage and routing
- `Seedance AM/References` - image, video, and audio references
- `Seedance AM/Advanced` - lower-level asset utilities
- `Seedance AM/Debug` - optional debug helpers
- `Seedance AM/Legacy` - old compatibility nodes not recommended for new workflows

## Which Node Should I Use?

- Generate a normal video: `API Key` -> `Seedance 2.0 - Standard`
- Save and preview the final mp4: use `Save Video`
- Add image references on `fal.ai`: use `Reference Images (9 slots)`
- Add image references on `anyfast`: currently experimental; use with caution
- Add reference video/audio: use `Reference Video` or `Reference Audio`
- Store or reuse `asset_id` and `group_id`: use `Identity Input`
- Debug a raw string: use `Show Text`
- Upload arbitrary asset files manually: use `Upload Asset`

## Real Human Flow

The recommended real-human flow is the hybrid official path:

1. Use ComfyUI's official `ByteDanceCreateImageAsset` node to create and verify the person ID
2. Feed the returned `asset_id` into `Seedance AM - Identity Input`
3. Connect `asset_id -> Seedance AM 2.0 - Standard.human_asset_id`
4. Finish with `Seedance AM - Save Video`

This is the workflow included in the repo:

- `seedance_hybrid_official_id_our_generation.json`

`group_id` is for identity reuse. `asset_id` is the value you connect to `human_asset_id` for generation.

Example:

```text
ByteDanceCreateImageAsset
  asset_id -> Seedance AM - Identity Input -> Seedance AM 2.0 - Standard.human_asset_id
```

## Example Workflows

- `seedance_hybrid_official_id_our_generation.json` - official ByteDance ID creation + Seedance AM generation
- `02_generate_with_existing_real_human_id.json` - generate with an existing verified `asset_id`
- `seedance_manual_asset_generation_workflow.json` - paste an `asset_id` manually and generate

## fal.ai Notes

- `fal.ai` works by selecting `provider = fal.ai` in `Seedance AM - API Key`
- `fal.ai` uses normal references such as `reference_images`, `reference_video`, and `reference_audio`
- `fal.ai` does not use `human_asset_id`, `asset_id`, or `group_id` as a real-human flow
- `end_user_id` in fal is not the same as `asset_id` or `group_id`

## AnyFast Notes

- `anyfast` works for Seedance generation and the official hybrid real-human flow
- `reference_video` and `reference_audio` asset flows are supported
- automatic local `reference_images` coming directly from ComfyUI `IMAGE` tensors are still experimental on `anyfast`
- current tests show `fal.ai` is the stable provider for local image-reference workflows

## Video Output

`Seedance2` returns a `video_url` string. The recommended final step is `Seedance AM - Save Video`.

1. Generate the video
2. Let `Seedance AM - Save Video` download the mp4
3. Preview it directly in the node UI

If you want to use ComfyUI's native `LoadVideo` node afterwards, set `save_to = input` in `Seedance AM - Save Video`.

## Key Parameters

| Parameter | Meaning |
|---|---|
| `prompt` | Main text prompt. Use `@image1` to `@image9`, `@video1`, and `@audio1` style references |
| `resolution` | `480p`, `720p`, `1080p`, and `2K` for Ultra |
| `ratio` | `16:9`, `9:16`, `4:3`, `3:4`, `1:1`, `21:9`, `adaptive` |
| `duration` | 4 to 15 seconds |
| `generate_audio` | Generate synced ambient audio when supported |
| `seed` | `-1` for random, any other value for reproducible results |
| `first_frame` | Enables image-to-video |
| `last_frame` | Guides how the video ends |
| `human_asset_id` | Verified real-human `asset_id` from the official ByteDance asset node |

## License

Apache 2.0
