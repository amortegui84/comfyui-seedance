"""Offline checks for the Seedance nodes.

Builds the request payloads and asserts on them without ever calling AnyFast, so
this costs nothing to run. Covers per-model limits, the 2.0 -> 2.5 differences,
that the deprecated nodes still behave exactly as they used to, and that
web/js/model_variants.js has not drifted from MODEL_SPECS in nodes.py.

    python test_nodes.py

Exits non-zero if anything fails.
"""
import sys, types, json, os, tempfile, shutil, atexit
import numpy as np

# Windows consoles default to cp1252, which cannot encode the arrows and dashes
# in these messages — without this the suite dies with UnicodeEncodeError instead
# of reporting results.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

# --- stub ComfyUI's folder_paths so nodes.py imports outside ComfyUI ---
# get_user_directory points at a scratch dir so the test never reads or writes
# the real asset cache / identity store.
_SCRATCH = tempfile.mkdtemp(prefix="seedance_test_")
atexit.register(shutil.rmtree, _SCRATCH, True)
fp = types.ModuleType("folder_paths")
fp.get_input_directory = lambda: os.getcwd()
fp.get_output_directory = lambda: os.getcwd()
fp.get_user_directory = lambda: _SCRATCH
sys.modules["folder_paths"] = fp

REPO = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REPO)
import nodes

API = {"api_key": "sk-test", "provider": "anyfast", "base_url": "https://www.anyfast.ai"}

captured = {}
def fake_submit(api, payload, poll_timeout=1200):
    captured["payload"] = payload
    captured["poll_timeout"] = poll_timeout
    return ("https://example/v.mp4", "task-1", None)
nodes._submit_and_poll = fake_submit

RES_ALL_EXPECTED = ["720p", "1080p", "480p", "2k"]
PASS, FAIL = [], []
def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  ok   " if cond else "  FAIL ") + name + (f"  -> {detail}" if detail and not cond else ""))

def run(node, **kw):
    base = dict(api=API, prompt="a cat", resolution="720p", ratio="16:9",
                duration=10, generate_audio=True, watermark=False, seed=-1)
    base.update(kw)
    return node.generate(**base)

def expect_error(node, fragment, **kw):
    try:
        run(node, **kw)
    except ValueError as e:
        return fragment.lower() in str(e).lower(), str(e)
    return False, "no error raised"

print("\n=== node registry ===")
check("SeedanceV25Pro is gone", "SeedanceV25Pro" not in nodes.NODE_CLASS_MAPPINGS)
check("legacy key SeedanceV25Standard still loads",
      nodes.NODE_CLASS_MAPPINGS.get("SeedanceV25Standard") is nodes.SeedanceV25)
check("no RES_V25_PRO constant left", not hasattr(nodes, "RES_V25_PRO"))

print("\n=== 2.5 widget schema ===")
it = nodes.SeedanceV25.INPUT_TYPES()
res_enum = it["required"]["resolution"][0]
dur_opts = it["required"]["duration"][1]
check("resolutions are 720p/480p only", res_enum == ["720p", "480p"], res_enum)
check("duration min is -1", dur_opts["min"] == -1, dur_opts)
check("duration max is 30", dur_opts["max"] == 30, dur_opts)
check("web_search widget present", "web_search" in it["optional"])
check("2.0 schema untouched: min 4 / max 15",
      nodes.Seedance2.INPUT_TYPES()["required"]["duration"][1]["min"] == 4 and
      nodes.Seedance2.INPUT_TYPES()["required"]["duration"][1]["max"] == 15)
check("2.0 has no web_search widget", "web_search" not in nodes.Seedance2.INPUT_TYPES()["optional"])

print("\n=== 2.5 payloads ===")
v25 = nodes.SeedanceV25()
run(v25)
p = captured["payload"]
check("model id is seedance-2.5", p["model"] == "seedance-2.5", p["model"])
check("poll timeout raised to 2400", captured["poll_timeout"] == 2400, captured["poll_timeout"])
check("no tools key when web_search off", "tools" not in p)

