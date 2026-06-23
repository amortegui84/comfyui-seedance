# Seedance node — implementation & analysis notes

## Seedance 2.5 support (added)

- New nodes: `SeedanceV25Standard` (`seedance-2.5`) and `SeedanceV25Pro` (`seedance-2.5-pro`).
- Implemented by **subclassing `_V2Base`** — the same base class the 2.0 nodes use.
  All payload building, reference/asset handling, I2V/R2V logic and polling are
  reused with zero duplication. Each 2.5 class only overrides `MODEL_ID`,
  `RESOLUTIONS`, `DURATION_DEFAULT` (10), `DURATION_MAX` (30) and `CATEGORY`.

### Seedance 2.5 — confirmed specs (from launch coverage, 2026-06-23)
- **Duration: up to 30s** in a single pass, no stitching (vs 15s in 2.0). → wired
  as `MAX_DURATION_V25 = 30`; the 2.5 duration slider now goes 4–30s.
- **Up to 50 multimodal references** (images + audio + video + style/3D refs),
  ~4x the 2.0 limit. *The plugin's collector nodes only expose 9 slots — see
  "Known gaps" below; the generation node itself does not cap the list length.*
- **4K: reported but NOT officially confirmed** for 2.5 (4K *is* confirmed for 2.0).
  Offered only on the `SeedanceV25Pro` placeholder (`RES_V25_PRO` includes `4k`).
- **Audio output not explicitly confirmed** for 2.5 (2.0 has native audio). The
  `generate_audio` toggle is kept; verify behavior when 2.5 is live.
- **Availability:** enterprise beta now, public launch early July 2026 —
  **not yet on AnyFast**, so all of the below is unverifiable against the API today.

Sources: the-decoder.com, explainx.ai, digitalapplied.com (Seedance 2.5 launch coverage).

### AnyFast official docs check (docs.anyfast.ai, 2026-06-23)
- **2.5 status:** the AnyFast docs index (`docs.anyfast.ai/llms.txt`) states
  *"Seedance 2.5 … Coming soon to Anyfast."* → confirms the `model_not_found` on
  `seedance-2.5*` is expected; the model is simply not enabled yet.
- **Model-ID convention:** AnyFast's `seedance-2.0` API reference uses the dotted
  id `seedance-2.0` (its schema enum lists only that one id — no separate Standard/
  Fast/Ultra ids). So `seedance-2.5` here matches the convention, but `seedance-2.5-pro`
  is speculative (a 2.5 "Pro" tier may not exist).
- **2.0 resolutions per AnyFast schema:** `480p / 720p / 1080p / 4k` (default 720p),
  duration 4–15s default 5. NOTE: the plugin's 2.0 nodes currently expose `2k`
  (works via Direct channel) and do NOT list `4k` — a separate 2.0 accuracy gap,
  left unchanged here to avoid altering working 2.0 workflows without sign-off.

### Placeholders / things to confirm when AnyFast ships 2.5
- **Model IDs** `seedance-2.5` / `seedance-2.5-pro` — ByteDance/AnyFast have not
  published real IDs; the Pro/tier structure is unconfirmed (may be `-ultra`, or
  not exist as a separate model — AnyFast's 2.0 schema has a single id).
- **Resolution lists** `RES_V25` (mirrors 2.0) and `RES_V25_PRO` (adds `4k`) —
  confirm exact supported tiers; remove `4k` if 2.5 does not actually support it.
- **`MAX_DURATION_V25 = 30`** — confirm 30 is the real cap and the min (assumed 4).

### Known gaps (not changed — would need UI work)
- 50-reference support: `SeedanceRefImages` and `SeedanceFaceRef` expose 9 image
  slots. `SeedanceFaceRef` can be chained via `existing_refs` and reused groups,
  but reaching 50 refs cleanly would need a redesigned collector node.
- `SeedanceExtend` does not list the 2.5 model IDs and is capped at 15s; left as-is
  since 2.5's 30s single-pass output reduces the need for extend, and 2.5 extend
  support is undocumented.

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

### Friendly `model_not_found` error for 2.5
Running a 2.5 node before AnyFast ships the model returns
`503 model_not_found / "No available channel for model seedance-2.5-pro"`.
`_submit_and_poll` now detects this and, for `seedance-2.5*` models, raises a
clear "2.5 not generally available yet — use 2.0 / update the model ID" message
instead of the raw 503. **Confirmed via live test: the full 2.5 pipeline (asset
upload, GroupType resolve, 30s prompt, 4k payload) works end to end; only the
model itself is missing on AnyFast until ~early July 2026.**

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

### b) Configurable timeout — NOT CHANGED (documented)
`_poll_v2(..., timeout=1200)` is hardcoded and not exposed on the nodes.
Recommendation: add an optional `timeout_seconds` input (default 1200, allow up
to ~2400 for 2.5, which may take longer at higher res / longer duration) and
thread it through `_submit_and_poll` → `_poll_v2`. Left out for now to avoid an
unrequested change to the shared submit/poll path used by every node.

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
