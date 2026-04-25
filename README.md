# ComfyUI-Seedance

Generate AI videos with [ByteDance Seedance 2.0](https://seedance2.ai) directly inside ComfyUI. Supports text-to-video, image-to-video, multi-reference, audio sync, and real human video generation.

Works with **AnyFast** and **fal.ai** — pick your provider in the API Key node.

---

## Install

```bash
git clone https://github.com/amortegui84/comfyui-seedance ComfyUI/custom_nodes/comfyui-seedance
pip install -r ComfyUI/custom_nodes/comfyui-seedance/requirements.txt
```

Restart ComfyUI. opencv-python is required for the `first_frame` output — everything else works without it.

---

## Quick Start

1. Add a **Seedance — API Key** node
2. Paste your API key, choose your provider (`anyfast` or `fal.ai`)
3. Add a **Seedance 2.0 — Standard** node and connect the `api` output
4. Write a prompt and click Queue

That's it for text-to-video. Connect a `first_frame` image to switch to image-to-video.

---

## Providers

| | AnyFast | fal.ai |
|---|---|---|
| API key from | [anyfast.ai](https://www.anyfast.ai) | [fal.ai](https://fal.ai) |
| T2V / I2V / Reference | ✅ | ✅ |
| 1080p / 2K | ✅ | ⚠ 720p max |
| Real Human (ID verification) | ✅ | ❌ |
| Extend video | ✅ | ❌ |

---

## Nodes

| Node | What it does |
|---|---|
| **Seedance — API Key** | Enter your API key and choose provider |
| **Seedance 2.0 — Standard** | Generate video (T2V or I2V). Up to 1080p, 15 s |
| **Seedance 2.0 — Fast** | Same as Standard, faster |
| **Seedance 2.0 — Ultra** | Highest quality. Up to 2K |
| **Seedance — Extend Video** | Continue a generated video using its task_id |
| **Seedance — Reference Images (9 slots)** | Pass up to 9 reference images to a generation node |
| **Seedance — Create Human Asset** | Upload a portrait for real human video. Shows a **clickable verification link** in the node on first use. Outputs `asset_id`, `group_id`, `verify_url` |
| **Seedance — Human Asset Panel** | Shows `asset_id`, `group_id`, and `verify_url` together in one centered panel and passes them through |
| **Seedance — Upload Asset** | Upload a video or audio file as a reference |
| **Seedance — Reference Video** | Pick a video from your input folder and upload it |
| **Seedance — Reference Audio** | Pick an audio from your input folder and upload it |
| **Seedance — Save Video** | Download and save the generated video |
| **Seedance — Show Text** | Display any text value (URL, ID) directly in the node |

---

## How to Use

### Text to Video
Connect: `API Key` → `Seedance 2.0 — Standard` → `Save Video`

Write your prompt and run. Leave all optional inputs disconnected.

### Image to Video
Connect a `Load Image` node to the `first_frame` input. Optionally connect a second image to `last_frame` to control how the video ends.

### Style / Character Reference (up to 9 images)
Connect images to **Reference Images (9 slots)**, then connect its output to the `reference_images` input of the generation node. Mention the images in your prompt using `@image1`, `@image2`, etc.

### With Reference Audio or Video
Use **Reference Video** or **Reference Audio** nodes to upload files from your `input/` folder. Connect their outputs to `reference_video` / `reference_audio` on the generation node. Use `@video1` / `@audio1` in your prompt.

### Extend a Video
Wire the `task_id` output of any generation node into **Seedance — Extend Video**. Add a continuation prompt and pick a duration.

---

## Real Human Video (ID Verification)

ByteDance requires identity verification before generating videos with a real person's likeness. This is a one-time step per person — afterwards you reuse a Group ID.

> **Rules:** One person per image. Group IDs are tied to the account that created them and cannot be shared across accounts.

### First time — getting verified

**Step 1.** Connect a portrait to **Create Human Asset** and run it with `existing_group_id` empty.

**Step 2.** A red panel appears inside the node with a **clickable "Open Verification Link" button**. Click it (or open the URL on your phone) and complete the liveness check within 30 seconds.

**Step 3.** Copy and save the **`group_id` output** shown in the node — you'll need it for every future run.

If you want everything in one place, connect the three outputs to **Seedance — Human Asset Panel**. It shows the verification button, `asset_id`, and `group_id` in a single centered block.

### Generate the video

Connect `asset_id` directly to the `human_asset_id` input of any generation node — no extra nodes needed:

```
[Load Image]  ←  portrait photo
     |
[Create Human Asset]
     | asset_id ──────────────────────────────┐
     | group_id ← save this for next time     |
                                              ▼
                              [Seedance 2.0 — Standard]
                                human_asset_id = (asset_id)
                                prompt = "A young person walking @image1"
                                     | video_url
                                     ▼
                              [Save Video]
```

The `@image1` tag is added to your prompt automatically if you forget it.

> **Show Text nodes** — connect `asset_id` or `group_id` to a **Seedance — Show Text** node to read and copy the values easily inside the graph.
>
> **Human Asset Panel** — use this when you want `asset_id`, `group_id`, and `verify_url` centralized in one dedicated node instead of separate text previews.

### Next time — same person, no re-verification

Paste the saved Group ID into `existing_group_id`. The node skips verification and returns a ready-to-use `asset_id` immediately.

```
[Load Image]  ←  any photo of the same person
     |
[Create Human Asset]
  existing_group_id = "grp_abc123xyz"   ← paste here
     | asset_id
     ▼ (connect to human_asset_id on the generation node)
```

### Two people in one video

Run **Create Human Asset** for each person, then connect both `asset_id` outputs to the generation node:

```
[Person A — Create Human Asset]  asset_id → human_asset_id ┐
[Person B — Create Human Asset]  asset_id → Reference Images (image_1)
                                                            ↓
                                             [Seedance 2.0 — Standard]
                                              prompt = "@image1 and @image2 together"
```

---

## Key Parameters

| Parameter | What it does |
|---|---|
| `prompt` | Describe the scene. Use `@image1`…`@image9`, `@video1`, `@audio1` to reference assets |
| `resolution` | 480p / 720p / 1080p (2K for Ultra) |
| `ratio` | 16:9, 9:16, 4:3, 3:4, 1:1, 21:9, adaptive |
| `duration` | 4–15 seconds |
| `generate_audio` | Auto-generate synced ambient audio |
| `seed` | -1 = random, any other value = reproducible |
| `first_frame` | Starting image → activates Image-to-Video |
| `last_frame` | Ending image → guides how the clip resolves |
| `human_asset_id` | Connect `asset_id` from **Create Human Asset** to generate ID-verified real human video (AnyFast only) |

---

## License

Apache 2.0 — © 2025 amortegui84