run(v25, web_search=True)
check("web_search adds tools", captured["payload"].get("tools") == [{"type": "web_search"}],
      captured["payload"].get("tools"))

run(v25, duration=-1)
check("duration -1 accepted on 2.5", captured["payload"]["duration"] == -1)

run(v25, reference_audio="https://x/a.mp3")
p = captured["payload"]
audio_items = [c for c in p["content"] if c["type"] == "audio_url"]
check("2.5 audio-only allowed", len(audio_items) == 1)
check("@audio1 auto-tagged", "@audio1" in p["content"][0]["text"], p["content"][0]["text"])

run(v25, reference_video="https://x/1.mp4\nhttps://x/2.mp4\nhttps://x/3.mp4")
p = captured["payload"]
vids = [c for c in p["content"] if c["type"] == "video_url"]
check("3 videos from one multiline socket", len(vids) == 3, len(vids))
txt = p["content"][0]["text"]
check("@video1..@video3 tagged", all(f"@video{i}" in txt for i in (1, 2, 3)), txt)

print("\n=== 2.5 limits ===")
ok, msg = expect_error(v25, "at most 10 video",
                       reference_video="\n".join(f"https://x/{i}.mp4" for i in range(11)))
check("rejects 11 videos", ok, msg)
ok, msg = expect_error(v25, "at most 30 image", reference_images=[object()] * 31)
check("rejects 31 images", ok, msg)
ok, msg = expect_error(v25, "between 4 and 30", duration=2)
check("rejects duration 2", ok, msg)

print("\n=== 2.0 regressions ===")
v2 = nodes.Seedance2()
run(v2, prompt="a cat", resolution="720p", duration=5)
p = captured["payload"]
check("2.0 model id unchanged", p["model"] == "seedance", p["model"])
check("2.0 poll timeout still 1200", captured["poll_timeout"] == 1200, captured["poll_timeout"])
check("2.0 payload has no tools", "tools" not in p)

ok, msg = expect_error(v2, "requires at least one image", duration=5,
                       reference_audio="https://x/a.mp3")
check("2.0 still rejects audio-only", ok, msg)
ok, msg = expect_error(v2, "only supported by Seedance 2.5", duration=-1)
check("2.0 rejects duration -1", ok, msg)
ok, msg = expect_error(v2, "at most 3 video", duration=5,
                       reference_video="\n".join(f"https://x/{i}.mp4" for i in range(4)))
check("2.0 rejects 4 videos", ok, msg)
ok, msg = expect_error(v2, "Cannot mix", duration=5,
                       first_frame="IMG", reference_video="https://x/1.mp4")
check("I2V/R2V mixing guard intact", ok, msg)

# single-URL behaviour must be byte-identical to before the multiline change
one_ref = [{"type": "image_url", "image_url": {"url": "asset://a1"}, "role": "reference_image"}]
run(v2, duration=5, anyfast_refs=one_ref, reference_video="  https://x/1.mp4  ")
vids = [c for c in captured["payload"]["content"] if c["type"] == "video_url"]
check("single URL still trimmed to one entry",
      len(vids) == 1 and vids[0]["video_url"]["url"] == "https://x/1.mp4", vids)

print("\n=== RefImages chaining ===")
col = nodes.SeedanceRefImages()
first, = col.collect(image_1="A", image_2="B")
second, = col.collect(image_1="C", existing_images=first)
check("chained collector accumulates in order", second == ["A", "B", "C"], second)
plain, = col.collect(image_1="A")
check("unchained collector unchanged", plain == ["A"], plain)

print("\n=== unified SeedanceVideo node ===")
uni = nodes.SeedanceVideo()
uit = uni.INPUT_TYPES()
req_order = list(uit["required"].keys())
check("api is still the first input", req_order[0] == "api", req_order)
check("model is the second input", req_order[1] == "model", req_order)
check("model list covers all 5 live models",
      uit["required"]["model"][0] == ["seedance-2.0", "seedance-2.0-fast", "seedance-2.0-mini",
                                      "seedance-2.0-ultra", "seedance-2.5"],
      uit["required"]["model"][0])
