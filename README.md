# ComfyUI-Seedance

ComfyUI custom nodes for [ByteDance Seedance 2.0](https://seedance2.ai) — the state-of-the-art multimodal video generation model.

Supports **Text-to-Video**, **Image-to-Video**, and **Omni Reference** (images + video + audio) across three quality tiers with two API providers: **AnyFast** and **fal.ai**.

---

## What's New

- **Multi-provider support** — switch between AnyFast and fal.ai with a single dropdown
- **`first_frame` IMAGE output** — every generation node now outputs the first frame as an IMAGE tensor, enabling direct chaining between nodes
- **Extend Video** — continue a previously generated video using its `task_id`
- **Identity-Verified Human Video** — generate real human video with a verified person's likeness
- **Group ID reuse** — save your Asset Group ID to skip identity re-verification on future runs
- **Reference Video / Audio loader nodes** — pick files from your ComfyUI input folder in one click

---

## Nodes at a Glance

| Node | Category | Description |
|---|---|---|
| **Seedance — API Key** | Config | Holds credentials and selects the API provider |
| **Seedance 2.0 — Standard** | Generation | Quality/speed balance. Up to 1080p, 15 s, audio |
| **Seedance 2.0 — Fast** | Generation | Faster generation, same features as Standard |
| **Seedance 2.0 — Ultra** | Generation | Highest quality, up to 2K |
| **Seedance — Extend Video** | Generation | Continue an existing video using its task_id |
| **Seedance — Reference Images (9 slots)** | Utility | Send up to 9 reference images to a generation node |
| **Seedance — Image Batch (References)** | Utility | Legacy 2-image batch node (kept for compatibility) |
| **Seedance — Create Human Asset (ID Verified)** | Assets | Upload a portrait for identity-verified video generation |
| **Seedance — Upload Asset** | Assets | Upload any image, video, or audio to the asset library |
| **Seedance — Reference Video** | Assets | Pick a video file from the input folder and upload it |
| **Seedance — Reference Audio** | Assets | Pick an audio file from the input folder and upload it |
| **Seedance — Save Video** | Output | Download and save the generated video |

---

## Installation

```bash
git clone https://github.com/amortegui84/comfyui-seedance ComfyUI/custom_nodes/comfyui-seedance
cd ComfyUI/custom_nodes/comfyui-seedance
pip install -r requirements.txt
```

Restart ComfyUI after installation.

> **`opencv-python`** is required for the `first_frame` IMAGE output. If it is missing, the output will be a black placeholder image — all other functionality still works normally.

---

## Setup

### Option A — AnyFast (recommended for full features)

1. Create a free account at [anyfast.ai](https://www.anyfast.ai)
2. Go to **Console → Token Management → + Create token**
3. Copy your API key (starts with `sk-`)
4. In ComfyUI, add a **Seedance — API Key** node, paste the key, set `provider` = **anyfast**

### Option B — fal.ai

1. Create an account at [fal.ai](https://fal.ai) and get your API key
2. In ComfyUI, add a **Seedance — API Key** node, paste the key, set `provider` = **fal.ai**
3. The `base_url` field is ignored for fal.ai — the correct endpoints are set automatically

| Feature | AnyFast | fal.ai |
|---|---|---|
| Text-to-Video | ✅ | ✅ |
| Image-to-Video | ✅ | ✅ |
| Reference-to-Video (omni) | ✅ | ✅ |
| 1080p / 2K resolution | ✅ | ⚠️ 720p max on standard endpoints |
| Identity-verified human video | ✅ | ❌ Requires AnyFast asset system |
| Extend Video | ✅ | ❌ Not yet confirmed |
| Video / Audio asset upload | ✅ | ❌ Not needed — pass URLs directly |

---

## Workflows

### 1 — Text to Video

```
[Seedance — API Key]
      │ api
      ▼
[Seedance 2.0 — Standard]
  prompt    = "A timelapse of storm clouds over the ocean"
  resolution = 1080p | ratio = 16:9 | duration = 5
      │ video_url          │ first_frame (IMAGE)
      ▼                    ▼
[Save Video]         [next node or preview]
```

Leave `first_frame` disconnected → **Text-to-Video**.

---

### 2 — Image to Video

Connect any `IMAGE` to the `first_frame` input → **Image-to-Video**.  
Optionally also connect `last_frame` to guide how the clip resolves.

---

### 3 — Reference-to-Video (style / character consistency)

```
[Load Image A] ──┐
[Load Image B] ──┤► [Seedance — Reference Images (9 slots)]
[Load Image C] ──┘         │ reference_images
                            ▼
                  [Seedance 2.0 — Standard]
                    prompt = "A person smiling @image1, wearing outfit @image2"
```

Use `@image1`, `@image2` … `@image9` in your prompt to instruct the model how to apply each reference.  
You can mix reference images with `first_frame` / `last_frame` in the same generation.

---

### 4 — Video Extend (chain clips)

```
[Seedance 2.0 — Standard]
      │ task_id
      ▼
[Seedance — Extend Video]
  prompt   = "continue the scene into a sunrise"
  duration = 5
      │ video_url
      ▼
[Save Video]
```

Wire the `task_id` output of any generation node into **Extend Video** to seamlessly continue the clip.

> **Note:** Requires AnyFast to expose the `/v1/video/extend` endpoint. If you see a 404 error, the feature is not yet available on your plan.

---

### 5 — Omni Reference (images + video + audio)

```
[Load Image]             [Ref Video node]    [Ref Audio node]
      │ reference_images       │ ref_video        │ ref_audio
      └──────────────────────►[Seedance 2.0 — Standard]
                                prompt = "@image1 style, @video1 motion, @audio1 sync"
```

Use **Reference Video** and **Reference Audio** loader nodes to upload files from your ComfyUI input folder. Connect their `reference_video` / `reference_audio` outputs to the generation node, and reference them with `@video1` / `@audio1` in your prompt.

---

### 6 — Identity-Verified Human Video

> **Legal requirement:** ByteDance requires a one-time identity verification before generating videos with a real person's likeness. After the first verification, you save a **Group ID** and reuse it — no further liveness checks are needed for that person.
>
> - One Group ID per person.
> - A Group ID verified on one account **cannot** be used on another account.
> - Each image/video used to create an asset must contain **only one person**.

#### Step 1 — First-time verification

Run this workflow once with `existing_group_id` left **empty**:

```
[Load Image]  ← portrait photo (one person only)
      │ image
      ▼
[Seedance — Create Human Asset]
  name              = "my_portrait"
  group_name        = "comfyui-human-assets"
  existing_group_id = (leave empty)
      │                    │                    │
   asset_id             group_id           verify_url
      ▼                    ▼                    ▼
[Show Text]          [Show Text]          [Show Text]
 (copy later)       ★ SAVE THIS ★       open this link!
```

The `verify_url` output contains a Seedance verification link. **Connect it to a "Show Text" node**, then:

1. Click the URL shown in the "Show Text" node
2. Complete the **camera liveness check** on your phone or browser (under 30 seconds)
3. Copy the **Group ID** from its "Show Text" node and save it somewhere safe

> "Show Text" is available in many custom node packs (e.g. rgthree, ComfyUI-Custom-Scripts). Any node that displays a STRING value works.

#### Step 2 — Generate the video

After completing the liveness check, wire the `asset_id` to the generation node:

```
[Create Human Asset]
      │ asset_id
      ▼
[Seedance — Reference Images (9 slots)]
      │ reference_images
      ▼
[Seedance 2.0 — Standard]
  prompt = "A person giving a speech @image1"
      │ video_url
      ▼
[Save Video]
```

#### Step 3 — Subsequent runs (same person, no re-verification)

Paste the saved Group ID into `existing_group_id`. The `verify_url` output will be empty — the API uses facial comparison against the original verified identity automatically.

```
[Load Image]  ← new photo of the same person
      │ image
      ▼
[Seedance — Create Human Asset]
  existing_group_id = "grp_abc123"   ← paste your saved Group ID
      │ asset_id          │ group_id     │ verify_url (empty — no action needed)
      ▼
[Reference Images] → [Seedance 2.0 — Standard]
```

#### Multiple people in one video

Each person needs their own verified Group ID. Upload portraits separately, then connect both `asset_id` outputs to different image slots:

```
[Load Image A]                             [Load Image B]
      │                                          │
[Create Human Asset]                     [Create Human Asset]
  existing_group_id = "grp_aaa"            existing_group_id = "grp_bbb"
      │ asset_id                                 │ asset_id
      ▼                                          ▼
                   [Reference Images (9 slots)]
                    image_1 = Person A asset_id
                    image_2 = Person B asset_id
                         │ reference_images
                         ▼
              [Seedance 2.0 — Standard]
               prompt = "@image1 and @image2 meeting in a café"
```

---

## Node Reference

### Seedance — API Key

| Parameter | Default | Description |
|---|---|---|
| `api_key` | `""` | Your API key. AnyFast keys start with `sk-`; fal.ai keys are different format |
| `provider` | `anyfast` | `anyfast` or `fal.ai` |
| `base_url` | `https://www.anyfast.ai` | AnyFast only — ignored for fal.ai |

**Output:** `SEEDANCE_API` — wire to every other Seedance node.

---

### Seedance 2.0 — Standard / Fast / Ultra

All three share the same inputs. Differences are speed, model quality, and maximum resolution.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `api` | SEEDANCE_API | — | From the API Key node |
| `prompt` | string | `""` | Scene description. Use `@image1`…`@image9`, `@video1`…`@video3`, `@audio1`…`@audio3` to reference assets |
| `resolution` | enum | `1080p` | Output resolution. Ultra adds `2K`; Standard/Fast go down to `480p` |
| `ratio` | enum | `16:9` | `16:9`, `9:16`, `4:3`, `3:4`, `1:1`, `21:9`, `adaptive` |
| `duration` | int | `5` | Video length in seconds (4–15) |
| `generate_audio` | bool | `true` | Automatically generate synchronized ambient audio |
| `watermark` | bool | `false` | Add a ByteDance watermark |
| `seed` | int | `-1` | Reproducible seed; `-1` = random |
| `first_frame` | IMAGE | *(optional)* | Starting frame — activates Image-to-Video mode |
| `last_frame` | IMAGE | *(optional)* | Ending frame — guides how the video resolves |
| `reference_images` | SEEDANCE_IMAGE_LIST | *(optional)* | Style/character references from Reference Images node |
| `reference_video` | STRING | *(optional)* | `Asset://` ID from Reference Video node |
| `reference_audio` | STRING | *(optional)* | `Asset://` ID from Reference Audio node |

**Outputs:** `video_url` (STRING), `task_id` (STRING), `first_frame` (IMAGE)

| Model | Speed | Max Resolution |
|---|---|---|
| Standard (`seedance`) | Normal | 1080p |
| Fast (`seedance-fast`) | Fast | 1080p |
| Ultra (`seedance-2.0-ultra`) | Slower | 2K |

---

### Seedance — Extend Video

Continue a previously generated video.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `api` | SEEDANCE_API | — | From the API Key node |
| `task_id` | STRING | — | `task_id` output from any generation node |
| `prompt` | string | `""` | Optional continuation prompt |
| `duration` | int | `5` | Duration to append (4–15 s) |
| `resolution` | enum | `1080p` | Resolution for the extended segment |

**Outputs:** `video_url` (STRING), `task_id` (STRING), `first_frame` (IMAGE)

---

### Seedance — Reference Images (9 slots)

Collect up to 9 reference images for a generation node.

| Parameter | Type | Description |
|---|---|---|
| `image_1` | IMAGE | Required |
| `image_2` … `image_9` | IMAGE | Optional — connect as many as needed |

**Output:** `reference_images` (SEEDANCE_IMAGE_LIST)

---

### Seedance — Create Human Asset (ID Verified)

Upload a portrait for identity-verified real human video generation.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `api` | SEEDANCE_API | — | AnyFast only |
| `image` | IMAGE | — | Portrait photo of the person |
| `name` | string | `portrait` | Label for this asset |
| `group_name` | string | `comfyui-human-assets` | Asset group name |
| `existing_group_id` | STRING | `""` | Paste a previously saved Group ID to skip re-verification |

**Outputs:** `asset_id` (STRING), `group_id` (STRING), `verify_url` (STRING)

| Output | What to do with it |
|---|---|
| `asset_id` | Wire to **Reference Images (9 slots)** → then to a generation node |
| `group_id` | Connect to a **Show Text** node and **save the value** for future runs |
| `verify_url` | Connect to a **Show Text** node — click the link and complete the liveness check (first run only; empty on reuse) |

---

### Seedance — Upload Asset

Upload any image, video, or audio to the AnyFast asset library.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `api` | SEEDANCE_API | — | AnyFast only |
| `asset_type` | enum | `Image` | `Image`, `Video`, or `Audio` |
| `name` | string | `asset` | Label in the asset library |
| `group_name` | string | `comfyui-assets` | Asset group (created automatically) |
| `image` | IMAGE | *(optional)* | Connect an image node |
| `file_path` | STRING | *(optional)* | Local path to a video or audio file |
| `existing_group_id` | STRING | *(optional)* | Reuse an existing group instead of creating a new one |

**Outputs:** `asset_id` (STRING), `group_id` (STRING)

---

### Seedance — Reference Video / Reference Audio

Pick a file from your ComfyUI `input/` folder, upload it, and get an `Asset://` ID.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `api` | SEEDANCE_API | — | AnyFast only |
| `video_file` / `audio_file` | dropdown | — | Files found in ComfyUI `input/` |
| `name` | string | `ref_video` / `ref_audio` | Label |
| `group_name` | string | `comfyui-assets` | Asset group |
| `existing_group_id` | STRING | *(optional)* | Reuse an existing group |

**Outputs:** `reference_video` / `reference_audio` (STRING), `group_id` (STRING)

Use the **Choose Video / Choose Audio** button in the ComfyUI toolbar to copy files into the `input/` folder.

---

### Seedance — Save Video

Download and save the generated video to the ComfyUI `output/` folder.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `video_url` | STRING | — | From any generation node's `video_url` output |
| `filename_prefix` | string | `seedance` | Saved as `{prefix}_{timestamp}.mp4` |

---

## API Details

### AnyFast
```
POST  https://www.anyfast.ai/v1/video/generations       ← submit job
GET   https://www.anyfast.ai/v1/video/generations/{id}  ← poll status
POST  https://www.anyfast.ai/v1/video/extend            ← extend video
POST  https://www.anyfast.ai/volc/asset/CreateAssetGroup
POST  https://www.anyfast.ai/volc/asset/CreateAsset
```

### fal.ai
```
POST  https://queue.fal.run/bytedance/seedance-2.0/text-to-video
POST  https://queue.fal.run/bytedance/seedance-2.0/image-to-video
POST  https://queue.fal.run/bytedance/seedance-2.0/reference-to-video
POST  https://queue.fal.run/bytedance/seedance-2.0/fast/text-to-video
POST  https://queue.fal.run/bytedance/seedance-2.0/fast/image-to-video
POST  https://queue.fal.run/bytedance/seedance-2.0/fast/reference-to-video
GET   https://queue.fal.run/fal-ai/queue/requests/{id}/status  ← poll
GET   https://queue.fal.run/fal-ai/queue/requests/{id}         ← result
```

Nodes poll every 5 seconds (up to 10 minutes). Generated video URLs are valid for 24 hours.

---

## License

Apache 2.0 — © 2025 amortegui84
