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
| **Seedance — Create Human Asset** | Upload a portrait for real human video (with ID verification) |
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

ByteDance requires identity verification before generating videos with a real person's likeness. This is done once per person — after that you reuse a Group ID.

> **Rules:** One person per image. Group IDs are tied to the account that created them and cannot be shared across accounts.

### First time — getting verified

**Step 1.** Build this workflow and run it:

```
[Load Image]  ←  portrait photo (one person, clear face)
     |
[Seedance — Create Human Asset]
  existing_group_id = (leave empty)
```

**Step 2.** The node shows a verification link in its preview area:

```
⚠  VERIFICATION REQUIRED
1. Copy the link below and open it on your phone:
   https://verify.seedance.ai/...
2. Complete the liveness check (under 30 seconds).
3. Save your Group ID for future uploads:
   grp_abc123xyz
4. After verifying, use the asset_id output for generation:
   Asset://def456
```

**Step 3.** Open the link, complete the camera check, done.

**Step 4.** Copy and save the **Group ID** shown in the node — you'll need it next time.

### Generate the video

After verification, connect the `asset_id` output to **Reference Images**:

```
[Create Human Asset]
       | asset_id
       ▼
[Reference Images (9 slots)]
       | reference_images
       ▼
[Seedance 2.0 — Standard]
  prompt = "A person walking in a park @image1"
       | video_url
       ▼
[Save Video]
```

### Next time — same person, no re-verification

Paste the saved Group ID into `existing_group_id`. The node skips verification and gives you a ready-to-use `asset_id` immediately.

```
[Load Image]  ←  new photo of the same person
     |
[Seedance — Create Human Asset]
  existing_group_id = "grp_abc123xyz"   ← paste here
     | asset_id
     ▼
[Reference Images] → [Seedance 2.0 — Standard]
```

### Two people in one video

Run **Create Human Asset** separately for each person (each with their own Group ID), then connect both `asset_id` outputs to different image slots in **Reference Images**:

```
[Person A asset_id] → image_1 ┐
[Person B asset_id] → image_2 ┤ [Reference Images]
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

---

## License

Apache 2.0 — © 2025 amortegui84
