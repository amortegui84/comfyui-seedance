# ComfyUI-Seedance

ComfyUI nodes for [ByteDance Seedance](https://www.anyfast.ai) video generation — Text-to-Video and Image-to-Video — via the [AnyFast API](https://www.anyfast.ai).

Supports Seedance 1.0 Pro and Pro Fast models with a shared API key node that connects to all generation nodes.

---

## Nodes

| Node | Model | Resolution | Input |
|---|---|---|---|
| **Seedance — API Key** | — | — | API credentials |
| **Seedance — Text→Video (Pro)** | `doubao-seedance-1-0-pro-250528` | 480 / 720 / **1080p** | Text prompt |
| **Seedance — Text→Video (Fast)** | `doubao-seedance-1-0-pro-fast-251015` | 480 / **720p** | Text prompt |
| **Seedance — Image→Video (Pro)** | `doubao-seedance-1-0-pro-250528` | 480 / 720 / **1080p** | First frame + optional last frame |
| **Seedance — Image→Video (Fast)** | `doubao-seedance-1-0-pro-fast-251015` | 480 / **720p** | First frame + optional last frame |

All generation nodes output `video_url` (direct download link, valid 24h) and `task_id`.

---

## How It Works

```
[Seedance — API Key]
  api_key = "sk-..."
  base_url = "https://www.anyfast.ai"
        │
        │ SEEDANCE_API
        ▼
[Seedance — Text→Video (Pro)]     or     [Seedance — Image→Video (Pro)]
  prompt, resolution, ratio ...           first_frame (IMAGE), last_frame (IMAGE, optional) ...
        │                                         │
        ▼                                         ▼
  video_url (STRING)                        video_url (STRING)
```

The API key node is wired once and shared across all generation nodes in the workflow.

---

## Installation

Clone into `ComfyUI/custom_nodes` and restart ComfyUI:

```bash
git clone https://github.com/amortegui84/comfyui-seedance ComfyUI/custom_nodes/comfyui-seedance
```

No additional Python packages required beyond `requests` and `Pillow`, which ComfyUI already provides.

---

## Setup

1. Create a free account at [anyfast.ai](https://www.anyfast.ai)
2. Go to **Console → Token Management → + Create token**
3. Copy your API key (starts with `sk-`)
4. In ComfyUI, add a **Seedance — API Key** node and paste the key

---

## Node Reference

### Seedance — API Key

Holds credentials and base URL. Connect its `api` output to any generation node.

| Parameter | Default | Description |
|---|---|---|
| `api_key` | `""` | Your AnyFast API key (`sk-...`) |
| `base_url` | `https://www.anyfast.ai` | API base URL — change only if using a different provider |

**Output:** `SEEDANCE_API` — wire to any generation node.

---

### Seedance — Text→Video (Pro / Fast)

Generates a video from a text prompt only. Pro supports up to 1080p; Fast is limited to 720p.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `api` | SEEDANCE_API | — | From the API Key node |
| `prompt` | string | `""` | Scene, subject, action, and style description |
| `resolution` | enum | `1080p` / `720p` | Short-side resolution of the output video |
| `ratio` | enum | `16:9` | Aspect ratio — `16:9` or `9:16` |
| `duration` | int | `5` | Video length in seconds (2–12) |
| `seed` | int | `-1` | Fixed seed for reproducibility; `-1` = random |
| `watermark` | bool | `false` | Add a ByteDance watermark to the output |
| `camera_fixed` | bool | `false` | Lock camera position throughout the clip |

**Outputs:** `video_url` (STRING), `task_id` (STRING)

---

### Seedance — Image→Video (Pro / Fast)

Animates from a first frame image. An optional last frame constrains the ending. Pro supports up to 1080p; Fast is limited to 720p.

The aspect ratio is detected automatically from the input image (`adaptive`).

| Parameter | Type | Default | Description |
|---|---|---|---|
| `api` | SEEDANCE_API | — | From the API Key node |
| `first_frame` | IMAGE | — | Starting frame of the video |
| `last_frame` | IMAGE | *(optional)* | Ending frame — constrains how the video resolves |
| `prompt` | string | `""` | Motion, action, or style guidance |
| `resolution` | enum | `1080p` / `720p` | Short-side resolution |
| `duration` | int | `5` | Video length in seconds (2–12) |
| `seed` | int | `-1` | Fixed seed; `-1` = random |
| `watermark` | bool | `false` | ByteDance watermark |
| `camera_fixed` | bool | `false` | Lock camera position |

**Outputs:** `video_url` (STRING), `task_id` (STRING)

---

## Model IDs

| Model | ID | Max Resolution |
|---|---|---|
| Seedance 1.0 Pro | `doubao-seedance-1-0-pro-250528` | 1080p |
| Seedance 1.0 Pro Fast | `doubao-seedance-1-0-pro-fast-251015` | 720p |

---

## API Format

This node pack uses the AnyFast video generation API:

```
POST  https://www.anyfast.ai/v1/video/generations       ← submit job
GET   https://www.anyfast.ai/v1/video/generations/{id}  ← poll status
```

The nodes poll automatically every 5 seconds until the job completes (up to 10 minutes). Once complete, the `video_url` is valid for 24 hours.

---

## License

Apache 2.0 — © 2025 amortegui84
