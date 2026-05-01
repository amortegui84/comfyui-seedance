# ComfyUI AnyFast Seedance

Generate videos with **ByteDance Seedance 2.0** inside ComfyUI, powered by [AnyFast](https://www.anyfast.ai).

Supports text-to-video, image-to-video, face/person references (with automatic moderation bypass), reference images, reference video, and reference audio — all wired directly to ComfyUI's built-in nodes.

---

## Install

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/amortegui84/comfyui-anyfast-seedance
cd comfyui-anyfast-seedance
pip install -r requirements.txt
```

Restart ComfyUI. `opencv-python` is optional — only needed for the `first_frame` IMAGE output pin on generation nodes.

---

## API Key

1. Sign up at [anyfast.ai](https://www.anyfast.ai) and copy your API key.
2. In ComfyUI, add a **Seedance AM - API Key** node and paste the key in the `api_key` field.
3. The `base_url` defaults to `https://www.anyfast.ai` — leave it unless AnyFast gives you a custom endpoint.

The API Key node output (`api`) must be connected to every generation node you use.

---

## Model Variants

| Node | Model ID | Resolutions | Best for |
|---|---|---|---|
| `Seedance AM 2.0 - Standard` | `seedance` | 480p / 720p / 1080p | General use |
| `Seedance AM 2.0 - Fast` | `seedance-fast` | 480p / 720p / 1080p | Quick iterations |
| `Seedance AM 2.0 - Ultra` | `seedance-2.0-ultra` | 720p / 1080p / 2k | Highest quality |

All three nodes share the same inputs and work identically — only the underlying model differs.

---

## Quick Start: Text to Video

```
Seedance AM - API Key  →  Seedance AM 2.0 - Standard  →  Seedance AM - Save Video
```

1. Add **Seedance AM - API Key** and paste your key.
2. Add **Seedance AM 2.0 - Standard**, write a prompt.
3. Connect `video_url` → **Seedance AM - Save Video**.
4. Queue. The node submits the job and polls until the video is ready.

---

## Workflows

### 1. Text to Video

No image needed. Just a prompt.

**Example:** `examples/01_text_to_video.json`

```
API Key → Seedance2 → SaveVideo
```

---

### 2. Image to Video

Connect any image directly to the `first_frame` input on the generation node. No intermediate node required.

**Example:** `examples/02_image_to_video.json`

```
LoadImage → Seedance2(first_frame) → SaveVideo
```

- Do not add `@image1` to the prompt — `first_frame` uses I2V mode, not reference tags.
- Connect a second image to `last_frame` to control both start and end frames.
- Do not mix `first_frame` with `reference_images`, `reference_video`, or `reference_audio`.

---

### 3. Face / Person Reference (style reference)

For images with **real human faces**. AnyFast routes them through the asset system to satisfy Volcano Engine's face-moderation policy.

**Example:** `examples/03_face_reference.json`

```
LoadImage → SeedanceFaceRef(ref_image_1) → anyfast_refs → Seedance2 → SaveVideo
                         ↓
                    ShowText (group_id)
                    ShowText (asset_ids)
```

- Connect the face image to `ref_image_1` (or any `ref_image_N` slot).
- Use `@image1` in the prompt to tell the model where to apply the identity/style.
- **`group_id` and `asset_ids` are shown directly on the node** after upload — copy the `group_id` and paste it into `existing_group_id` on the next run to skip re-upload.
- Assets are also cached locally by image hash: repeated runs with the same image are instant.
- Up to 9 reference images supported (`ref_image_1` … `ref_image_9`).
- Can be combined with `reference_audio` and `reference_video`.

#### First run vs. repeat runs

| Situation | What to do |
|---|---|
| First run | Leave `existing_group_id` empty. The node creates a new group and uploads. |
| Repeat run, same images | Paste the saved `group_id` into `existing_group_id`. Upload is skipped via local cache. |
| Same `group_id`, different image | Connect the new image; the node uploads it into the same group. |
| Force re-upload | Enable `force_reupload` to bypass the local cache. |

#### Liveness verification (first upload only)

On first use, AnyFast may print a verification link in the ComfyUI console:

```
[Seedance Assets] *** IDENTITY VERIFICATION REQUIRED ***
[Seedance Assets] Open this link on your phone or browser (< 30 s): https://...
```

Open the link and complete the check within 30 seconds. This is a one-time step per asset group.

---

### 4. Face / Person as First Frame (I2V)

Start the video **from** a face image. The video animates out from that exact frame.

**Example:** `examples/03b_face_first_frame.json`

```
LoadImage → SeedanceFaceRef(first_frame) → anyfast_refs → Seedance2 → SaveVideo
```

- Connect to the `first_frame` slot, not `ref_image_N`.
- No `@image` tags in the prompt.
- Cannot be combined with reference images, audio, or video in the same request.

---

### 5. Extend a Video

Continue a previously generated clip by wiring its `task_id` into `SeedanceExtend`.

**Example:** `examples/08_extend_video.json`

```
API Key → Seedance2 → SeedanceSaveVideo (original)
               ↓ task_id
          SeedanceExtend → SeedanceSaveVideo (extended)
```

- Wire `task_id` from any generation node (Standard, Fast, or Ultra) to `SeedanceExtend`.
- Pick the **same model** used for the original generation in the `model` dropdown (`seedance`, `seedance-fast`, or `seedance-2.0-ultra`).
- Match the **same resolution** — Ultra supports `2k`; Standard and Fast go up to `1080p`.
- Leave `prompt` blank to continue the clip naturally, or add text to steer the extension.
- Disable `generate_audio` if the original clip had no generated audio.
- The extended clip can itself be extended by chaining `task_id` outputs.
- If AnyFast returns 404/405, the `/v1/video/extend` endpoint is not available on your plan yet.

---

### 6. Reference Audio

Make the video match a soundtrack — motion and energy follow the audio.

**Example:** `examples/04_reference_audio.json`

```
Load Audio  → SeedanceReferenceAudio → reference_audio ──────────────────→ Seedance2 → SaveVideo
LoadImage   → SeedanceRefImages(image_1) → reference_images ──────────────→ ↑
```

> **Important:** AnyFast requires at least one image reference alongside `reference_audio`.
> Connecting audio alone returns a 400 error. Always pair it with an image via
> `SeedanceRefImages` (for non-face images) or `SeedanceFaceRef` (for real people).

- `@audio1` and `@image1` are auto-appended to the prompt if not present.
- Turn off `generate_audio` in the generation node when using a reference audio track.
- Files ≤ 10 MB are sent as base64; larger files are uploaded to a temporary host.

---

### 7. Reference Video (style transfer)

Replicate the motion style or cinematic look of an existing video.

**Example:** `examples/05_reference_video.json`

```
Load Video → SeedanceReferenceVideo → reference_video → Seedance2 → SaveVideo
```

Or pick a file from the `video_file` dropdown.

- `@video1` is auto-appended to the prompt if not already present.
- The video is uploaded to a temporary public host (catbox.moe) and the URL is passed to AnyFast.

---

## All Nodes

### Core

| Node | What it does |
|---|---|
| `Seedance AM - API Key` | Stores your AnyFast API key and base URL. Connect its output to every generation node. |
| `Seedance AM 2.0 - Standard` | Main generation node (`seedance` model). |
| `Seedance AM 2.0 - Fast` | Same as Standard but faster (`seedance-fast` model). |
| `Seedance AM 2.0 - Ultra` | Highest quality (`seedance-2.0-ultra` model, supports 2k). |
| `Seedance AM - Extend Video` | Continue a previous generation by wiring its `task_id`. Pick the same model used for the original. Returns the extended clip. |
| `Seedance AM - Save Video` | Download and save the generated mp4 to the ComfyUI output folder. Shows a preview in the UI. |

### References

| Node | What it does |
|---|---|
| `Seedance AM - Reference Images (9 slots)` | Collect up to 9 images as a `SEEDANCE_IMAGE_LIST` for the `reference_images` input on generation nodes. |
| `Seedance AM - Reference Video` | Upload a video file (or connect Load Video) and return a public URL. No API key required. |
| `Seedance AM - Reference Audio` | Upload an audio file (or connect Load Audio) and return a data URI or public URL. No API key required. |

### Face / Asset (real people)

| Node | What it does |
|---|---|
| `Seedance AM - Face / Person Reference (asset)` | Upload real-person images through the AnyFast asset system to bypass face moderation. Caches asset IDs locally. Outputs `anyfast_refs`, `group_id`, and `asset_ids`. |
| `Seedance AM - Asset Reference` | Wrap a raw `asset://` ID string into an `ANYFAST_IMAGE_REFS` entry. Useful for manual asset management. |
| `Seedance AM - Upload Asset` | Manually upload a single image to AnyFast Asset Management. For bulk face uploads use `SeedanceFaceRef` instead. |

### Utilities

| Node | What it does |
|---|---|
| `Seedance AM - Show Text` | Display any string value (asset_id, group_id, video_url…) directly inside the node body for easy copy-paste. |

---

## Generation Parameters

| Parameter | Values | Notes |
|---|---|---|
| `prompt` | text | `@image1`…`@image9`, `@video1`, `@audio1` are auto-appended when needed |
| `resolution` | `480p` / `720p` / `1080p` (Standard/Fast); `720p` / `1080p` / `2k` (Ultra) | |
| `ratio` | `16:9` `9:16` `4:3` `3:4` `1:1` `21:9` `adaptive` | |
| `duration` | 4 – 15 seconds | |
| `generate_audio` | true / false | Auto-generates synced voice, sound effects, and music |
| `watermark` | true / false | ByteDance watermark |
| `seed` | -1 or integer | `-1` = random; any positive integer = reproducible |

---

## Mixing References

There are two **mutually exclusive** modes. You must pick one:

| Mode | Inputs used | What it does |
|---|---|---|
| **I2V** (Image-to-Video) | `first_frame` and/or `last_frame` | Video starts and/or ends on an exact frame |
| **R2V** (Reference-to-Video) | `reference_images`, `reference_video`, `reference_audio` | Style, motion, and rhythm transfer |

You cannot combine I2V and R2V inputs in the same request.

### Valid combinations

| Combination | Mode | Example |
|---|---|---|
| prompt only | T2V | `01_text_to_video.json` |
| `first_frame` | I2V | `02_image_to_video.json` |
| `first_frame` + `last_frame` | I2V | — |
| `reference_images` | R2V | `03_face_reference.json` |
| `reference_video` | R2V | `05_reference_video.json` |
| `reference_audio` + `reference_images` | R2V | `04_reference_audio.json` |
| `reference_video` + `reference_images` | R2V | `06_video_image_ref.json` |
| `reference_video` + `reference_audio` + `reference_images` | R2V | `07_video_audio_image_ref.json` |

### Invalid combinations

| Combination | Why |
|---|---|
| `reference_audio` alone | AnyFast requires at least one image or video ref alongside audio |
| `first_frame` + `reference_images` | Cannot mix I2V frame control with R2V references |
| `first_frame` + `reference_video` | Cannot mix I2V frame control with R2V references |
| `first_frame` + `reference_audio` | Cannot mix I2V frame control with R2V references |

---

## Example Workflows

| File | Mode | Description |
|---|---|---|
| `examples/01_text_to_video.json` | T2V | Minimal baseline — prompt only |
| `examples/02_image_to_video.json` | I2V | Animate an image from its first frame |
| `examples/03_face_reference.json` | R2V | Face/person as style reference (`@image1` in prompt) |
| `examples/03b_face_first_frame.json` | I2V | Face/person image as the literal first frame |
| `examples/04_reference_audio.json` | R2V | Audio + image reference — motion driven by soundtrack |
| `examples/05_reference_video.json` | R2V | Video reference for style/motion transfer |
| `examples/06_video_image_ref.json` | R2V | Video reference + image reference combined |
| `examples/07_video_audio_image_ref.json` | R2V | Full multimodal — video + audio + image references |
| `examples/08_extend_video.json` | Extend | Continue a generated clip using its task_id |
| `examples/09_first_last_frame.json` | I2V | Control both start and end frame of the video |
| `examples/10_face_audio_ref.json` | R2V | Face identity reference + audio rhythm (dancing, lip-sync) |

To use: in ComfyUI, go to **Load** → select the JSON file.

---

## Troubleshooting

**"real-person face detected" or PrivacyInformation error**
Use `SeedanceFaceRef` instead of connecting the image directly to `reference_images`. The face node routes images through the asset system which bypasses this check.

**Asset not found / asset not visible**
The node waits for `Active` status automatically. If it times out, AnyFast may be under load — retry in a few minutes. You can also paste the saved `group_id` into `existing_group_id` and re-run.

**Liveness verification link in console**
Open the printed URL on your phone within 30 seconds. This only happens on first upload per group.

**"API key is empty"**
Make sure the API Key node's `api_key` field is filled and connected to the generation node.

**`first_frame` IMAGE output is blank / black**
Install `opencv-python` (`pip install opencv-python`). Without it the first frame extraction falls back to a 64×64 black image.

**Generation times out after 1200 s**
Seedance Ultra at 2k can take longer than other variants. The timeout is 20 minutes — if you hit it regularly, check AnyFast's status page.

**"reference_audio cannot be the only reference input"**
AnyFast requires at least one image or video reference when using audio. Connect an image via `SeedanceRefImages` or `SeedanceFaceRef` alongside the audio.

---

## License

Apache 2.0
