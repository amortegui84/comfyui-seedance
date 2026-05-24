# ComfyUI AnyFast Seedance

Generate videos with **ByteDance Seedance 2.0** inside ComfyUI, powered by [AnyFast](https://www.anyfast.ai).

Supports text-to-video, image-to-video, face/person references (with automatic moderation bypass), reference images, reference video, and reference audio.

---

## Install

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/amortegui84/comfyui-seedance
cd comfyui-seedance
pip install -r requirements.txt
```

Restart ComfyUI. `opencv-python` is optional — only needed for the `first_frame` IMAGE output pin on generation nodes.

---

## API Key & Plans

1. Sign up at [anyfast.ai](https://www.anyfast.ai) and copy your API key.
2. In ComfyUI, add a **Seedance AM - API Key** node and paste the key in the `api_key` field.
3. The `base_url` defaults to `https://www.anyfast.ai` — leave it unless AnyFast gives you a custom endpoint.

Connect the API Key node output (`api`) to every generation node you use.

### AnyFast plan requirements

| Feature | Plan needed |
|---|---|
| Text-to-video, Image-to-video | Any plan |
| `reference_audio`, `reference_video` | **Direct** plan or higher |
| `seedance-2.0-ultra` model | **Direct** plan or higher |
| Face/person references (`SeedanceFaceRef`) | **Direct** plan or higher |

> If you get a 404 or "endpoint not available" error on reference inputs or Ultra, your account needs to be upgraded to Direct. Contact AnyFast support to activate it.

---

## Model Variants

| Node | Model ID | Resolutions | Best for |
|---|---|---|---|
| `Seedance AM 2.0 - Standard` | `seedance` | 480p / 720p / 1080p | General use |
| `Seedance AM 2.0 - Fast` | `seedance-fast` | 480p / 720p / 1080p | Quick iterations |
| `Seedance AM 2.0 - Ultra` | `seedance-2.0-ultra` | 720p / 1080p / 2k | Highest quality |

All three nodes share the same inputs — only the underlying model differs.

---

## Quick Start: Text to Video

```
Seedance AM - API Key  →  Seedance AM 2.0 - Standard  →  Seedance AM - Save Video
```

1. Add **Seedance AM - API Key** and paste your key.
2. Add **Seedance AM 2.0 - Standard** and write a prompt.
3. Connect `video_url` → **Seedance AM - Save Video**.
4. Queue. The node submits the job and polls until the video is ready.

---

## Example Workflows

| File | Mode | Description |
|---|---|---|
| `examples/01_text_to_video.json` | T2V | Minimal baseline — prompt only |
| `examples/02_image_to_video.json` | I2V | Animate an image from its first frame |
| `examples/04_face_reference.json` | R2V | Face/person as identity reference (`@image1` in prompt) |
| `examples/05_face_audio.json` | R2V | **Lip-sync with cloned voice** — face + voice sample + quoted dialogue |
| `examples/07_extend_video.json` | Extend | Continue a generated clip using its `task_id` |

To load: in ComfyUI go to **Load** → select the JSON file.

---

## Workflows

### 1. Text to Video

No image needed. Just a prompt.

```
API Key → Seedance2 → SaveVideo
```

---

### 2. Image to Video

Connect any image to `first_frame`. No intermediate node required.

```
LoadImage → Seedance2(first_frame) → SaveVideo
```

- Do **not** add `@image1` to the prompt — `first_frame` uses I2V mode, not reference tags.
- Connect a second image to `last_frame` to control both start and end frames.

---

### 3. Face / Person Reference

For real human faces, use `SeedanceFaceRef` instead of the regular image node. AnyFast routes them through the asset system to satisfy Volcano Engine's face-moderation policy. Requires **Direct** plan.

```
LoadImage → SeedanceFaceRef(ref_image_1) → Seedance2(anyfast_refs) → SaveVideo
API Key   → SeedanceFaceRef              ↑
```

- Use `@image1` in the prompt to tell the model where to apply the identity.
- **`group_id` and `asset_ids` are shown directly on the node** after upload — copy the `group_id` and paste it into `existing_group_id` on the next run to skip re-upload.
- Assets are cached locally by image hash: repeated runs with the same image are instant.

#### First run vs. repeat runs

| Situation | What to do |
|---|---|
| First run | Leave `existing_group_id` empty. A new group is created. |
| Repeat run, same images | Paste the saved `group_id` into `existing_group_id`. Upload is skipped. |
| Force re-upload | Enable `force_reupload` to bypass the local cache. |

#### Liveness verification (first upload only)

On first use, AnyFast may print a verification link in the ComfyUI console:

```
[Seedance Assets] *** IDENTITY VERIFICATION REQUIRED ***
[Seedance Assets] Open this link on your phone or browser (< 30 s): https://...
```

Open the link within 30 seconds. This is a one-time step per asset group.

---

### 4. Face + Audio Reference (Lip-Sync / Cloned Voice)

Drive a character's motion and voice from a reference audio clip. Requires **Direct** plan.

```
LoadImage → SeedanceFaceRef(ref_image_1) → Seedance2(anyfast_refs)     → SaveVideo
API Key   → SeedanceFaceRef              ↑
SeedanceReferenceAudio                  → Seedance2(reference_audio)   ↑
```

#### How reference_audio actually works

`reference_audio` is a **voice/rhythm style reference** — it tells the model what the voice should *sound like* (timbre, delivery, tempo). It does **not** become the audio track of the output by itself.

| What you want | How to do it |
|---|---|
| Character dances / moves to a music track | `reference_audio` = music clip, `generate_audio = True` |
| Character speaks in a cloned voice | `reference_audio` = voice sample, `generate_audio = True`, write dialogue in **double quotes** in the prompt |
| Embed an external audio file in the video | `generate_audio = False`, connect `SeedanceReferenceAudio` → `SaveVideo(reference_audio)` to mux it in |

#### Lip-sync with a cloned voice

Leave `generate_audio = True`. Write what the character should say in **double quotes** in the prompt. Reference the audio with `@audio1` for voice style:

```
A person speaking to camera @image1 @audio1. "Hello, welcome to my channel."
```

Seedance generates the speech in the voice style of your reference audio and syncs the lips to the words. The `@audio1` tag is auto-appended if missing, but you need the quoted dialogue for actual speech.

#### Embedding an external audio track (music, pre-recorded voice)

If you have a finished audio file you want in the video exactly as-is:

```
SeedanceReferenceAudio → Seedance2(reference_audio)   [generate_audio = False]
                       → SaveVideo(reference_audio)   ← splits the same wire
```

SaveVideo muxes the audio automatically on save.

- Audio must be **≤ 15 seconds** (API hard limit 15.2 s). Files longer than that are automatically trimmed to 15 s with a console warning.
- Files ≤ 10 MB are encoded as base64; larger files are uploaded to a temporary host.

---

### 5. Extend a Video

Continue a previously generated clip by wiring its `task_id` into `SeedanceExtend`.

```
API Key → Seedance2 → SeedanceSaveVideo (original)
               ↓ task_id
          SeedanceExtend → SeedanceSaveVideo (extended)
```

- Pick the **same model** used for the original generation in the `model` dropdown.
- Match the **same resolution** as the original.
- Leave `prompt` blank to continue naturally, or add text to steer the extension.
- Disable `generate_audio` if the original had no generated audio.
- The extended clip can itself be extended by chaining `task_id` outputs.

---

## All Nodes

### Core

| Node | What it does |
|---|---|
| `Seedance AM - API Key` | Stores your AnyFast API key and base URL. Connect its output to every generation and reference-video node. |
| `Seedance AM 2.0 - Standard` | Main generation node (`seedance` model). |
| `Seedance AM 2.0 - Fast` | Same as Standard but faster (`seedance-fast` model). |
| `Seedance AM 2.0 - Ultra` | Highest quality (`seedance-2.0-ultra` model, supports 2k). Requires Direct plan. |
| `Seedance AM - Extend Video` | Continue a previous generation by wiring its `task_id`. Pick the same model and resolution as the original. |
| `Seedance AM - Save Video` | Download and save the generated mp4. Optional `reference_audio` input: connect the same `SeedanceReferenceAudio` output here to auto-mux your audio into the final video (requires ffmpeg). |

### References

| Node | What it does |
|---|---|
| `Seedance AM - Reference Images (9 slots)` | Collect up to 9 non-face images as a `SEEDANCE_IMAGE_LIST` for `reference_images`. Do not use for real people — use `SeedanceFaceRef` instead. |
| `Seedance AM - Reference Video` | Upload a video file to AnyFast assets and return an `asset://` URI. Requires `api` connection. Minimum ~640×640 px, maximum ~1920×1088 px. |
| `Seedance AM - Reference Audio` | Encode or upload an audio file and return a data URI or public URL. No API key required. |

### Face / Asset (real people)

| Node | What it does |
|---|---|
| `Seedance AM - Face / Person Reference (asset)` | Upload real-person images through the AnyFast asset system to bypass face moderation. Caches asset IDs locally. Outputs `anyfast_refs`, `group_id`, and `asset_ids`. Requires Direct plan. |
| `Seedance AM - Asset Reference` | Wrap a raw `asset://` ID string into an `ANYFAST_IMAGE_REFS` entry. For manual asset management. |
| `Seedance AM - Upload Asset` | Manually upload a single image to AnyFast Asset Management. For bulk face uploads use `SeedanceFaceRef` instead. |

### Utilities

| Node | What it does |
|---|---|
| `Seedance AM - Show Text` | Display any string value (asset_id, group_id, video_url…) inside the node body for easy copy-paste. |
| `Seedance AM - Mux Audio into Video` | Merge an audio file into a saved video using ffmpeg. Use after SaveVideo when you want your reference audio embedded in the final mp4. |

---

## Generation Parameters

| Parameter | Values | Notes |
|---|---|---|
| `prompt` | text | `@image1`…`@image9`, `@video1`, `@audio1` are auto-appended when needed |
| `resolution` | `480p` / `720p` / `1080p` (Standard/Fast); `720p` / `1080p` / `2k` (Ultra) | |
| `ratio` | `16:9` `9:16` `4:3` `3:4` `1:1` `21:9` `adaptive` | |
| `duration` | 4 – 15 seconds | |
| `generate_audio` | true / false | Auto-generates synced voice, sound effects, and music. Turn off when using `reference_audio`. |
| `watermark` | true / false | ByteDance watermark |
| `seed` | -1 or integer | `-1` = random; any positive integer = reproducible |

---

## Mixing References

Two **mutually exclusive** modes:

| Mode | Inputs used | What it does |
|---|---|---|
| **I2V** | `first_frame` and/or `last_frame` | Video starts/ends on an exact frame |
| **R2V** | `reference_images`, `reference_video`, `reference_audio`, `anyfast_refs` | Style, motion, and rhythm transfer |

You cannot combine I2V and R2V inputs in the same request.

### Valid combinations

| Combination | Mode |
|---|---|
| prompt only | T2V |
| `first_frame` | I2V |
| `first_frame` + `last_frame` | I2V |
| `anyfast_refs` (face) | R2V |
| `anyfast_refs` + `reference_audio` | R2V |
| `anyfast_refs` + `reference_audio` + `reference_video` | R2V |
| `reference_video` | R2V |
| `reference_images` | R2V |

### Invalid combinations

| Combination | Why |
|---|---|
| `reference_audio` alone | AnyFast requires at least one image or video ref alongside audio |
| `first_frame` + any R2V input | Cannot mix I2V frame control with R2V references |

---

## Video Resolution Requirements

The `SeedanceReferenceVideo` node uploads your video to the AnyFast asset system. The video must meet these pixel count constraints:

| Limit | Pixels | Equivalent resolution |
|---|---|---|
| Minimum | 409,600 px | ~640 × 640 |
| Maximum | 2,086,876 px | ~1920 × 1088 |

If your video falls outside this range you will get a `PixelCountTooSmall` or `PixelCountTooLarge` error. Re-export at a compatible resolution before uploading.

---

## Troubleshooting

**"real-person face detected" or PrivacyInformation error**
Use `SeedanceFaceRef` instead of connecting the face image to `reference_images` or `anyfast_refs` directly. The face node routes images through the asset system which bypasses this check.

**Liveness verification link in console**
Open the printed URL on your phone within 30 seconds. This only happens on the first upload per group.

**"endpoint not available" or 404 on reference inputs / Ultra**
These features require a **Direct** plan. Contact AnyFast support to activate it on your account.

**"API key is empty"**
Make sure the API Key node's `api_key` field is filled and its output is connected to the generation node.

**`first_frame` IMAGE output is blank / black**
Install `opencv-python` (`pip install opencv-python`). Without it the first frame extraction falls back to a 64×64 black image.

**Reference audio accepted but lip-sync is wrong or there's no audio**
`reference_audio` is a voice *style* reference, not a playback track. For lip-sync: keep `generate_audio = True` and write the dialogue in **double quotes** in the prompt — `"Hello, say this."`. Use `@audio1` to apply the voice style from your reference. If you want the raw audio file embedded instead, set `generate_audio = False` and connect `SeedanceReferenceAudio` → `SaveVideo(reference_audio)`.

**"reference_audio cannot be the only reference input"**
AnyFast requires at least one image or video reference when using audio. Connect an image via `SeedanceRefImages` or `SeedanceFaceRef` alongside the audio.

**Audio duration error (InvalidParameter content[2])**
The API rejects audio longer than 15.2 seconds. The node auto-trims to 15 s and prints a warning in the console — just re-queue after the trim.

**PixelCountTooSmall on reference video**
Re-export the video at a higher resolution (minimum ~640×640 px / 409,600 total pixels).

**Generation times out after 1200 s**
Seedance Ultra at 2k can take longer than other variants. If you hit the 20-minute timeout regularly, check AnyFast's status page.

**Asset not found / asset not visible**
The node waits for `Active` status automatically. If it times out, AnyFast may be under load — retry in a few minutes. You can paste the saved `group_id` into `existing_group_id` and re-run without re-uploading.

---

## License

Apache 2.0
