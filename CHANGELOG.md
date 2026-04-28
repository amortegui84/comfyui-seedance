# Changelog

## 2026-04-28

### Fixed — Asset workflow now works end-to-end on AnyFast

**Root cause confirmed by AnyFast support (Hannah):** Assets have a processing period after `CreateAsset` and must reach `Active` status before being used in a generation request.

The `_wait_for_asset_active` polling function existed but had three bugs that made it silently fail:

**Bug 1 — Critical: wrong `GroupType` filter in `ListAssets`**
The code filtered `ListAssets` with `"GroupType": "AIGC"`. The `CreateAssetGroup` API has no `GroupType` field — groups are created without a type. This filter returned zero results on every poll, causing the function to time out (120 s) and raise an error instead of waiting for the asset.
- Fix: removed `GroupType` from the `ListAssets` filter.

**Bug 2 — Timeout too short**
The 120-second timeout was insufficient for AnyFast's asset processing period.
- Fix: timeout raised to 300 seconds.

**Bug 3 — `AssetType` missing in multipart upload path**
When uploading Video or Audio assets via multipart form-data, `AssetType` was not set in the request. The API defaults to `"Image"`, causing video and audio assets to be registered with the wrong type.
- Fix: `AssetType` is now always set explicitly in both JSON and multipart upload paths.

### Fixed — Incorrect `model` field for Video/Audio asset uploads

`CreateAsset` requires different model values per asset type (`volc-asset` for images, `volc-asset-video` for video, `volc-asset-audio` for audio). All uploads previously used `volc-asset`.
- Fix: added `model_map` mapping asset type to correct billing model.

### Fixed — Wrong `asset://` URL casing sent to generation endpoint

`CreateAsset` documentation example shows `Asset://` (capital A), but the Seedance 2.0 generation endpoint example shows `asset://` (lowercase). All asset URI references now use lowercase `asset://` to match the generation endpoint spec.

### Fixed — `_is_anyfast_asset_not_ready_error` did not match actual error

The retry guard in `_submit_and_poll` checked for `"fail_to_fetch_task"` and `"invalidparameter"`, but the actual generation error is `"The specified asset <id> is not found"`. The retry never triggered.
- Fix: added a second pattern — `"specified asset" in text and "not found" in text`.

### Fixed — `fail_reason` not extracted on generation failure

When a Seedance task fails, the actual error text is in `body.data.fail_reason`. The error reporting code looked for `"error"` and `"message"` keys, which do not exist at that level. Failure messages were reported as the raw response dict.
- Fix: `_poll_v2` now checks `fail_reason` / `failReason` first, then falls back to generic keys.

### Fixed — `2K` resolution sent as `"2K"` instead of `"2k"`

The `seedance-2.0-ultra` API spec uses lowercase `"2k"`. The dropdown value was `"2K"` (uppercase), which would be rejected by the API's enum validation.
- Fix: `RES_V2_ULTRA` updated to `["2k", "1080p", "720p"]`.

### Fixed — ID field extraction order

`CreateAssetGroup` and `CreateAsset` responses both return the ID in a field named `Id` (capital I). The `_extract_id` calls now try `"Id"` as the first candidate before generic fallbacks, avoiding unnecessary canonical lookups.

### Fixed — Improved logging in `_wait_for_asset_active`

The polling loop now prints:
- When waiting starts (with timeout)
- When the group has no assets yet
- When the target asset is not in the list yet (with count of other assets)
- When the asset is found with its current status

### Updated — README

- Removed outdated warnings about asset `first_frame` being broken
- Corrected `"2K"` → `"2k"` in parameter documentation
- Fixed `reference_images` incorrectly described as "fal.ai only"
- Clarified `@image` / `@video` / `@audio` tags are auto-appended (no manual step needed)
- Clarified `first_frame` / `last_frame` roles do not use `@image` tags
- Updated AnyFast Notes to reflect asset workflow status
- Added clear flow diagrams for reference image options A and B
