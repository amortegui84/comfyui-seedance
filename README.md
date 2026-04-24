# ComfyUI-Seedance

ComfyUI nodes for [ByteDance Seedance 2.0](https://www.anyfast.ai) video generation via the [AnyFast API](https://www.anyfast.ai).

Supports **Text-to-Video** and **Image-to-Video** across three quality tiers — Standard, Fast, and Ultra — with audio generation, style references, and frame control, all from a single shared API key node.

---

## Nodes

| Node | Purpose |
|---|---|
| **Seedance — API Key** | Holds your AnyFast credentials. Wire to all other nodes. |
| **Seedance 2.0 — Standard** | Best quality/speed balance. Up to 1080p, 15s, with audio. |
| **Seedance 2.0 — Fast** | Same features as Standard, generates faster. |
| **Seedance 2.0 — Ultra** | Highest quality. Up to 2K resolution. |
| **Seedance — Image Batch (References)** | Collect 1–9 images as style references for generation nodes. |
| **Seedance — Upload Asset** | Upload a video or audio file to use as a reference. |
| **Seedance — Save Video** | Download the generated video and save it to the output folder. |

---

## How It Works

### Basic — Text or Image to Video

```
[Seedance — API Key]
  api_key = "sk-..."
        │
        │ api
        ▼
[Seedance 2.0 — Standard]
  prompt, resolution, ratio, duration ...
  first_frame (IMAGE, optional) ──────────── leave empty for Text→Video
  last_frame  (IMAGE, optional) ──────────── constrains the ending shot
        │
        ▼
  video_url ──► [Seedance — Save Video]
```

- Leave `first_frame` empty → **Text-to-Video**
- Connect `first_frame` → **Image-to-Video**
- Connect both `first_frame` and `last_frame` → video is guided from start to finish

### With Reference Images (style / character consistency)

```
[Load Image A] ──┐
[Load Image B] ──┤► [Seedance — Image Batch]  inputcount = 2
                 │         │
                 │         │ reference_images
                 │         ▼
                 └──► [Seedance 2.0 — Standard]
                            │
                            ▼
                        video_url
```

Use the **Image Batch** node to pass 1–9 reference images to any generation node. Increase `inputcount` to add more image slots. This is used to guide the style, character, or scene without fixing a specific first frame.

---

## Installation

Clone into your `ComfyUI/custom_nodes` folder and restart ComfyUI:

```bash
git clone https://github.com/amortegui84/comfyui-seedance ComfyUI/custom_nodes/comfyui-seedance
```

No extra Python packages needed beyond `requests` and `Pillow`, which ComfyUI already includes.

---

## Setup

1. Create a free account at [anyfast.ai](https://www.anyfast.ai)
2. Go to **Console → Token Management → + Create token**
3. Copy your API key (starts with `sk-`)
4. In ComfyUI, add a **Seedance — API Key** node and paste the key

---

## Node Reference

### Seedance — API Key

| Parameter | Default | Description |
|---|---|---|
| `api_key` | `""` | Your AnyFast API key (`sk-...`) |
| `base_url` | `https://www.anyfast.ai` | Only change if using a different API provider |

**Output:** `SEEDANCE_API` — wire this to every other Seedance node.

---

### Seedance 2.0 — Standard / Fast / Ultra

All three models share the same inputs. The only difference is speed, quality, and maximum resolution.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `api` | SEEDANCE_API | — | From the API Key node |
| `prompt` | string | `""` | Scene, motion, style, and subject description |
| `resolution` | enum | `1080p` | Short-side resolution. Ultra adds `2K`; Standard/Fast go down to `480p` |
| `ratio` | enum | `16:9` | Aspect ratio. Options: `16:9`, `9:16`, `4:3`, `3:4`, `1:1`, `21:9`, `adaptive` |
| `duration` | int | `5` | Video length in seconds (4–15) |
| `generate_audio` | bool | `true` | Generate ambient audio automatically |
| `watermark` | bool | `false` | Add a ByteDance watermark |
| `seed` | int | `-1` | Fixed seed for reproducibility; `-1` = random |
| `first_frame` | IMAGE | *(optional)* | Starting frame — activates Image-to-Video mode |
| `last_frame` | IMAGE | *(optional)* | Ending frame — guides how the video resolves |
| `reference_images` | SEEDANCE_IMAGE_LIST | *(optional)* | Style/character references — connect from Image Batch node |
| `reference_video` | STRING | *(optional)* | Asset:// ID from Upload Asset node |
| `reference_audio` | STRING | *(optional)* | Asset:// ID from Upload Asset node |

**Outputs:** `video_url` (STRING), `task_id` (STRING)

| Model | Speed | Max Resolution |
|---|---|---|
| Standard (`seedance`) | Normal | 1080p |
| Fast (`seedance-fast`) | Fast | 1080p |
| Ultra (`seedance-2.0-ultra`) | Slower | 2K |

---

### Seedance — Image Batch (References)

Collects multiple images into a single list to pass as style references.

| Parameter | Type | Description |
|---|---|---|
| `inputcount` | int (1–9) | Number of image slots — increase to add more inputs |
| `image_1` … `image_N` | IMAGE | Connect one image per slot |

**Output:** `reference_images` (SEEDANCE_IMAGE_LIST) — wire to any generation node.

> Increase `inputcount` and the node adds new image slots automatically. Use this even for a single reference image (set `inputcount` to 1).

---

### Seedance — Upload Asset

> **When do you need this?**
>
> The generation nodes accept images directly as inline data (base64), which covers most use cases — first frame, last frame, and reference images all work without this node.
>
> Use **Upload Asset** only when you need to reference a **video** or **audio** file as input to a generation:
> - `reference_video` — provide a video clip the model uses as a motion or style reference
> - `reference_audio` — provide an audio track the model synchronizes the video to
>
> Images uploaded as assets return an `Asset://` ID; you can also reference them that way if you prefer reusing already-uploaded files rather than sending base64 every run.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `api` | SEEDANCE_API | — | From the API Key node |
| `asset_type` | enum | `Image` | `Image`, `Video`, or `Audio` |
| `name` | string | `asset` | Label for the file in the asset library |
| `group_name` | string | `comfyui-assets` | Organizer name — assets are grouped automatically, no setup needed |
| `image` | IMAGE | *(optional)* | Connect an image node to upload an image |
| `file_path` | STRING | *(optional)* | Local path to a video or audio file |

**Output:** `asset_id` (STRING) — an `Asset://...` ID, wire to `reference_video` or `reference_audio` on a generation node.

---

### Seedance — Save Video

Downloads the generated video and saves it to the ComfyUI output folder.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `video_url` | STRING | — | Connect from any generation node's `video_url` output |
| `filename_prefix` | string | `seedance` | Saved as `{prefix}_{timestamp}.mp4` |

---

## API Format

```
POST  https://www.anyfast.ai/v1/video/generations       ← submit job
GET   https://www.anyfast.ai/v1/video/generations/{id}  ← poll status
```

Nodes poll every 5 seconds (up to 10 minutes). The returned `video_url` is valid for 24 hours.

---

## License

Apache 2.0 — © 2025 amortegui84
