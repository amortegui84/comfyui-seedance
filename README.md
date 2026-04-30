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
3. Leave `base_url` as `https://www.anyfast.ai` unless AnyFast gives you a different endpoint.

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

### 2. Image to Video (no face)

For images that **do not contain a real human face**.

**Example:** `examples/02_image_to_video.json`

```
LoadImage → SeedanceAnyfastImageUpload(first_frame) → anyfast_refs → Seedance2 → SaveVideo
```

- Connect the image to the `first_frame` slot of **AnyFast Image Upload**.
- Do not add `@image1` to the prompt — `first_frame` uses I2V mode, not reference tags.
- Do not mix `first_frame` with `reference_images`, `reference_video`, or `reference_audio` in the same request.

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
- **Save the `group_id`** output — paste it into `existing_group_id` on the next run to skip re-upload.
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

### 5. Reference Audio

Make the video match a soundtrack — motion and energy follow the audio.

**Example:** `examples/04_reference_audio.json`

```
Load Audio  → SeedanceReferenceAudio ──────────────────────────────→ reference_audio ─┐
LoadImage   → SeedanceAnyfastImageUpload(ref_image_1) → anyfast_refs ─→ Seedance2 → SaveVideo
                                                                                      ↑
                                                                              reference_audio ─┘
```

> **Important:** AnyFast requires at least one image reference alongside `reference_audio`.
> Connecting audio alone returns a 400 error. Always pair it with an image via
> `SeedanceAnyfastImageUpload` (for non-face images) or `SeedanceFaceRef` (for real people).

- `@audio1` and `@image1` are auto-appended to the prompt if not present.
- Turn off `generate_audio` in the generation node when using a reference audio track.
- Files ≤ 10 MB are sent as base64; larger files are uploaded to a temporary host.

---

### 6. Reference Video (style transfer)

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
| `Seedance AM - Extend Video` | Continue a previous generation by wiring its `task_id`. Returns the extended clip. |
| `Seedance AM - Save Video` | Download and save the generated mp4 to the ComfyUI output folder. Shows a preview in the UI. |

### AnyFast Image Preparation

| Node | What it does |
|---|---|
| `Seedance AM - AnyFast Image Upload (base64, no faces)` | Encode images as base64 data URIs. Use for non-face images only. Supports `first_frame`, `last_frame`, and up to 9 `ref_image` slots. |
| `Seedance AM - Face / Person Reference (asset)` | Upload real-person images through the AnyFast asset system to bypass face moderation. Caches asset IDs locally. Outputs `anyfast_refs`, `group_id`, and `asset_ids`. |
| `Seedance AM - Asset Reference` | Wrap a raw `asset://` ID string into an `ANYFAST_IMAGE_REFS` entry. Useful for manual asset management. |

### References

| Node | What it does |
|---|---|
| `Seedance AM - Reference Images (9 slots)` | Collect up to 9 images as a `SEEDANCE_IMAGE_LIST` for the `reference_images` input on generation nodes. |
| `Seedance AM - Reference Video` | Upload a video file (or connect Load Video) and return a public URL. No API key required. |
| `Seedance AM - Reference Audio` | Upload an audio file (or connect Load Audio) and return a data URI or public URL. No API key required. |

### Advanced / Debug

| Node | What it does |
|---|---|
| `Seedance AM - Upload Asset` | Manually upload a single image to AnyFast Asset Management. For bulk face uploads use `SeedanceFaceRef` instead. |
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

| Combination | Allowed? |
|---|---|
| `ref_image_N` + `reference_audio` | ✅ Yes |
| `ref_image_N` + `reference_video` | ✅ Yes |
| `ref_image_N` + `reference_audio` + `reference_video` | ✅ Yes |
| `reference_video` alone | ✅ Yes |
| `reference_audio` alone | ❌ No — AnyFast requires at least one image reference alongside audio |
| `first_frame` alone | ✅ Yes (pure I2V) |
| `first_frame` + `reference_audio` | ❌ No — frame control cannot mix with multimodal refs |
| `first_frame` + `ref_image_N` | ❌ No |
| `last_frame` alone or with `first_frame` | ✅ Yes |

---

## Example Workflows

| File | Mode | Description |
|---|---|---|
| `examples/01_text_to_video.json` | T2V | Minimal baseline — prompt only |
| `examples/02_image_to_video.json` | I2V | Animate a non-face image |
| `examples/03_face_reference.json` | R2V | Face/person as style reference (`@image1` in prompt) |
| `examples/03b_face_first_frame.json` | I2V | Face/person image as the literal first frame |
| `examples/04_reference_audio.json` | T2V + audio | Video generation driven by a reference audio track |
| `examples/05_reference_video.json` | T2V + video | Video generation with a reference video for style/motion |

To use: in ComfyUI, go to **Load** → select the JSON file.

---

## Troubleshooting

**"real-person face detected" or PrivacyInformation error**
Use `SeedanceFaceRef` instead of `SeedanceAnyfastImageUpload`. The face node routes images through the asset system which bypasses this check.

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

---

## License

Apache 2.0
