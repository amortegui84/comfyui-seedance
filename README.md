# ComfyUI AnyFast Seedance

Generate videos with **ByteDance Seedance 2.0 and 2.5** inside ComfyUI, powered by [AnyFast](https://www.anyfast.ai).

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

There is **one generation node** — `Seedance AM - Video`. Pick the model in its
`model` dropdown; the `resolution` list and `duration` range narrow to whatever
that model supports.

| `model` | Resolutions | Duration | Refs (img / vid / aud) | Best for |
|---|---|---|---|---|
| `seedance-2.0` | 480p / 720p / 1080p | 4–15s | 9 / 3 / 3 | General use |
| `seedance-2.0-fast` | 480p / 720p / 1080p | 4–15s | 9 / 3 / 3 | Quick iterations |
| `seedance-2.0-mini` | 480p / 720p / 1080p | 4–15s | 9 / 3 / 3 | Cheapest 2.0 |
| `seedance-2.0-ultra` | 720p / 1080p / 2k | 4–15s | 9 / 3 / 3 | Highest resolution |
| `seedance-2.5` | **480p / 720p only** | **`-1` or 4–30s** | **30 / 10 / 10** | Long clips, many references, audio-only |

If you pick a combination the model does not support, the node says so before
sending the request — it never fails halfway through a paid generation.

> **Upgrading from an earlier version?** The old per-model nodes
> (`Seedance AM 2.0 - Standard / Fast / Ultra`, `Seedance AM 2.5`) still exist and
> still work, so saved workflows keep loading. They are marked deprecated and
> hidden from the Add Node menu. Replace them with `Seedance AM - Video` when
> convenient — same inputs, same outputs, one extra `model` dropdown.

### Choosing between 2.0 and 2.5

**2.5 trades resolution for length.** It is not a strict upgrade:

| | Seedance 2.0 | Seedance 2.5 |
|---|---|---|
| Resolution | up to 1080p (2k on Ultra) | **480p / 720p only** |
| Duration | 4–15s | 4–30s, or `-1` to let the model choose |
| References | 9 images / 3 videos / 3 audio | 50 total — 30 images / 10 videos / 10 audio |
| Audio-only generation | not supported | **supported** — generate from an audio reference with no image or video |
| Tiers | Standard / Fast / Ultra | one model, no tiers |
| `web_search` grounding | — | available on text-to-video |

Reach for **2.0 Ultra** when you need 1080p or 2k. Reach for **2.5** when you need
a clip longer than 15s, more than 9 references, or audio-driven generation.

### Seedance 2.5 task families

The AnyFast guide splits 2.5 into five task types. Some of them constrain `ratio`
and `duration` — the node does not force these for you, so set them yourself:

| Task | What you connect | Required settings |
|---|---|---|
| Text-to-video | prompt only | any `ratio`, `duration` `-1` or 4–30 |
| Reference-to-video | `reference_images` / `reference_video` / `reference_audio` | any `ratio`, `duration` `-1` or 4–30 |
| Video editing (add / remove / replace / repair) | reference media + editing intent in the prompt | `ratio: adaptive` **and** `duration: -1` |
| Video extension (continue a clip) | reference media + "continue / extend" intent | `ratio: adaptive` |
| First / last frame | `first_frame`, optionally `last_frame` | `ratio: adaptive` |

Frame-guided workflows cannot be combined with editing or extension intents.

Spoken and sung audio is generated in 11 languages: Chinese, English, Spanish,
Indonesian, Malay, Thai, Arabic, Portuguese, Vietnamese, Japanese and Korean.

---

## Quick Start: Text to Video

```
Seedance AM - API Key  →  Seedance AM - Video  →  Seedance AM - Save Video
```

1. Add **Seedance AM - API Key** and paste your key.
2. Add **Seedance AM - Video**, pick a `model`, and write a prompt.
3. Connect `video_url` → **Seedance AM - Save Video**.
4. Queue. The node submits the job and polls until the video is ready.

---

## Example Workflows

Each one demonstrates exactly one capability.

| File | Shows |
|---|---|
| `01_text_to_video.json` | The baseline — prompt only |
| `02_image_to_video.json` | Animate a still from an exact first frame |
| `03_first_last_frame.json` | Interpolate between a start and an end image |
| `04_save_identity.json` | Upload a real person **and save them as a named identity** |
| `05_reuse_identity.json` | **Reuse that identity** — no image, no upload, resolves from disk |
| `06_lip_sync.json` | Identity + voice sample + quoted dialogue |
| `07_extend_video.json` | Continue a clip via its `task_id` (2.0 only) |
| `08_v25_long_clip.json` | Seedance 2.5 — 30s in a single pass |
| `09_v25_audio_only.json` | Seedance 2.5 — generate from audio alone, `duration: -1` |
| `10_v25_multi_reference.json` | Seedance 2.5 — identity + motion video + music together |
| `11_v25_web_search.json` | Seedance 2.5 — `web_search` grounding |

To load: in ComfyUI go to **Load** → select the JSON file.

Examples 04, 05, 06 and 10 use a placeholder identity called `my-subject`. Run
example 04 once to create it, or pick one of your own from the dropdown — a
missing identity behaves like a missing checkpoint: the rest of the graph is fine.

### Regenerating them

```bash
python build_examples.py --write
```

The workflows are **generated**, not hand-written. Hand-written ComfyUI JSON
carries its own copy of every node's input list plus a positional array of widget
values, so it silently rots whenever a node changes — that is how an older example
ended up asking Seedance 2.5 for 1080p. `build_examples.py` describes each graph
compactly and derives the sockets and slot indices by introspecting the real node
classes, then validates widget values against each node's own `INPUT_TYPES`,
including the per-model resolution and duration limits. Run it without `--write`
to validate only. `test_nodes.py` re-checks the files on disk, so a hand-edit that
breaks one is caught too.

---

## Tests

```bash
python test_nodes.py
```

Offline — it builds request payloads and asserts on them without calling AnyFast,
so it costs nothing. It covers:

- per-model resolution / duration / reference limits, on both the unified and the deprecated nodes
- that the deprecated nodes still produce byte-identical payloads
- **widget order**, which ComfyUI serialises positionally — inserting a widget anywhere but the end silently corrupts every saved workflow
- the identity store, including that re-uploading one image does not reshuffle `@image1`/`@image2`
- that a fully-cached FaceRef run makes zero asset-API calls
- that `web/js/model_variants.js` has not drifted from `MODEL_SPECS`
- that every workflow in `examples/` still matches the nodes it uses

Run it after touching `nodes.py`, the `.js`, or the examples.

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
| `Seedance AM - Video` | The generation node. Pick any Seedance 2.x model in the `model` dropdown — resolution and duration follow it. |
| `Seedance AM 2.0 - Standard / Fast / Ultra (legacy)`, `Seedance AM 2.5 (legacy)` | Deprecated one-model-per-node versions, hidden from the Add Node menu. Kept only so saved workflows keep loading. |
| `Seedance AM - Extend Video` | **2.0 only.** Continue a previous generation by wiring its `task_id`. Pick the same model and resolution as the original. On 2.5, extend natively instead: feed the clip back as `reference_video` with a "continue" intent and `ratio: adaptive`. |
| `Seedance AM - Save Video` | Download and save the generated mp4. Optional `reference_audio` input: connect the same `SeedanceReferenceAudio` output here to auto-mux your audio into the final video (requires ffmpeg). |

### References

| Node | What it does |
|---|---|
| `Seedance AM - Reference Images (9 per node, chainable)` | Collect up to 9 non-face images as a `SEEDANCE_IMAGE_LIST` for `reference_images`. Chain nodes via `existing_images` to reach 2.5's 30-image limit. Do not use for real people — use `SeedanceFaceRef` instead. |
| `Seedance AM - Reference Video` | Upload a video file to AnyFast assets and return an `asset://` URI. Requires `api` connection. Minimum ~640×640 px, maximum ~1920×1088 px. |
| `Seedance AM - Reference Audio` | Encode or upload an audio file and return a data URI or public URL. No API key required. **See the privacy note below.** |

> ⚠️ **Audio over 10 MB leaves your machine via a public file host.**
> `Seedance AM - Reference Audio` inlines files up to 10 MB as a base64 data URI,
> which never leaves the AnyFast request. Anything larger is uploaded to
> **catbox.moe**, falling back to litterbox and 0x0.st, and the resulting public
> URL is what gets sent. Those hosts are not private and Catbox uploads are
> permanent. If the clip is someone's voice, keep it under 10 MB — trimming to the
> 2–15s the API accepts anyway is usually enough — or host it yourself and paste
> your own URL.

The `reference_video` and `reference_audio` sockets on the generation nodes accept
**one URL per line**, so a single socket can carry several references (2.0: 3 each;
2.5: 10 each). `@video1…@videoN` and `@audio1…@audioN` are tagged automatically.

> Note: media uploaded through the AnyFast **asset** system is still capped at
> 2–15s (video ≤50 MB, audio ≤15 MB) regardless of model. 2.5's longer 2–30s
> video references (≤200 MB) only apply to references passed as direct URLs.

### Face / Asset (real people)

| Node | What it does |
|---|---|
| `Seedance AM - Face / Person Reference (asset)` | Upload real-person images through the AnyFast asset system to bypass face moderation. Caches asset IDs locally. Set `identity` to also save them as a reusable named identity. Outputs `anyfast_refs`, `group_id`, and `asset_ids`. Requires Direct plan. |
| `Seedance AM - Identity (saved person)` | Pick a previously saved person by name from a dropdown and get their `anyfast_refs` instantly — no image connected, no upload, nothing sent to AnyFast. See [Identities](#identities). |
| `Seedance AM - Asset Reference` | Wrap a raw `asset://` ID string into an `ANYFAST_IMAGE_REFS` entry. For manual asset management. |
| `Seedance AM - Upload Asset` | Manually upload a single image to AnyFast Asset Management. For bulk face uploads use `SeedanceFaceRef` instead. |

### Utilities

| Node | What it does |
|---|---|
| `Seedance AM - Show Text` | Display any string value (asset_id, group_id, video_url…) inside the node body for easy copy-paste. |
| `Seedance AM - Mux Audio into Video` | Merge **any** audio file into an already-saved video using ffmpeg — background music, a separate voiceover, a second audio pass. For the common case of embedding the reference audio you used during generation, `SaveVideo`'s own `reference_audio` input already does it. |

---

## Generation Parameters

| Parameter | Values | Notes |
|---|---|---|
| `prompt` | text | `@image1`…`@imageN`, `@video1`…`@videoN`, `@audio1`…`@audioN` are auto-appended when needed |
| `resolution` | `480p` / `720p` / `1080p` (2.0 Standard/Fast); `720p` / `1080p` / `2k` (2.0 Ultra); `480p` / `720p` (2.5) | 2.5 has no 1080p or higher |
| `ratio` | `16:9` `9:16` `4:3` `3:4` `1:1` `21:9` `adaptive` | 2.5 edit / extend / frame tasks require `adaptive` |
| `duration` | 4 – 15 seconds (2.0); `-1` or 4 – 30 seconds (2.5) | `-1` lets 2.5 choose the length; required for edit tasks |
| `generate_audio` | true / false | Auto-generates synced voice, sound effects, and music. Turn off when using `reference_audio`. |
| `watermark` | true / false | ByteDance watermark |
| `seed` | -1 or integer | `-1` = random; any positive integer = reproducible |
| `web_search` (2.5 only) | true / false | Text-to-video only — grounds the prompt in current information before generating |

---

## Wiring references into the generation node

The generation node has six reference sockets. Which one you use depends on
**what the image is of**, not on what you want it to do:

| What you have | Node to use | Socket |
|---|---|---|
| A real person's face | `Face / Person Reference` (first time) or `Identity` (after) | `anyfast_refs` |
| An object, product, place, style board | `Reference Images` | `reference_images` |
| The exact frame the video starts on | `LoadImage` straight in | `first_frame` |
| The exact frame it ends on | `LoadImage` straight in | `last_frame` |
| A video to copy motion from | `Reference Video` | `reference_video` |
| Audio to drive rhythm or clone a voice | `Reference Audio` | `reference_audio` |

### Why real faces need a different socket

The asset system (`asset://` IDs) is **not face-specific** — it can carry any
image. But Volcano Engine rejects real-person photos sent inline as base64, so
faces *must* go through it. Objects can go either way, and the direct route is
faster: no upload, no waiting for the asset to become Active.

So the rule is simply: **people → `anyfast_refs`, everything else →
`reference_images`.** Use `Upload Asset` + `Asset Reference` if you ever want a
non-face image on the asset route too (e.g. to reuse a product shot by ID).

### They can be combined

Connecting a face to `anyfast_refs` **and** product shots to `reference_images`
in the same generation works. The images are numbered together for the prompt:
asset entries first, then the plain ones.

```
Identity (person)      → anyfast_refs      → @image1
Reference Images (2)   → reference_images  → @image2, @image3
```

Write the prompt using those tags — `"@image1 holding @image2 in a @image3
setting"`. If you leave the tags out entirely they are appended automatically,
but then the model decides what each image is for.

> Before v0.3.0 this combination silently discarded everything on
> `reference_images` whenever `anyfast_refs` was connected — no error, just a
> video generated without them. Fixed; there is a regression test.

### What still cannot be combined

`first_frame` / `last_frame` are **frame control**, and AnyFast does not accept
frame control together with references in one request. The node rejects it up
front rather than letting the API fail. Pick one mode:

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
| `reference_audio` alone | R2V — **Seedance 2.5 only** |

### Invalid combinations

| Combination | Why |
|---|---|
| `reference_audio` alone on a **2.0** node | 2.0 requires at least one image or video ref alongside audio. Use the 2.5 node for audio-only generation. |
| `first_frame` + any R2V input | Cannot mix I2V frame control with R2V references |
| More refs than the model allows | 2.0: 9 images / 3 videos / 3 audio. 2.5: 30 / 10 / 10. |

---

## Identities

Real-person references have to go through the AnyFast asset system, which returns
opaque IDs like `asset://asset-20260427034723-fd8qt`. Identities put a name on
them so you never have to keep that mapping yourself.

**Saving one:** set `identity` on `Seedance AM - Face / Person Reference` (e.g.
`my-subject`) and run once. The images upload as usual and the asset IDs are written to
an identity file.

**Reusing it:** add `Seedance AM - Identity`, pick `my-subject` from the dropdown, wire
`anyfast_refs` into the generation node. No image, no upload, no waiting — it
resolves from disk. Restart ComfyUI after creating a new identity for it to show
up in the dropdown.

### Where the files live

```
ComfyUI/user/seedance/identities/my-subject.json
```

One file per identity, so a single identity can be copied to another machine, and
renaming the file renames the identity. Override the folder with the
`SEEDANCE_IDENTITIES_DIR` environment variable — **point it at a synced folder
(OneDrive, Dropbox) and your identities follow you between machines.**

It has to be an environment variable rather than a node input because the dropdown
is built in `INPUT_TYPES`, before any node connection exists.

```json
{
  "identity": "my-subject",
  "group_id": "group-20260427034718-89l4z",
  "notes": "",
  "assets": [
    {
      "asset_id": "asset://asset-20260427034723-fd8qt",
      "role": "reference_image",
      "image_sha": "ad870a802cbe...",
      "uploaded_at": "2026-08-07T09:43:26"
    }
  ]
}
```

The file is plain JSON on purpose: open it and copy an `asset_id` into a script,
into `Seedance AM - Asset Reference`, or anywhere else you need the raw ID.
The order of `assets` decides which one becomes `@image1`, `@image2` … so it is
preserved when an image is re-uploaded.

### Importing what you already have

```bash
python migrate_identities.py
```

Shows what it would import from the old hash cache, grouped by AnyFast asset
group. Add `--apply` to write the files as `unnamed-1`, `unnamed-2`… then rename
them. Nothing is deleted and the hash cache keeps working, so it is safe to run
and safe to skip.

### Two caches, two jobs

| Store | Question it answers |
|---|---|
| `seedance_asset_cache.json` (hash cache) | "Have I already uploaded *this exact image*?" — skips redundant uploads |
| `seedance/identities/*.json` | "What is *my-subject's* asset ID?" — the question you ask when building a workflow |

Leaving `identity` empty keeps the old hash-cache-only behaviour exactly as before.

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