check("resolution is the union, 720p first", uit["required"]["resolution"][0] == RES_ALL_EXPECTED,
      uit["required"]["resolution"][0])

run(uni, model="seedance-2.5", resolution="480p", duration=30)
check("2.5 via dropdown", captured["payload"]["model"] == "seedance-2.5" and
      captured["poll_timeout"] == 2400)
run(uni, model="seedance-2.0-ultra", resolution="2k", duration=15)
check("ultra via dropdown", captured["payload"]["model"] == "seedance-2.0-ultra" and
      captured["poll_timeout"] == 1200)
run(uni, model="seedance-2.0-mini", resolution="1080p", duration=5)
check("mini is now reachable", captured["payload"]["model"] == "seedance-2.0-mini")

ok, msg = expect_error(uni, "does not support 1080p", model="seedance-2.5", resolution="1080p")
check("rejects 1080p on 2.5", ok, msg)
ok, msg = expect_error(uni, "does not support 480p", model="seedance-2.0-ultra", resolution="480p")
check("rejects 480p on ultra", ok, msg)
ok, msg = expect_error(uni, "between 4 and 15", model="seedance-2.0", resolution="720p", duration=30)
check("rejects 30s on 2.0", ok, msg)
ok, msg = expect_error(uni, "only supported by Seedance 2.5", model="seedance-2.0",
                       resolution="720p", duration=-1)
check("rejects -1 on 2.0 via dropdown", ok, msg)
ok, msg = expect_error(uni, "Unknown model", model="seedance-9.9", resolution="720p", duration=5)
check("rejects unknown model id", ok, msg)
ok, msg = expect_error(uni, "at most 3 audio", model="seedance-2.0", resolution="720p", duration=5,
                       reference_video="https://x/v.mp4",
                       reference_audio="\n".join(f"https://x/{i}.mp3" for i in range(4)))
check("per-model audio cap follows the dropdown", ok, msg)
run(uni, model="seedance-2.5", resolution="720p", duration=10, reference_audio="https://x/a.mp3")
check("2.5 audio-only works via dropdown",
      len([c for c in captured["payload"]["content"] if c["type"] == "audio_url"]) == 1)

print("\n=== legacy nodes still registered & unchanged ===")
for key, model_id in (("Seedance2", "seedance"), ("Seedance2Fast", "seedance-fast"),
                      ("Seedance2Ultra", "seedance-2.0-ultra"), ("SeedanceV25Standard", "seedance-2.5")):
    cls = nodes.NODE_CLASS_MAPPINGS.get(key)
    check(f"{key} registered", cls is not None)
    check(f"{key} marked DEPRECATED", getattr(cls, "DEPRECATED", False) is True)
    check(f"{key} keeps model id {model_id}", cls.MODEL_ID == model_id, getattr(cls, "MODEL_ID", None))
    check(f"{key} has a display name", key in nodes.NODE_DISPLAY_NAME_MAPPINGS)

check("SeedanceMuxAudio kept (covers arbitrary audio, not just reference audio)",
      "SeedanceMuxAudio" in nodes.NODE_CLASS_MAPPINGS)

# The unified node must produce byte-identical requests to the legacy nodes it
# replaces — that is what makes swapping them safe. (2.0 legacy uses the older
# `seedance` alias, so compare against the 2.5 node, whose id is unchanged.)
print("\n=== unified vs legacy payload equality ===")
args = dict(prompt="a cat @image1", resolution="720p", ratio="adaptive", duration=25,
            generate_audio=True, watermark=True, seed=42,
            anyfast_refs=[{"type": "image_url", "image_url": {"url": "asset://a1"},
                           "role": "reference_image"}],
            reference_audio="https://x/a.mp3\nhttps://x/b.mp3")
