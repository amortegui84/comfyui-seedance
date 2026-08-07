# Seedance node — implementation & analysis notes

## Architecture review (2026-08-07)

15 nodes were registered before this pass. Roughly half existed because of
implementation detail rather than because the user needs a distinct concept.
Findings, ordered by how much confusion they cause. **§1 and §3 are done; §2, §4
and §5 remain proposals.**

### 1. Four generation nodes that differ by one string — DONE
`Seedance2`, `Seedance2Fast`, `Seedance2Ultra` and `SeedanceV25` are all
`_V2Base` subclasses whose only real difference is `MODEL_ID`, `RESOLUTIONS` and
the duration range. `seedance-2.0-mini` is live on AnyFast and would make it five.

Collapsed into one **`SeedanceVideo`** node ("Seedance AM - Video") with a `model`
combo covering all five live ids, including `seedance-2.0-mini`, which previously
had no node at all.

- `MODEL_SPECS` in `nodes.py` is the single source of truth for the per-model
  resolution list, duration range, reference caps, audio-only flag and poll
  timeout. `_V2Base._spec()` resolves them; the legacy classes answer from their
  class attributes, `SeedanceVideo` looks them up from the picked model.
- `INPUT_TYPES` offers the *union* of resolutions (`RES_ALL`, 720p first so the
  default is valid everywhere). `generate()` rejects a resolution the chosen
  model does not support, before the request is sent.
- `web/js/model_variants.js` narrows the resolution dropdown and clamps the
  duration slider when `model` changes — same widget-callback trick
  `web/js/api_key.js` already used. It is a convenience layer only; Python is
  what enforces. `test_nodes.py` asserts the two tables have not drifted.
- The four old classes stay registered and marked `DEPRECATED = True`, so saved
  workflows keep loading and keep their exact previous behaviour (note they use
  the older `seedance` / `seedance-fast` aliases, not the dotted ids). A test
  asserts the unified node's payload is byte-identical to the legacy 2.5 node's.

**5 nodes → 1 visible.** Adding a future Seedance model is now one entry in
`MODEL_SPECS` plus one in the .js.

### 2b. The asset ID mechanic — DONE 2026-08-07

Reviewed the asset pipeline end to end. Four concrete problems, three of which
had their own fix already half-written in the code:

| Problem | Evidence | Fix |
|---|---|---|
| Assets had no usable name | `asset_name = f"face_{role}_{idx+1}"` — all 28 uploaded images were called `face_reference_image_1` etc. The user kept a hand-written index in `API-KEY.txt` | `identity` field; the name goes into AnyFast's `Name` and into an identity file |
| A throwaway group per run | `_ensure_group` ran *before* the cache loop, so a fully-cached run still paid `CreateAssetGroup` + 3s. Result: 28 images across 8 groups | Group resolved lazily — created only on the first real upload |
| The cache stored `group_id` and never read it | written at the cache-write site, no reader anywhere | prefer the identity's saved group, then the cached one |
| Four layers of insurance on one race | 5s in `_upload_asset` + `_wait_for_asset_active` polling + **20s fixed** settle + up to 12 submit retries in `_submit_and_poll`. ~35-40s per new image, ~6 min for nine | settle cut 20s → 5s (`ASSET_SETTLE_DEFAULTS`), overridable via `SEEDANCE_ASSET_SETTLE`; the submit retry is the real safety net |

**Design decisions worth keeping:**
- **One file per identity, not one big JSON.** A single identity can be copied to
  another machine, renaming the file renames the identity, and a synced folder
  does not produce merge conflicts.
- **Not in the custom-node folder.** A `git pull` or reinstall would wipe it.
  Default is `ComfyUI/user/seedance/identities/`, which survives updates.
- **Folder set by `SEEDANCE_IDENTITIES_DIR`, an env var, not a node input** —
  the dropdown is built in `INPUT_TYPES`, before any connection exists, so there
  is nothing else to read a path from at that point. Pointing it at OneDrive is
  the intended way to share identities across machines.
