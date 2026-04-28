# Seedance Node Implementation Report

Date: 2026-04-28

## Scope

This report captures the work completed on the `comfyui-seedance` node during the AnyFast asset workflow stabilization pass, the current repository state, and the implementation guidance that should remain true for future work.

## Main outcomes

1. The repository was synchronized to GitHub without uploading local sensitive notes or unrelated image files.
2. The AnyFast asset workflow was corrected around asset readiness and generation compatibility.
3. The node now handles `ReadTimeout` on generation submit more safely.
4. The public documentation and workflow inventory were reviewed against:
   - actual node behavior
   - direct testing results
   - the support response from Hannah at AnyFast

## Repository synchronization

The local branch had two commits ahead of `origin/main` and they were pushed successfully.

Commits that were published:

- `444a2e9` `Fix asset workflow: wait for Active status, correct API field names and casing`
- `946ea80` `Add SKILL_VIDEO_API_EXPERT.md — expert reference for video API integrations`

Files intentionally kept out of the repository:

- `ANYFAST_TEST2_REPORT.txt`
- `example_id.png`
- `nodos.png`
- `opciones.png`

## AnyFast asset workflow: what was wrong

The main production issue was this failure pattern during generation:

- asset creation succeeded
- the returned asset ID existed
- generation then failed with an asset-not-found error or behaved inconsistently

The root cause confirmed through testing and AnyFast support was asset readiness, not basic authentication or submit/poll wiring.

## What was implemented

### 1. Asset lifecycle hardening

The node now follows the practical AnyFast lifecycle:

1. `CreateAssetGroup`
2. `CreateAsset`
3. `ListAssets` poll until the target asset is `Active`
4. only then use the asset in generation

Implementation details already present in the node:

- asset IDs are normalized to lowercase `asset://...`
- `AssetType` is sent explicitly during asset upload
- `ListAssets` is polled without `GroupType`
- reusable `group_id` support is exposed through `existing_group_id`

Relevant code paths:

- `nodes.py` `_ensure_group()`
- `nodes.py` `_upload_asset()`
- `nodes.py` `_wait_for_asset_active()`
- `nodes.py` `SeedanceAssetRef`
- `nodes.py` `SeedanceUploadAsset`

### 2. AnyFast support confirmation

The support response from Hannah confirmed:

- assets are supported for `first_frame`
- there is a waiting period after asset creation
- `ListAssets` should be used to verify `Active` status

This matches the current asset-based AnyFast workflow in the node.

### 3. Safer ReadTimeout handling

The generation submit path in `_submit_and_poll()` was updated so that:

- `ReadTimeout` on `POST /v1/video/generations` is caught explicitly
- the node raises a clear `RuntimeError`
- the node does not auto-resubmit after a submit timeout

Why this matters:

- if AnyFast accepted the job but did not return the `task_id` in time, an automatic retry could create duplicate jobs
- the safer behavior is to stop and tell the user to check AnyFast job history before retrying

Current behavior:

- generic transient network errors still retry
- submit `ReadTimeout` does not retry automatically

## Documentation review

### What is aligned

- README correctly explains that AnyFast `first_frame` should use assets through `anyfast_refs`
- README correctly documents reference video/audio upload flows
- README explains that `anyfast_refs` overrides direct image inputs on AnyFast
- the advanced reference file `SKILL_VIDEO_API_EXPERT.md` is largely aligned with current findings

### What was still inconsistent

The repo still contained older workflow language implying that base64-first-frame on AnyFast was a normal path.

This was cleaned up by:

- marking `workflows/anyfast/03_first_frame.json` as legacy/experimental
- marking `workflows/anyfast/11_anyfast_asset_first_frame.json` as the recommended first-frame path
- updating the README workflow table accordingly

## Workflow review summary

### AnyFast workflows

- `01_t2v.json`
  - Good baseline text-to-video workflow.
- `03_first_frame.json`
  - Uses `SeedanceAnyfastImageUpload` and base64 refs.
  - Keep only as legacy/experimental.
  - Do not present as the recommended first-frame workflow.
- `04_reference_images.json`
  - Still valid for image references.
  - Uses base64 reference-image flow, not asset persistence.
- `09_anyfast_save_to_input_for_vhs.json`
  - Fine as a save/output integration workflow.
- `10_anyfast_video_audio_refs.json`
  - Valid asset-backed media reference workflow.
- `11_anyfast_asset_first_frame.json`
  - This should remain the canonical first-frame AnyFast workflow.

### fal.ai workflows

- `01_t2v.json`
  - Good.
- `05_image_to_video.json`
  - Good. fal.ai supports direct `first_frame`.
- `06_reference_images.json`
  - Good. fal.ai accepts direct tensor reference images.

### test workflows

- `test_01_t2v.json`
  - Baseline API sanity check.
- `test_02_asset_first_frame.json`
  - Useful to verify the officially supported asset path.
- `test_03_base64_refs.json`
  - Useful only as a diagnostic comparison workflow, not as a recommended production path.

## Known current behavior

### AnyFast

- Recommended `first_frame` path: asset upload + `asset://` + `Active` wait
- Reference images can still be sent inline as base64
- `anyfast_refs` overrides direct `first_frame`, `last_frame`, and `reference_images`
- submit timeout may still happen if AnyFast stalls before returning the task ID

### fal.ai

- direct `first_frame` tensor path remains correct
- direct reference image tensor path remains correct
- `anyfast_refs` is not applicable

## Open risks and follow-up suggestions

1. Decide whether AnyFast inline base64 `first_frame` support should remain in code at all.
2. If the base64 path stays, keep it clearly documented as legacy/experimental.
3. Consider adding `.gitignore` rules for local reports and screenshots if they continue appearing.
4. If AnyFast exposes idempotency or a task-query-by-request feature later, the timeout strategy can be improved further.

## Recommended next implementation priorities

1. Commit the local `ReadTimeout` fix in `nodes.py`.
2. Keep `11_anyfast_asset_first_frame.json` as the primary documented AnyFast I2V workflow.
3. Optionally reduce ambiguity in code by de-emphasizing or removing direct AnyFast `first_frame` base64 fallback.
4. Add a short troubleshooting section to README for:
   - asset not found
   - asset not `Active`
   - submit timeout after 600 seconds