run(nodes.SeedanceV25(), **args)
legacy_payload, legacy_timeout = captured["payload"], captured["poll_timeout"]
run(uni, model="seedance-2.5", **args)
check("identical payload", captured["payload"] == legacy_payload,
      f"\n  legacy={legacy_payload}\n  new   ={captured['payload']}")
check("identical poll timeout", captured["poll_timeout"] == legacy_timeout)

# The JS mirror of MODEL_SPECS must not drift from Python.
import re as _re
js = open(os.path.join(REPO, "web", "js", "model_variants.js"), encoding="utf-8").read()
js_models = set(_re.findall(r'"(seedance-[\d.]+[a-z-]*)":\s*\{', js))
check("model_variants.js lists exactly the Python models",
      js_models == set(nodes.MODEL_SPECS), f"js={sorted(js_models)} py={sorted(nodes.MODEL_SPECS)}")
for mid, spec in nodes.MODEL_SPECS.items():
    block = _re.search(r'"%s":\s*\{([^}]*)\}' % _re.escape(mid), js).group(1)
    js_res = _re.findall(r'"(\d+p|2k|4k)"', block)
    js_max = int(_re.search(r"durationMax:\s*(\d+)", block).group(1))
    js_min = int(_re.search(r"durationMin:\s*(-?\d+)", block).group(1))
    check(f"js spec matches python for {mid}",
          js_res == spec["resolutions"] and js_max == spec["duration_max"]
          and js_min == spec["duration_min"],
          f"js={js_res}/{js_min}-{js_max} py={spec['resolutions']}/{spec['duration_min']}-{spec['duration_max']}")

print("\n=== mixing asset refs with plain image refs ===")


class _RealTensor:
    """Minimal stand-in for a torch IMAGE tensor that _tensor_to_b64 accepts."""
    def __init__(self, seed):
        self._arr = np.random.default_rng(seed).random((8, 8, 3))

    def __getitem__(self, _idx):
        return self

    def numpy(self):
        return self._arr


_face = [{"type": "image_url", "image_url": {"url": "asset://face1"}, "role": "reference_image"}]
run(v25, prompt="a scene", anyfast_refs=_face, reference_images=[_RealTensor(7), _RealTensor(8)])
_p = captured["payload"]
_imgs = [c for c in _p["content"] if c["type"] == "image_url"]
check("asset ref survives the mix", any(c["image_url"]["url"] == "asset://face1" for c in _imgs))
check("plain image refs are no longer dropped", len(_imgs) == 3, len(_imgs))
check("asset entries come first", _imgs[0]["image_url"]["url"] == "asset://face1", _imgs[0])
check("plain refs are sent as base64",
      all(c["image_url"]["url"].startswith("data:") for c in _imgs[1:]), _imgs[1:])
_txt = _p["content"][0]["text"]
check("@image1..@image3 span both sources",
      all(f"@image{i}" in _txt for i in (1, 2, 3)) and "@image4" not in _txt, _txt)

# The combined count is what gets checked against the model's cap.
_many = [_RealTensor(i) for i in range(30)]
ok, msg = expect_error(v25, "at most 30 image", anyfast_refs=_face, reference_images=_many)
check("combined count enforces the per-model cap", ok, msg)

# Frame control still cannot be mixed with references, from either door.
_ff = [{"type": "image_url", "image_url": {"url": "asset://f1"}, "role": "first_frame"}]
ok, msg = expect_error(v25, "cannot be combined", anyfast_refs=_ff,
                       reference_images=[_RealTensor(1)])
check("asset first_frame + plain refs is rejected, not silently merged", ok, msg)

# Plain refs alone must behave exactly as before.
run(v25, prompt="a scene", reference_images=[_RealTensor(7)])
_imgs = [c for c in captured["payload"]["content"] if c["type"] == "image_url"]
check("plain refs alone unchanged", len(_imgs) == 1 and _imgs[0]["role"] == "reference_image", _imgs)