- **Slugs are ASCII-folded** (`Ana María` → `ana-maria.json`) because cloud sync
  clients and cross-OS copies still mishandle non-ASCII filenames. The accented
  name is preserved inside the file.
- **`_record_identity_asset` updates in place**, never remove-and-append: list
  order decides which asset is `@image1`, so re-uploading one image of an
  identity must not reshuffle the prompt tags of every workflow using it. There
  is a regression test for exactly this.
- **Empty `identity` = previous behaviour**, byte for byte. The identity store is
  additive; the hash cache is untouched and still does its own job.

Migration: `migrate_identities.py` groups the old hash cache by AnyFast group and
writes `unnamed-N` files. Ran it — 28 images → 8 identities. Note that three of
the four IDs the user had hand-noted in a local scratch file were
**not** in the hash cache at all; they predate it. They were added directly as
identity files, which is exactly the gap this store closes.

### 2c. Reference audio >10 MB goes to a PUBLIC host — documented, not changed

`SeedanceReferenceAudio` inlines audio up to 10 MB as a base64 data URI, but
anything larger goes through `_upload_to_temp_host` → catbox.moe (permanent),
then litterbox, then 0x0.st. The resulting public URL is what AnyFast fetches.
Nothing warned the user about this, and the typical payload here is *a real
person's voice sample*.

Left as-is for now because the >10 MB path is the only way to send large audio
and removing it breaks working setups, but it is now called out in the README.
Proper fix, if wanted: route large audio through the AnyFast **asset** system
(which already exists for video and images and is private) instead of a public
host, and drop the temp-host fallback entirely. Asset audio is capped at 15 MB /
2–15s, which covers essentially every legitimate reference clip.

