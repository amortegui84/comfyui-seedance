# ComfyUI-Seedance AM

Generate AI videos with [ByteDance Seedance 2.0](https://seedance2.ai) directly inside ComfyUI.

This pack supports:

- text-to-video
- image-to-video
- reference images
- reference audio and video uploads
- real-human asset verification
- AnyFast and fal.ai providers

## Recommended Node Set

Most users only need these nodes:

- `Seedance AM - API Key`
- `Seedance AM 2.0 - Standard`
- `Seedance AM - Save Video`
- `Seedance AM - Reference Images (9 slots)` when using style/reference images
- `Seedance AM - Create Human Asset` when using real-human identity verification
- `Seedance AM - Identity Input` to keep `asset_id` and `group_id` organized

Everything else is advanced, debug, or compatibility.

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

`opencv-python` is only required for the `first_frame` output. The rest of the nodes work without it.

## Quick Start

1. Add `Seedance AM - API Key`
2. Paste your API key and choose `anyfast` or `fal.ai`
3. Add `Seedance AM 2.0 - Standard`
4. Connect `api` and run

For text-to-video, leave image inputs disconnected. For image-to-video, connect a `Load Image` node to `first_frame`.

## Provider Behavior

- `anyfast` uses the `base_url` field, normally `https://www.anyfast.ai`
- `fal.ai` always uses `https://fal.run` internally
- `fal.ai` API keys come from `https://fal.ai/dashboard`
- If the `base_url` widget does not visibly refresh in the UI, runtime still normalizes it correctly for `fal.ai`

## Providers

| Feature | AnyFast | fal.ai |
|---|---|---|
| Text to video / image to video | Yes | Yes |
| Reference images | Yes | Yes |
| Reference audio / video assets | Yes | Yes |
| 1080p / 2K | Yes | 720p max |
| Real human ID verification | Yes | No |
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
| `Seedance AM - Create Human Asset` | Start verification and create the final `asset_id` using a verified `group_id` |
| `Seedance AM - Identity Input` | Store `asset_id` and `group_id` together and output either or both |
| `Seedance AM - Reference Video` | Pick a local video from the input folder and upload it |
| `Seedance AM - Reference Audio` | Pick a local audio file from the input folder and upload it |
| `Seedance AM - Upload Asset` | Advanced generic uploader for image, audio, or video assets |
| `Seedance AM - Save Video` | Downloads the generated video, saves it locally, and should preview the mp4 in-node |
| `Seedance AM - Show Text` | Generic string preview node for debugging |
| `Seedance AM - Text Input (Legacy)` | Older generic text holder kept for compatibility |

## Categories

The nodes are grouped in ComfyUI like this:

- `Seedance AM/Core` - main generation flow
- `Seedance AM/Identity` - real-human ID and ID storage
- `Seedance AM/References` - image, video, and audio references
- `Seedance AM/Advanced` - lower-level asset utilities
- `Seedance AM/Debug` - optional debug helpers
- `Seedance AM/Legacy` - old compatibility nodes not recommended for new workflows

## Which Node Should I Use?

- Generate a normal video: `API Key` -> `Seedance 2.0 - Standard`
- Save and preview the final mp4: use `Save Video`
- Add image references: use `Reference Images (9 slots)`
- Add reference video/audio: use `Reference Video` or `Reference Audio`
- Create a new real-human ID: use `Create Human Asset`
- Store or reuse `asset_id` and `group_id`: use `Identity Input`
- Debug a raw string: use `Show Text`
- Upload arbitrary asset files manually: use `Upload Asset`
- Build a new workflow from scratch: avoid `Text Input (Legacy)` unless you specifically need compatibility

## Compatibility

- `Seedance AM - API Key V2 (Compatibility)` exists only so older saved workflows can still load
- For new workflows, ignore it and use `Seedance AM - API Key`

## Usage

### Text to Video

```text
Seedance AM - API Key -> Seedance AM 2.0 - Standard -> Seedance AM - Save Video
```

Write a prompt and queue it.

### Image to Video

Connect a `Load Image` node to `first_frame`. Optionally connect a second image to `last_frame` to guide the ending frame.

### Reference Images

Connect images to `Seedance AM - Reference Images (9 slots)`, then connect that output to a generation node. Reference them in the prompt as `@image1`, `@image2`, and so on.

### Reference Audio or Video

Use `Seedance AM - Reference Video` or `Seedance AM - Reference Audio` to upload files from ComfyUI's input folder, then connect the returned asset IDs to the generation node.

### Extend Video

Connect a generation node's `task_id` output to `Seedance AM - Extend Video`, add a continuation prompt, and run again.

## Real Human Video

This repo does not use the same built-in ByteDance nodes shown in Comfy's official Real Human workflow templates.

- Official Comfy templates use core nodes like `ByteDance Create Image/Video Asset`
- This repo uses the custom node `Seedance AM - Create Human Asset`
- In this repo, the verification UI is shown inside `Seedance AM - Create Human Asset`
- `Seedance AM - Show Text` is only for previewing plain string outputs after the fact

If you load `api_seedance2_0_r2v_real_human.json` and expect identical behavior, it will not match this custom pack 1:1.

### First-time verification

1. Connect a portrait to `Seedance AM - Create Human Asset`
2. Leave `existing_group_id` empty
3. Run the node
4. Click `Start Verification` inside the node
5. Complete the H5 liveness check in your browser or phone
6. The node fills `existing_group_id` automatically
7. Queue the node again to create the final `asset_id`

Important:

- one person per image or verification asset
- `group_id` belongs to the account that created it
- cross-account reuse is not supported
- the verification link is expected to appear inside `Seedance AM - Create Human Asset`, not in `Show Text`
- if the verification button or link does not appear, update ComfyUI and make sure you are running from `127.0.0.1` or `localhost` while logged into ComfyUI partner/API nodes

### Troubleshooting when nothing appears

1. Restart ComfyUI so the custom JS in `web/js/human_asset.js` reloads
2. Open ComfyUI from `http://127.0.0.1:8188` or `http://localhost:8188`
3. Update ComfyUI to the latest nightly or newest desktop build
4. Make sure partner/API-node login is active in ComfyUI
5. Do not rely on `Seedance AM - Show Text` for the verification step
6. If ComfyUI is started with `--listen` and accessed over LAN/IP, the verification proxy may not work

### Generate with a verified human

Connect the returned `asset_id` directly to `human_asset_id` on a Seedance generation node.

```text
Load Image
  -> Seedance AM - Create Human Asset
      asset_id -> Seedance AM 2.0 - Standard.human_asset_id
      group_id -> save for future uploads
```

If the prompt does not include `@image1`, the node adds it automatically when `human_asset_id` is present.

### Reuse the same person later

Paste the saved `group_id` into `existing_group_id`. The node skips new verification and returns a ready-to-use `asset_id`.

### Where to put each ID

- put `asset_id` into `Seedance AM 2.0 - Standard.human_asset_id`
- put a saved `group_id` into `Seedance AM - Create Human Asset.existing_group_id`
- use `Seedance AM - Identity Input` if you want to keep both values together and route each output where needed

Example:

```text
Seedance AM - Identity Input
  asset_id -> Seedance AM 2.0 - Standard.human_asset_id
  group_id -> Seedance AM - Create Human Asset.existing_group_id
```

## Example Workflows

- `01_create_real_human_id.json` - verify a new real person and save both IDs
- `02_generate_with_existing_real_human_id.json` - generate with a known `asset_id`
- `03_reuse_group_id_same_person.json` - upload a new photo of the same person using a saved `group_id`
- `seedance_hybrid_official_id_our_generation.json` - use official ByteDance ID creation with this pack for generation

## fal.ai Notes

- `fal.ai` works with this pack by selecting `provider = fal.ai` in `Seedance AM - API Key`
- `fal.ai` uses normal reference inputs such as `reference_images`, `reference_video`, and `reference_audio`
- `fal.ai` does not use `human_asset_id`, `asset_id`, or `group_id` as a real-human flow
- `end_user_id` in fal is not the same as `asset_id` or `group_id`

## Video Output Recommendation

`Seedance2` returns a `video_url` string. The recommended final step is `Seedance AM - Save Video`.

1. Generate the video
2. Let `Seedance AM - Save Video` download the mp4
3. Preview it directly in the node UI

If you want to use ComfyUI's native `LoadVideo` node afterwards, set `save_to = input` in `Seedance AM - Save Video` so the downloaded mp4 is written to the input folder.

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
| `human_asset_id` | Verified real-human asset ID from `Seedance AM - Create Human Asset` |

## License

Apache 2.0