print("\n=== widget order (saved-workflow compatibility) ===")
# ComfyUI serialises widget values as a POSITIONAL array. Inserting a widget
# anywhere but the end shifts every saved workflow's values by one — which is
# how `identity` briefly landed on top of `force_reupload`. These golden lists
# freeze the order: if you need a new widget, append it and update the list.
WIDGET_TYPES = {"INT", "FLOAT", "STRING", "BOOLEAN"}


def widget_order(cls):
    """Widget names in the order ComfyUI will serialise them."""
    spec = cls.INPUT_TYPES()
    names = []
    for section in ("required", "optional"):
        for name, definition in (spec.get(section) or {}).items():
            kind = definition[0] if isinstance(definition, (tuple, list)) else definition
            config = definition[1] if isinstance(definition, (tuple, list)) and len(definition) > 1 else {}
            if isinstance(kind, list):
                names.append(name)                      # combo
            elif kind in WIDGET_TYPES and not config.get("forceInput"):
                names.append(name)
    return names


GOLDEN_WIDGETS = {
    "SeedanceApiKey":  ["api_key", "base_url"],
    "SeedanceVideo":   ["model", "prompt", "resolution", "ratio", "duration",
                        "generate_audio", "watermark", "seed", "web_search"],
    "Seedance2":       ["prompt", "resolution", "ratio", "duration",
                        "generate_audio", "watermark", "seed"],
    "SeedanceV25Standard": ["prompt", "resolution", "ratio", "duration",
                            "generate_audio", "watermark", "seed", "web_search"],
    # group_name first, then force_reupload — identity MUST stay last so the two
    # pre-identity widgets keep their historical positions.
    "SeedanceFaceRef": ["group_name", "force_reupload", "identity"],
    "SeedanceAssetRef": ["role"],
    "SeedanceIdentity": ["identity", "role", "limit"],
    "SeedanceSaveVideo": ["filename_prefix", "save_to"],
}
for node_key, expected in GOLDEN_WIDGETS.items():
    actual = widget_order(nodes.NODE_CLASS_MAPPINGS[node_key])
    check(f"{node_key} widget order unchanged", actual == expected,
          f"expected {expected}, got {actual}")

check("FaceRef: identity is the LAST widget (append-only rule)",
      widget_order(nodes.SeedanceFaceRef)[-1] == "identity",
      widget_order(nodes.SeedanceFaceRef))

# A workflow saved before `identity` existed has 2 widget values; ComfyUI leaves
# the new trailing widget at its default. Simulate the old call shape.
_probe = {"called": False}
try:
    nodes.SeedanceFaceRef().upload(api=API, group_name="g", first_frame=None)
except ValueError as e:
    _probe["called"] = "at least one image" in str(e)
check("pre-identity call signature still reaches the normal validation",
      _probe["called"], _probe)

