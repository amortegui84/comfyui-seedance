# ComfyUI-Seedance

Generate AI videos with [ByteDance Seedance 2.0](https://seedance2.ai) directly inside ComfyUI. This node pack supports text-to-video, image-to-video, reference images, reference audio/video uploads, real-human asset verification, and video saving.

Works with `AnyFast` and `fal.ai`. Pick your provider in the API Key node.

## Install

```bash
git clone https://github.com/amortegui84/comfyui-seedance ComfyUI/custom_nodes/comfyui-seedance
pip install -r ComfyUI/custom_nodes/comfyui-seedance/requirements.txt
```

Restart ComfyUI.

`opencv-python` is only required for the `first_frame` output. The rest of the nodes work without it.

## Quick Start

1. Add `Seedance - API Key`
2. Paste your API key and choose `anyfast` or `fal.ai`
3. Add `Seedance 2.0 - Standard`
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
| `Seedance - API Key` | Configure provider, API key, and base URL |
| `Seedance 2.0 - Standard` | Main Seedance 2.0 generation node |
| `Seedance 2.0 - Fast` | Faster generation variant |
| `Seedance 2.0 - Ultra` | Highest quality variant, up to 2K |
| `Seedance - Extend Video` | Extend a previous generation using its `task_id` |
| `Seedance - Reference Images (9 slots)` | Collect up to 9 reference images |
| `Seedance - Create Human Asset (ID Verified)` | Upload a real-human portrait and get `asset_id`, `group_id`, and `verify_url` |
| `Seedance - Human Asset Panel` | Show `asset_id`, `group_id`, and `verify_url` together in one centered panel and pass them through |
| `Seedance - Upload Asset` | Upload a generic image, audio, or video asset |
| `Seedance - Reference Video` | Pick a local video from the input folder and upload it |
| `Seedance - Reference Audio` | Pick a local audio file from the input folder and upload it |
| `Seedance - Save Video` | Download and save the generated video |
| `Seedance - Show Text` | Display any string value directly in the node |

## Usage

### Text to Video

Connect:

```text
Seedance - API Key -> Seedance 2.0 - Standard -> Seedance - Save Video
```

Write a prompt and queue it.

### Image to Video

Connect a `Load Image` node to `first_frame`. Optionally connect a second image to `last_frame` to guide the ending frame.

### Reference Images

Connect images to `Seedance - Reference Images (9 slots)`, then connect that output to a generation node. Reference them in the prompt as `@image1`, `@image2`, and so on.

### Reference Audio or Video

Use `Seedance - Reference Video` or `Seedance - Reference Audio` to upload files from ComfyUI's input folder, then connect the returned asset IDs to the generation node.

### Extend Video

Connect a generation node's `task_id` output to `Seedance - Extend Video`, add a continuation prompt, and run again.

## Real Human Video

ByteDance requires identity verification before generating videos with a real person's likeness. This is normally a one-time flow per person. After verification, reuse the saved `group_id`.

Rules:

- One person per image or verification asset
- Group IDs belong to the account that created them
- Cross-account reuse is not supported

### First-time verification

1. Connect a portrait to `Seedance - Create Human Asset (ID Verified)`
2. Leave `existing_group_id` empty
3. Run the node
4. Open the returned verification link and complete the liveness check
5. Save the returned `group_id`

If you want the verification link and IDs in one place, connect the outputs to `Seedance - Human Asset Panel`.

### Generate with a verified human

Connect the returned `asset_id` directly to `human_asset_id` on a Seedance generation node.

```text
Load Image
  -> Seedance - Create Human Asset (ID Verified)
      asset_id -> Seedance 2.0 - Standard.human_asset_id
      group_id -> save for future uploads
```

If the prompt does not include `@image1`, the node adds it automatically when `human_asset_id` is present.

### Reuse the same person later

Paste the saved `group_id` into `existing_group_id`. The node skips new verification and returns a ready-to-use `asset_id`.

### Keep IDs readable in the graph

- Use `Seedance - Human Asset Panel` when you want `asset_id`, `group_id`, and `verify_url` centralized in one dedicated node
- Use `Seedance - Show Text` for simple one-value previews anywhere else in the graph

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
| `human_asset_id` | Verified real-human asset ID from `Seedance - Create Human Asset (ID Verified)` |

## License

Apache 2.0
