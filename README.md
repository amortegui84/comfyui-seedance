# ComfyUI-Seedance AM

Generate AI videos with [ByteDance Seedance 2.0](https://seedance2.ai) directly inside ComfyUI. This `Seedance AM` pack supports text-to-video, image-to-video, reference images, reference audio/video uploads, real-human asset verification, and video saving.

Works with `AnyFast` and `fal.ai`. Pick your provider in the API Key node.

The `Seedance AM - API Key` node now auto-switches `base_url` to match the selected provider:

- `anyfast` -> `https://www.anyfast.ai`
- `fal.ai` -> `https://fal.run`

## Current Real-Human Flow

This repo does **not** use the same built-in ByteDance nodes shown in Comfy's official Real Human workflow templates.

- Official Comfy templates use core nodes like `ByteDance Create Image/Video Asset`
- This repo uses the custom node `Seedance AM - Create Human Asset`
- In this repo, the verification UI is shown inside `Seedance AM - Create Human Asset`
- `Seedance AM - Show Text` is only for previewing plain string outputs after the fact

If you load `api_seedance2_0_r2v_real_human.json` and expect identical behavior, it will not match this custom node pack 1:1.

## Recommended Node Set

Most users only need these nodes:

- `Seedance AM - API Key`
- `Seedance AM 2.0 - Standard`
- `Seedance AM - Save Video`
- `Seedance AM - Reference Images (9 slots)` when using style/reference images
- `Seedance AM - Create Human Asset` when using real-human identity verification
- `Seedance AM - Identity Input` to keep `asset_id` and `group_id` organized

Everything else is either advanced, specialized, or kept for backward compatibility.

## Install

```bash
git clone https://github.com/amortegui84/comfyui-seedance ComfyUI/custom_nodes/comfyui-seedance
pip install -r ComfyUI/custom_nodes/comfyui-seedance/requirements.txt
```

Restart ComfyUI.

`opencv-python` is only required for the `first_frame` output. The rest of the nodes work without it.

## Quick Start

1. Add `Seedance AM - API Key`
2. Paste your API key and choose `anyfast` or `fal.ai`
3. Add `Seedance AM 2.0 - Standard`
4. Connect `api` and run

For text-to-video, leave image inputs disconnected. To switch to image-to-video, connect a `Load Image` node to `first_frame`.

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
| `Seedance AM - API Key` | Configure provider, API key, and base URL |
| `Seedance AM 2.0 - Standard` | Main Seedance 2.0 generation node |
| `Seedance AM 2.0 - Fast` | Faster generation variant |
| `Seedance AM 2.0 - Ultra` | Highest quality variant, up to 2K |
| `Seedance AM - Extend Video` | Extend a previous generation using its `task_id` |
| `Seedance AM - Reference Images (9 slots)` | Collect up to 9 reference images |
| `Seedance AM - Create Human Asset` | First run starts H5 verification, later run creates the final `asset_id` using the verified `group_id` |
| `Seedance AM - Identity Input` | Store `asset_id` and `group_id` together and output either or both |
| `Seedance AM - Reference Video` | Pick a local video from the input folder and upload it |
| `Seedance AM - Reference Audio` | Pick a local audio file from the input folder and upload it |
| `Seedance AM - Upload Asset` | Advanced generic uploader for image, audio, or video assets |
| `Seedance AM - Save Video` | Download and save the generated video |
| `Seedance AM - Show Text` | Generic string preview node, useful for debugging |
| `Seedance AM - Text Input (Legacy)` | Older generic text holder kept for compatibility |

## Categories

The nodes are grouped in ComfyUI like this:

- `Seedance AM/Core` — main generation flow
- `Seedance AM/Identity` — real-human ID and ID storage
- `Seedance AM/References` — image, video, and audio references
- `Seedance AM/Advanced` — lower-level asset utilities
- `Seedance AM/Debug` — optional debug helpers
- `Seedance AM/Legacy` — old compatibility nodes not recommended for new workflows

## Which Node Should I Use?

Use this as the short decision guide:

- Generate a normal video:
  `API Key` -> `Seedance 2.0 - Standard` -> `Save Video`
- Add image references:
  use `Reference Images (9 slots)`
- Add reference video/audio:
  use `Reference Video` or `Reference Audio`
- Create a new real-human ID:
  use `Create Human Asset`
- Store or reuse `asset_id` and `group_id`:
  use `Identity Input`
- Debug a raw string:
  use `Show Text`
- Upload arbitrary asset files manually:
  use `Upload Asset`
- Build a new workflow from scratch:
  avoid `Text Input (Legacy)` and `Image Batch (Legacy)`

## Usage

### Text to Video

Connect:

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

ByteDance requires identity verification before generating videos with a real person's likeness. This is normally a one-time flow per person. After verification, reuse the saved `group_id`.

Rules:

- One person per image or verification asset
- Group IDs belong to the account that created them
- Cross-account reuse is not supported

### First-time verification

1. Connect a portrait to `Seedance AM - Create Human Asset`
2. Leave `existing_group_id` empty
3. Run the node
4. Click `Start Verification` inside the node
5. Complete the H5 liveness check in your browser or phone
6. The node fills `existing_group_id` automatically
7. Queue the node again to create the final `asset_id`

The verification controls now live directly inside `Seedance AM - Create Human Asset`, so no extra panel node is needed.

Important:

- The official Comfy workflow uses built-in `ByteDance Create Image/Video Asset` nodes
- This repo replaces that flow with `Seedance AM - Create Human Asset`
- `Seedance AM - Show Text` is only for displaying final string outputs like `asset_id`, `group_id`, or `video_url`
- The verification link itself is expected to appear inside `Seedance AM - Create Human Asset`, not in `Show Text`
- If the verification button or link does not appear, update ComfyUI and make sure you are running from `127.0.0.1` or `localhost` while logged into ComfyUI partner/API nodes

### Troubleshooting when nothing appears

If you run the node and do not see a button or verification link:

1. Restart ComfyUI so the custom JS in `web/js/human_asset.js` reloads
2. Open ComfyUI from `http://127.0.0.1:8188` or `http://localhost:8188`
3. Update ComfyUI to the latest nightly or newest desktop build
4. Make sure partner/API-node login is active in ComfyUI
5. Do not rely on `Seedance AM - Show Text` for the verification step
6. If ComfyUI is started with `--listen` and accessed over LAN/IP, the verification proxy may not work

The node now shows a visible status/error panel when the local verification proxy is unavailable.

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

### Keep IDs readable in the graph

- Use `Seedance AM - Create Human Asset` for the full first-time verification flow and final asset creation
- Use `Seedance AM - Identity Input` as the main place to store and route `asset_id` and `group_id`
- Use `Seedance AM - Show Text` only if you want a separate generic debug preview
- `Seedance AM - Text Input (Legacy)` is no longer needed for real-human ID workflows

### Recommended example workflows

- `01_create_real_human_id.json` — verify a new real person and save both IDs
- `02_generate_with_existing_real_human_id.json` — generate with a known `asset_id`
- `03_reuse_group_id_same_person.json` — upload a new photo of the same person using a saved `group_id`

### Where to put each ID

- Put `asset_id` into `Seedance AM 2.0 - Standard.human_asset_id`
- Put a saved `group_id` into `Seedance AM - Create Human Asset.existing_group_id`
- Use `Seedance AM - Identity Input` if you want to keep both values together and route each output where needed

Example:

```text
Seedance AM - Identity Input
  asset_id -> Seedance AM 2.0 - Standard.human_asset_id
  group_id -> Seedance AM - Create Human Asset.existing_group_id
```

`Seedance AM - Identity Input` already shows both values inside the node, so its old `summary` output is no longer needed.

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