print("\n=== identity store ===")
# Point the store at a scratch folder so the test never touches real identities.
import tempfile, shutil
_tmp_identities = tempfile.mkdtemp(prefix="seedance_ids_")
os.environ["SEEDANCE_IDENTITIES_DIR"] = _tmp_identities
try:
    check("store honours SEEDANCE_IDENTITIES_DIR",
          os.path.normcase(nodes._identities_dir()) == os.path.normcase(_tmp_identities),
          nodes._identities_dir())
    check("empty store lists nothing", nodes._list_identities() == [], nodes._list_identities())

    check("slug keeps names readable", nodes._identity_slug("Ana María") == "ana-maria",
          nodes._identity_slug("Ana María"))
    check("slug strips path separators",
          "/" not in nodes._identity_slug("a/b") and "\\" not in nodes._identity_slug("a\\b"),
          nodes._identity_slug("a/b"))
    check("slug never returns empty", nodes._identity_slug("///") == "unnamed",
          nodes._identity_slug("///"))

    nodes._record_identity_asset("my-subject", "asset://a1", "reference_image", "group-1", image_hash="h1")
    nodes._record_identity_asset("my-subject", "asset://a2", "reference_image", "group-1", image_hash="h2")
    rec = nodes._load_identity("my-subject")
    check("identity file created and reloads", rec is not None and rec["identity"] == "my-subject")
    check("both assets recorded", [a["asset_id"] for a in rec["assets"]] == ["asset://a1", "asset://a2"],
          rec["assets"])
    check("group_id stored on the record", rec["group_id"] == "group-1", rec.get("group_id"))
    check("identity appears in the dropdown list", nodes._list_identities() == ["my-subject"],
          nodes._list_identities())

    # Re-recording the same asset must update in place, not duplicate.
    nodes._record_identity_asset("my-subject", "asset://a1", "first_frame", "group-1", image_hash="h1")
    rec = nodes._load_identity("my-subject")
    check("re-recording does not duplicate", len(rec["assets"]) == 2, rec["assets"])
    check("re-recording updates the role",
          [a["role"] for a in rec["assets"] if a["asset_id"] == "asset://a1"] == ["first_frame"],
          rec["assets"])
    check("re-recording preserves order (@imageN stability)",
          [a["asset_id"] for a in rec["assets"]] == ["asset://a1", "asset://a2"], rec["assets"])
    # Put a1 back to reference_image so the checks below read naturally.
    nodes._record_identity_asset("my-subject", "asset://a1", "reference_image", "group-1", image_hash="h1")

    ident = nodes.SeedanceIdentity()
    refs, gid, ids = ident.load("my-subject", "reference_image")["result"]
    check("Identity node emits one ref per asset", len(refs) == 2, refs)
    check("Identity node applies the chosen role",
          all(r["role"] == "reference_image" for r in refs), refs)
    check("Identity node emits asset:// urls",
          [r["image_url"]["url"] for r in refs] == ["asset://a1", "asset://a2"], refs)
    check("Identity node returns the group", gid == "group-1", gid)

    refs_ff, _, _ = ident.load("my-subject", "first_frame")["result"]
    check("frame roles are inserted at the front",
          refs_ff[0]["role"] == "first_frame", refs_ff)

    chained, _, _ = ident.load("my-subject", "reference_image",
                               existing_refs=[{"type": "image_url",
                                               "image_url": {"url": "asset://z"},
                                               "role": "reference_image"}])["result"]
    check("Identity node chains existing_refs", len(chained) == 3, chained)

    limited, _, _ = ident.load("my-subject", "reference_image", limit=1)["result"]
    check("limit caps the number of refs", len(limited) == 1, limited)

    try:
        ident.load("nobody", "reference_image")
        check("unknown identity raises", False, "no error")
    except ValueError as e:
        check("unknown identity raises a helpful error",
              "nobody" in str(e) and _tmp_identities in str(e), str(e))

    # The refs an Identity node emits must be interchangeable with FaceRef's.
    run(v25, anyfast_refs=refs)
    imgs = [c for c in captured["payload"]["content"] if c["type"] == "image_url"]
    check("Identity refs feed a generation node unchanged",
          [c["image_url"]["url"] for c in imgs] == ["asset://a1", "asset://a2"], imgs)
    check("@image tags follow the identity's asset count",
          "@image1" in captured["payload"]["content"][0]["text"]
          and "@image2" in captured["payload"]["content"][0]["text"],
          captured["payload"]["content"][0]["text"])
finally:
    os.environ.pop("SEEDANCE_IDENTITIES_DIR", None)
    shutil.rmtree(_tmp_identities, ignore_errors=True)

print("\n=== FaceRef: lazy group creation ===")


class _FakeTensor:
    """Enough of a torch tensor for _image_asset_cache_key / _tensor_to_b64."""
    def __init__(self, seed):
        rng = np.random.default_rng(seed)
        self._arr = rng.random((8, 8, 3), dtype=np.float64)

    def __getitem__(self, _idx):
        return self

    def numpy(self):
        return self._arr


