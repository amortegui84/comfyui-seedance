---
name: seedance-node-maintainer
description: Use when maintaining or extending this ComfyUI Seedance node, especially for AnyFast and fal.ai generation flows, asset lifecycle bugs, workflow alignment, provider-specific behavior, or documentation consistency. Focus on preserving the current production assumptions around AnyFast assets, `anyfast_refs`, and submit/poll error handling.
---

# Seedance Node Maintainer

Use this skill when working on `comfyui-seedance`.

## Core rules

1. Inspect `nodes.py`, `README.md`, and `workflows/` before changing behavior.
2. Treat AnyFast and fal.ai as different providers with different image-input rules.
3. Do not assume a provider feature works just because the public docs imply it does. Prefer tested behavior plus support confirmations.
4. Preserve safe failure behavior over aggressive retries when the API may have already accepted a job.

## Current provider model

### AnyFast

- Text-to-video works through `POST /v1/video/generations`.
- Recommended image-to-video path for `first_frame` is asset-based:
  1. create group
  2. create asset
  3. poll `ListAssets` until `Status == Active`
  4. generate using `asset://...`
- `anyfast_refs` is the structured input path for AnyFast image roles.
- When `anyfast_refs` is connected, direct `first_frame`, `last_frame`, and `reference_images` inputs are ignored.
- `asset://` should be lowercase.
- `ListAssets` should be polled without `GroupType` in this implementation.
- `AssetType` must be explicit for uploads.
- `existing_group_id` should be reused where practical.

### fal.ai

- Direct tensor `first_frame` is supported.
- Direct tensor `reference_images` is supported.
- `anyfast_refs` does not apply.

## Timeouts and retries

- `_submit_and_poll()` is the critical AnyFast submit path.
- If `POST /v1/video/generations` raises `ReadTimeout` after 600s:
  - fail with a clear message
  - do not auto-resubmit
  - tell the user to check AnyFast job history before retrying
- Rationale: the server may have accepted the job but not returned `task_id` in time; auto-retry risks duplicate generations.

## Workflow truth table

- `workflows/anyfast/11_anyfast_asset_first_frame.json`
  - canonical AnyFast first-frame workflow
- `workflows/anyfast/03_first_frame.json`
  - legacy/experimental base64-first-frame path
- `workflows/anyfast/04_reference_images.json`
  - acceptable AnyFast base64 reference-image workflow
- `workflows/test/test_02_asset_first_frame.json`
  - diagnostic for official AnyFast asset-first-frame path
- `workflows/test/test_03_base64_refs.json`
  - diagnostic comparison only, not the preferred production path

## Files to check first

- `nodes.py`
  - `_submit_and_poll()`
  - `_upload_asset()`
  - `_wait_for_asset_active()`
  - `SeedanceAnyfastImageUpload`
  - `SeedanceAssetRef`
  - `SeedanceUploadAsset`
  - `_V2Base.generate()`
- `README.md`
- `SKILL_VIDEO_API_EXPERT.md`
- `workflows/anyfast/*.json`
- `workflows/fal/*.json`
- `workflows/test/*.json`

## Editing guidance

### If changing AnyFast asset behavior

- keep the asset lifecycle explicit
- preserve lowercase `asset://`
- do not add `GroupType` back into `ListAssets` polling without proof it works
- keep `AssetType` explicit for all upload modes

### If changing image input behavior

- document whether the path is:
  - recommended production
  - valid but secondary
  - diagnostic only
- keep README and workflow note text aligned with actual code behavior

### If changing retries

- distinguish:
  - pre-submit or generic network failures
  - post-submit ambiguity like `ReadTimeout`
- never add submit auto-retries for ambiguous job-creation states unless the upstream API provides idempotency or a guaranteed recovery mechanism

## Common failure interpretations

- `"The specified asset ... is not found"`
  - usually asset not yet `Active`, wrong URI casing, or bad asset visibility timing
- `ListAssets` returns empty items repeatedly
  - likely filter mismatch or propagation timing
- `ReadTimeout` on `POST /v1/video/generations`
  - AnyFast stalled before returning the task ID; job may or may not already exist

## Validation checklist

After changing this repo:

1. Run `python -m py_compile nodes.py`.
2. Re-check README workflow descriptions against actual node behavior.
3. Re-check at least these workflows:
   - `anyfast/03_first_frame.json`
   - `anyfast/11_anyfast_asset_first_frame.json`
   - `test/test_02_asset_first_frame.json`
   - `test/test_03_base64_refs.json`
4. Confirm sensitive local reports or screenshots are not added to git.