### 2. Three different ways to attach an image reference
`SeedanceRefImages` (base64), `SeedanceFaceRef` (asset://) and
`SeedanceUploadAsset` + `SeedanceAssetRef` (manual asset) all answer "give the
model a picture". Picking the wrong one for a real person is not caught in the
UI — it surfaces as a 400 from AnyFast at generation time.

→ Two changes, independent of each other:
  a. **Merge `SEEDANCE_IMAGE_LIST` and `ANYFAST_IMAGE_REFS` into one type.** The
     generation node then has ONE `references` socket instead of
     `reference_images` + `anyfast_refs`, and `first_frame`/`last_frame` stop
     being expressible in two different places with different mixing rules.
  b. **Auto-recover from the face-moderation 400.** `_submit_and_poll` already
     detects "real person detected" and prints instructions. It could instead
     upload the offending images as assets and retry, turning a stop-and-rewire
     error into a transparent (slower) success.

### 3. `SeedanceMuxAudio` overlaps `SaveVideo` but is NOT redundant — DONE (kept)
Commit 5e5c634 added muxing into `SeedanceSaveVideo`, and the first read of this
review called MuxAudio dead weight. It isn't. `SaveVideo` only muxes the
`reference_audio` STRING it was handed during generation; `SeedanceMuxAudio`
takes an arbitrary AUDIO input / file / path and applies it to an already-saved
video — background music, a separate voiceover, a second audio pass. Deleting it
would remove capability, not duplication. Documentation should make the split
explicit instead.

### 4. `SeedanceExtend` is on borrowed time
It posts to `POST /v1/video/extend`, lists 2.0 model ids only, and caps at 15s.
2.5 does extension natively (reference_video + "continue" intent +
`ratio: adaptive`), which needs no node at all. Mark legacy / 2.0-only.

### 5. Categories no longer describe anything
`Core` holds the API key, the generation nodes, Extend and SaveVideo; `2.5` is a
category for a single model; `AnyFast` and `Advanced` split the asset nodes
arbitrarily. Suggested: `Seedance AM` (key, generate, save), `Seedance AM/
References`, `Seedance AM/Advanced` (raw asset management), `Seedance AM/Utils`.

### Where this landed
Visible nodes went from 15 to **12** (16 registered, 4 hidden as deprecated):
API Key · **Video** · Reference Images · Reference Video · Reference Audio ·
Face Ref · Asset Ref · Upload Asset · Extend · Save Video · Mux Audio · Show Text.

Doing §2 as well would take it to 9 by merging the two reference types and the
three image-attachment paths. That one touches the working asset pipeline, so it
is deliberately left for a separate pass.

### Migration cost
Removing a node type breaks any saved workflow that used it. Every consolidation
here ships non-breaking the same way: keep the old key in `NODE_CLASS_MAPPINGS`
(pointing at the new class where they merged, as with `SeedanceV25Standard` →
`SeedanceV25`) and set `DEPRECATED = True` so ComfyUI hides it from the Add Node
menu while still loading it.

## Seedance 2.5 support — FINALIZED 2026-08-07

2.5 is live on AnyFast. Everything below was verified against
`GET /v1/models` (live, with the project key) and the official docs at
`docs.anyfast.ai/{api-reference,guides}/model-api/bytedance/seedance-2-5`.

### What the earlier placeholder implementation got wrong

The 2026-06-23 nodes were built from press coverage before AnyFast shipped the
model. Three assumptions turned out to be false:

| Assumption (June) | Reality (docs + live API) |
|---|---|
| Two tiers: `seedance-2.5` + `seedance-2.5-pro` | **One model id only: `seedance-2.5`.** `/v1/models` lists no `-pro`, `-fast` or `-ultra` 2.5 variant. |
| Resolutions 1080p, plus 2k/4k on Pro | **480p / 720p ONLY.** 2.5 trades resolution for length; 1080p+ requires a 2.0 node. |
| 50 references, count unspecified | **30 images + 10 videos + 10 audio** (content array 1–51 items). |

### Confirmed 2.5 specs (wired into the nodes)
- `MODEL_ID = "seedance-2.5"`, single node `SeedanceV25`.
- `RES_V25 = ["720p", "480p"]`.
- Duration `-1` (model chooses) or `4`–`30`. `DURATION_MIN = -1` on the 2.5 class
  only, so 2.0 nodes still reject `-1`.
- `REF_LIMITS_V25 = {"image": 30, "video": 10, "audio": 10}` vs
  `REF_LIMITS_V2 = {"image": 9, "video": 3, "audio": 3}`. Both enforced locally
  before the request, with a message that names the cap.
- **Audio-only generation is 2.5-only** — `AUDIO_ONLY_OK = True`. The old
  "AnyFast requires an image or video alongside audio" guard is now a 2.0-only
  rule and points the user at the 2.5 node.
- `tools: [{"type": "web_search"}]` via an optional `web_search` toggle
  (text-to-video only, per the guide).
- `POLL_TIMEOUT = 2400` on 2.5 (30s clips exceed the 2.0 20-minute budget).
  `_submit_and_poll` now takes `poll_timeout` and threads it into `_poll_v2`;
  2.0 keeps the 1200s default.
- Audio output: `generate_audio` works, and 2.5 speaks/sings in 11 languages
  (zh, en, es, id, ms, th, ar, pt, vi, ja, ko).

### Task families (documented in the README, not enforced in code)
2.5 splits into five task types; editing/extension/frame-guided ones require
`ratio: "adaptive"` and (for editing) `duration: -1`. The nodes deliberately do
**not** force these — the user sets ratio/duration themselves, since inferring
"editing intent" from prompt text would be guesswork. Documented in the README's
"Seedance 2.5 task families" table.

### Back-compat decisions
- `SeedanceV25Pro` was **deleted**. It never produced a video (the model id does
  not exist), so no working workflow can depend on it.
- The surviving node class is `SeedanceV25` but it stays registered under the key
  `"SeedanceV25Standard"`, so workflows saved against the June placeholder — like
  `examples/11_face_reference_v25.json` — still load. Display name is now
  "Seedance AM 2.5" (no tier suffix).
- `examples/11` had `resolution: "1080p"`, which 2.5 rejects. Changed to 720p/20s.

### Multi-reference handling (new)
- `reference_video` / `reference_audio` sockets accept **one URL per line**, so a
  single socket carries up to 3 (2.0) or 10 (2.5) references. A lone URL behaves
  exactly as before. `@video1…@videoN` / `@audio1…@audioN` are tagged per entry.
- `SeedanceRefImages` gained an `existing_images` input so collectors chain to
  reach 2.5's 30-image limit without a 30-socket node.

### Still open
- **Asset-uploaded media is still capped at 2–15s** (video ≤50 MB, audio ≤15 MB)
  by the AnyFast asset API, regardless of model. 2.5's longer 2–30s / ≤200 MB
  video references only apply to direct URLs. Documented in the README.
- `return_last_frame` (both 2.0 and 2.5) is **not implemented** — the task-query
  response schema does not document a field that carries the returned frame, so
  there is nothing to read it from. Revisit if AnyFast documents it.
- `SeedanceExtend` still targets `POST /v1/video/extend` with 2.0 model ids only.
  Left alone: 2.5 does extension natively (reference_video + "continue" intent +
  `ratio: adaptive`), which is documented in the README instead.
- `seedance-2.0-mini` is live on AnyFast but has no node. Not added — see the
  architecture notes about node-count sprawl.

## Runtime fixes (from live testing 2026-06-23)

### Asset GroupType — pre-resolve + cache
The current AnyFast channel **requires** `Filter.GroupType` on `ListAssets`
(groups resolve to `GroupType=AIGC`), contradicting the older "omit GroupType"
note. The code already recovered via an in-loop fallback, but every asset wait
first fired a guaranteed `400 GroupType is missing`, polluting the AnyFast error
dashboard. Now `_wait_for_asset_active` calls `_resolve_group_type` (cached via
`_GROUP_TYPE_CACHE`, best-effort, never raises) **before** the first ListAssets
call, so GroupType is included up front and the 400 no longer happens. The
in-loop fallback is kept as a safety net for older typeless-group channels.

### Friendly `model_not_found` error for 2.5 — REMOVED 2026-08-07
The June build special-cased `seedance-2.5*` in `_submit_and_poll` to explain that
the model was not yet on AnyFast. That branch is gone now that 2.5 ships; the
generic "no available channel — enable it in the AnyFast Console" message applies.
The June live test had already confirmed the rest of the pipeline (asset upload,
GroupType resolve, 30s prompt) worked end to end; only the model was missing.

## §5 analysis findings

### a) I2V vs R2V validation — FIXED
Previously the validation that prevents mixing modes existed **only** for the
asset-based `anyfast_refs` path (raises if frame-control roles are combined with
reference roles). The direct `first_frame` IMAGE input + `reference_images` /
`reference_video` / `reference_audio` combination was **not** guarded in code.

Added an explicit guard at the top of `_V2Base.generate()`:

```python
if first_frame is not None and (reference_images or anyfast_refs or reference_video or reference_audio):
    raise ValueError("Cannot mix I2V (first_frame) with R2V references ...")
```

This applies to both 2.0 and 2.5 (shared base). It only rejects genuinely
incompatible combinations, so valid existing 2.0 workflows are unaffected.

### b) Configurable timeout — RESOLVED per-model (2026-08-07)
`_submit_and_poll` now takes `poll_timeout` and threads it into `_poll_v2`. Each
generation class sets `POLL_TIMEOUT`: 1200s for 2.0 (unchanged), 2400s for 2.5,
whose 30s clips render well past the old budget. Still not exposed as a node
input — a per-model default covers the real failure case without adding a widget
to every node. Revisit if users hit the 2400s ceiling.

### c) Seed handling — OK, no bug
`if seed != -1: payload["seed"] = seed` — the seed field is correctly omitted
when `seed == -1` and included otherwise. No fix needed.

### d) `_stabilize_anyfast_asset` 20s Image delay — NOT CHANGED (documented)
After an Image asset reaches `Active`, a fixed 20s settle delay is applied on
every run. For repeated runs where the asset is already `Active` (cache hit path
skips upload entirely, so no delay there) this is fine, but for force-reupload /
new-asset runs the 20s is always paid. Could be made adaptive (e.g. shorter
delay, or poll a readiness signal) but reducing it risks reintroducing the
"asset not visible to generation" 400s that the delay was added to avoid. Left
unchanged pending real-world timing data.