_face_calls = {"ensure_group": 0, "upload": 0}
_real_ensure_group = nodes._ensure_group
_real_upload_asset = nodes._upload_asset
_real_wait = nodes._wait_for_asset_active
_real_settle = nodes._stabilize_anyfast_asset


def _fake_ensure_group(api, group_name, existing_group_id=None):
    if existing_group_id and existing_group_id.strip():
        return existing_group_id.strip()
    _face_calls["ensure_group"] += 1
    return "group-NEW"


import itertools
_upload_serial = itertools.count(1)


def _fake_upload_asset(api, asset_type, name, group_id=None, image_tensor=None, file_path=None):
    # Serial is independent of the per-phase counters below, which get reset —
    # every upload must still return a distinct asset id, as the real API does.
    _face_calls["upload"] += 1
    _face_calls["last_name"] = name
    return (f"asset://uploaded-{next(_upload_serial)}", None, group_id or "group-NEW")


nodes._ensure_group = _fake_ensure_group
nodes._upload_asset = _fake_upload_asset
nodes._wait_for_asset_active = lambda *a, **k: None
nodes._stabilize_anyfast_asset = lambda *a, **k: None
os.environ["SEEDANCE_IDENTITIES_DIR"] = os.path.join(_SCRATCH, "ids2")
try:
    face = nodes.SeedanceFaceRef()
    img = _FakeTensor(1)

    # Cold run: nothing cached, so a group must be created and the image uploaded.
    res = face.upload(api=API, group_name="test", identity="pablo", ref_image_1=img)
    refs, gid, ids = res["result"]
    check("cold run creates exactly one group", _face_calls["ensure_group"] == 1, _face_calls)
    check("cold run uploads once", _face_calls["upload"] == 1, _face_calls)
    check("asset is named after the identity",
          _face_calls["last_name"].startswith("pablo_"), _face_calls.get("last_name"))
    check("identity file written on upload", nodes._load_identity("pablo") is not None)

    # Warm run: same image, so the hash cache hits. This is the case that used to
    # create a throwaway group on every single run.
    _face_calls["ensure_group"] = 0
    _face_calls["upload"] = 0
    refs2, gid2, _ = face.upload(api=API, group_name="test", identity="pablo",
                                 ref_image_1=img)["result"]
    check("warm run creates NO group", _face_calls["ensure_group"] == 0, _face_calls)
    check("warm run uploads nothing", _face_calls["upload"] == 0, _face_calls)
    check("warm run returns the same asset", refs2[0]["image_url"]["url"] == refs[0]["image_url"]["url"],
          (refs, refs2))
    check("warm run recovers the group from the identity", gid2 == gid, (gid, gid2))

    # A brand new image on a known identity reuses that identity's group instead
    # of spawning another one.
    _face_calls["ensure_group"] = 0
    face.upload(api=API, group_name="test", identity="pablo", ref_image_1=_FakeTensor(2))
    check("new image on known identity reuses its group", _face_calls["ensure_group"] == 0, _face_calls)
    check("identity now holds two assets", len(nodes._load_identity("pablo")["assets"]) == 2,
          nodes._load_identity("pablo")["assets"])

    # Without an identity, behaviour is the old one: cache still works, no file written.
    _face_calls["ensure_group"] = 0
    _face_calls["upload"] = 0
    face.upload(api=API, group_name="test", ref_image_1=img)
    check("no identity -> still cache-hits", _face_calls["upload"] == 0, _face_calls)
    check("no identity -> no identity file", "anonymous" not in nodes._list_identities())
finally:
    nodes._ensure_group = _real_ensure_group
    nodes._upload_asset = _real_upload_asset
    nodes._wait_for_asset_active = _real_wait
    nodes._stabilize_anyfast_asset = _real_settle
    os.environ.pop("SEEDANCE_IDENTITIES_DIR", None)

print("\n=== asset settle timing ===")
check("image settle dropped from 20s to 5s", nodes.ASSET_SETTLE_DEFAULTS["Image"] == 5,
      nodes.ASSET_SETTLE_DEFAULTS)
os.environ["SEEDANCE_ASSET_SETTLE"] = "0"
import time as _time
_t = _time.time(); nodes._stabilize_anyfast_asset("Image"); _elapsed_override = _time.time() - _t
os.environ.pop("SEEDANCE_ASSET_SETTLE", None)
check("SEEDANCE_ASSET_SETTLE=0 skips the wait", _elapsed_override < 1, f"{_elapsed_override:.1f}s")
_t = _time.time(); nodes._stabilize_anyfast_asset("Video"); _elapsed_video = _time.time() - _t
check("non-image types still never wait", _elapsed_video < 1, f"{_elapsed_video:.1f}s")

print("\n=== example workflows on disk ===")
# Checks the generated files, not the generator's spec — so a hand-edit that
# breaks a workflow is caught too.
CORE_WIDGET_COUNTS = {"LoadImage": 2}
_examples = sorted(f for f in os.listdir(os.path.join(REPO, "examples")) if f.endswith(".json"))
check("examples exist", len(_examples) >= 10, _examples)

for fn in _examples:
    with open(os.path.join(REPO, "examples", fn), encoding="utf-8") as fh:
        wf = json.load(fh)
    issues = []
    ids = {n["id"] for n in wf["nodes"]}
    for node in wf["nodes"]:
        ntype = node["type"]
        if ntype in CORE_WIDGET_COUNTS:
            expected_widgets = CORE_WIDGET_COUNTS[ntype]
        elif ntype in nodes.NODE_CLASS_MAPPINGS:
            expected_widgets = len(widget_order(nodes.NODE_CLASS_MAPPINGS[ntype]))
        else:
            issues.append(f"unknown node type {ntype}")
            continue
        got = len(node.get("widgets_values", []))
        if got != expected_widgets:
            issues.append(f"{ntype}: {got} widget value(s), node declares {expected_widgets}")
        if getattr(nodes.NODE_CLASS_MAPPINGS.get(ntype), "DEPRECATED", False):
            issues.append(f"{ntype} is deprecated — examples should use the current node")

    # Every link must connect slots that actually exist on both ends.
    for link_id, from_id, from_slot, to_id, to_slot, link_type in wf["links"]:
        if from_id not in ids or to_id not in ids:
            issues.append(f"link {link_id} references a missing node")
            continue
        src = next(n for n in wf["nodes"] if n["id"] == from_id)
        dst = next(n for n in wf["nodes"] if n["id"] == to_id)
        if from_slot >= len(src["outputs"]):
            issues.append(f"link {link_id}: {src['type']} has no output slot {from_slot}")
        if to_slot >= len(dst["inputs"]):
            issues.append(f"link {link_id}: {dst['type']} has no input slot {to_slot}")
        if from_slot < len(src["outputs"]) and src["outputs"][from_slot]["type"] != link_type:
            issues.append(f"link {link_id}: type {link_type} != output type "
                          f"{src['outputs'][from_slot]['type']}")

    # A generation node's resolution/duration must be legal for its model.
    for node in wf["nodes"]:
        if node["type"] != "SeedanceVideo":
            continue
        names = widget_order(nodes.SeedanceVideo)
        picked = dict(zip(names, node["widgets_values"]))
        spec = nodes.MODEL_SPECS.get(picked.get("model"))
        if not spec:
            issues.append(f"unknown model {picked.get('model')!r}")
            continue
        if picked["resolution"] not in spec["resolutions"]:
            issues.append(f"{picked['model']} cannot do {picked['resolution']}")
        d = picked["duration"]
        if d == -1 and spec["duration_min"] != -1:
            issues.append(f"{picked['model']} cannot take duration -1")
        elif d != -1 and not (4 <= d <= spec["duration_max"]):
            issues.append(f"{picked['model']} duration {d} out of range")

    check(f"{fn} is coherent", not issues, "; ".join(issues))

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    print("FAILED:", FAIL)
    sys.exit(1)
