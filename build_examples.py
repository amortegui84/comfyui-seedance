"""Generate the example workflows in examples/ from the live node definitions.

Hand-written ComfyUI workflow JSON drifts: it carries its own copy of every
node's input list and a positional array of widget values, so any change to a
node silently invalidates it. That is how examples/11 ended up asking Seedance
2.5 for 1080p, which the model does not support.

Here the graph is described compactly (nodes + links by NAME) and the input
sockets, output sockets and slot indices are derived by introspecting
NODE_CLASS_MAPPINGS. Widget values are validated against the node's own
INPUT_TYPES — including the per-model resolution and duration limits — so an
impossible example cannot be written out.

    python build_examples.py            # validate only, report what would change
    python build_examples.py --write    # regenerate examples/*.json
"""
import argparse
import atexit
import json
import os
import shutil
import sys
import tempfile
import types

REPO = os.path.dirname(os.path.abspath(__file__))

# Introspecting the nodes touches the identity store, which creates its folder.
# Point it at a scratch dir so building examples never writes inside the repo.
_SCRATCH = tempfile.mkdtemp(prefix="seedance_build_")
atexit.register(shutil.rmtree, _SCRATCH, True)
fp = types.ModuleType("folder_paths")
fp.get_input_directory = lambda: os.getcwd()
fp.get_output_directory = lambda: os.getcwd()
fp.get_user_directory = lambda: _SCRATCH
sys.modules["folder_paths"] = fp
sys.path.insert(0, REPO)
import nodes  # noqa: E402

WIDGET_TYPES = {"INT", "FLOAT", "STRING", "BOOLEAN"}

# Combos whose options come from the machine running this, not from the node:
# saved identities, and files sitting in ComfyUI's input folder. An example may
# legitimately name something the building machine does not have — same as a
# workflow referencing a checkpoint you have not downloaded.
ENVIRONMENT_COMBOS = {"identity", "audio_file", "video_file", "image"}

# Core ComfyUI nodes we reference but cannot introspect from here.
CORE_NODES = {
    "LoadImage": {
        "inputs":  [],
        "outputs": [("IMAGE", "IMAGE"), ("MASK", "MASK")],
        "widgets": ["image", "upload"],
        "size":    [315, 315],
    },
}


def node_shape(node_type):
    """(inputs, outputs, widget_names) exactly as ComfyUI will lay the node out."""
    if node_type in CORE_NODES:
        core = CORE_NODES[node_type]
        return core["inputs"], core["outputs"], core["widgets"]

    cls = nodes.NODE_CLASS_MAPPINGS[node_type]
    spec = cls.INPUT_TYPES()
    inputs, widgets = [], []
    for section in ("required", "optional"):
        for name, definition in (spec.get(section) or {}).items():
            kind = definition[0] if isinstance(definition, (tuple, list)) else definition
            config = definition[1] if isinstance(definition, (tuple, list)) and len(definition) > 1 else {}
            if isinstance(kind, list) or (kind in WIDGET_TYPES and not config.get("forceInput")):
                widgets.append(name)
            else:
                inputs.append((name, kind if isinstance(kind, str) else "STRING"))
    outputs = list(zip(cls.RETURN_NAMES, cls.RETURN_TYPES))
    return inputs, outputs, widgets


def widget_spec(node_type, name):
    if node_type in CORE_NODES:
        return None, {}
    spec = nodes.NODE_CLASS_MAPPINGS[node_type].INPUT_TYPES()
    for section in ("required", "optional"):
        definition = (spec.get(section) or {}).get(name)
        if definition is None:
            continue
        kind = definition[0] if isinstance(definition, (tuple, list)) else definition
        config = definition[1] if isinstance(definition, (tuple, list)) and len(definition) > 1 else {}
        return kind, config
    return None, {}


def validate_node(wf_name, node):
    """Reject anything the node itself would reject, before it reaches a user."""
    problems = []
    node_type = node["type"]
    _, _, widget_names = node_shape(node_type)
    values = node.get("widgets", [])

    if len(values) != len(widget_names):
        problems.append(
            f"{node_type}: {len(values)} widget value(s) for {len(widget_names)} widget(s) "
            f"{widget_names}"
        )
        return problems

    picked = dict(zip(widget_names, values))
    for name, value in picked.items():
        kind, config = widget_spec(node_type, name)
        if name in ENVIRONMENT_COMBOS:
            continue
        if isinstance(kind, list) and value not in kind:
            problems.append(f"{node_type}.{name}={value!r} not in {kind}")
        elif kind == "INT" and isinstance(value, int):
            lo, hi = config.get("min"), config.get("max")
            if lo is not None and value < lo or hi is not None and value > hi:
                problems.append(f"{node_type}.{name}={value} outside [{lo}, {hi}]")

    # Cross-widget rules the static schema cannot express.
    if node_type == "SeedanceVideo":
        spec = nodes.MODEL_SPECS.get(picked.get("model"), {})
        if spec:
            if picked["resolution"] not in spec["resolutions"]:
                problems.append(
                    f"{picked['model']} does not support resolution "
                    f"{picked['resolution']!r} (only {spec['resolutions']})"
                )
            duration = picked["duration"]
            if duration == -1 and spec["duration_min"] != -1:
                problems.append(f"{picked['model']} does not accept duration -1")
            elif duration != -1 and not (4 <= duration <= spec["duration_max"]):
                problems.append(
                    f"{picked['model']} duration {duration} outside 4-{spec['duration_max']}"
                )
            if picked.get("web_search") and picked["model"] not in nodes.MODEL_SPECS:
                problems.append("web_search set on an unknown model")
    return problems


def build(workflow):
    """Compact spec -> ComfyUI workflow JSON."""
    by_id = {n["id"]: n for n in workflow["nodes"]}
    shapes = {n["id"]: node_shape(n["type"]) for n in workflow["nodes"]}

    # Resolve links by name into (link_id, from_id, from_slot, to_id, to_slot, type).
    links, out_links, in_links = [], {}, {}
    for i, (from_id, from_name, to_id, to_name) in enumerate(workflow["links"], start=1):
        _, outputs, _ = shapes[from_id]
        try:
            from_slot = [o[0] for o in outputs].index(from_name)
        except ValueError:
            raise SystemExit(
                f"{workflow['file']}: node {from_id} ({by_id[from_id]['type']}) has no output "
                f"{from_name!r}; available: {[o[0] for o in outputs]}"
            )
        inputs, _, _ = shapes[to_id]
        try:
            to_slot = [s[0] for s in inputs].index(to_name)
        except ValueError:
            raise SystemExit(
                f"{workflow['file']}: node {to_id} ({by_id[to_id]['type']}) has no input "
                f"{to_name!r}; available: {[s[0] for s in inputs]}"
            )
        link_type = outputs[from_slot][1]
        links.append([i, from_id, from_slot, to_id, to_slot, link_type])
        out_links.setdefault((from_id, from_slot), []).append(i)
        in_links[(to_id, to_slot)] = i

    out_nodes = []
    for order, node in enumerate(workflow["nodes"]):
        inputs, outputs, widget_names = shapes[node["id"]]
        out_nodes.append({
            "id":    node["id"],
            "type":  node["type"],
            "title": node["title"],
            "pos":   node["pos"],
            "size":  node.get("size", CORE_NODES.get(node["type"], {}).get("size", [400, 300])),
            "flags": {},
            "order": order,
            "mode":  0,
            "outputs": [
                {"name": name, "type": kind,
                 "links": out_links.get((node["id"], slot), []), "slot_index": slot}
                for slot, (name, kind) in enumerate(outputs)
            ],
            "inputs": [
                {"name": name, "type": kind, "link": in_links.get((node["id"], slot))}
                for slot, (name, kind) in enumerate(inputs)
            ],
            "properties": {"Node name for S&R": node["type"]},
            "widgets_values": node.get("widgets", []),
        })

    return {
        "last_node_id": max(n["id"] for n in workflow["nodes"]),
        "last_link_id": len(links),
        "nodes":  out_nodes,
        "links":  links,
        "groups": [],
        "config": {},
        "extra":  {"ds": {"scale": 1, "offset": [0, 0]}},
        "version": 0.4,
    }


# --------------------------------------------------------------------------- #
# The workflows. Each one demonstrates exactly one thing.
# --------------------------------------------------------------------------- #

# Placeholder identity name used by the shipped examples. Deliberately generic:
# these files are shared, and a real person's name in a public repo is both a
# privacy leak and a broken reference on anyone else's machine.
EXAMPLE_IDENTITY = "my-subject"

API_KEY = {"id": 1, "type": "SeedanceApiKey", "title": "1. API key",
           "pos": [40, 40], "size": [380, 100], "widgets": ["", "https://www.anyfast.ai"]}


def save(node_id, prefix, pos, title="Save video"):
    return {"id": node_id, "type": "SeedanceSaveVideo", "title": title,
            "pos": pos, "size": [320, 100], "widgets": [prefix, "output"]}


def gen(node_id, title, pos, model, prompt, resolution="720p", ratio="16:9",
        duration=5, audio=True, watermark=False, seed=-1, web_search=False):
    return {"id": node_id, "type": "SeedanceVideo", "title": title, "pos": pos,
            "size": [440, 360],
            "widgets": [model, prompt, resolution, ratio, duration,
                        audio, watermark, seed, web_search]}


WORKFLOWS = [
    {
        "file": "01_text_to_video.json",
        "what": "T2V — the minimal baseline, prompt only",
        "nodes": [
            API_KEY,
            gen(2, "2. Pick a model and write a prompt", [460, 40], "seedance-2.0",
                "A beautiful sunset over the ocean, cinematic", duration=5),
            save(3, "seedance_t2v", [950, 120]),
        ],
        "links": [(1, "api", 2, "api"), (2, "video_url", 3, "video_url")],
    },
    {
        "file": "02_image_to_video.json",
        "what": "I2V — animate a still, starting from an exact first frame",
        "nodes": [
            API_KEY,
            {"id": 2, "type": "LoadImage", "title": "2. Image to animate",
             "pos": [40, 180], "widgets": ["scene.png", "image"]},
            gen(3, "3. Generate from first_frame", [460, 40], "seedance-2.0",
                "Slow push-in, gentle wind, cinematic", duration=5),
            save(4, "seedance_i2v", [950, 120]),
        ],
        "links": [(1, "api", 3, "api"), (2, "IMAGE", 3, "first_frame"),
                  (3, "video_url", 4, "video_url")],
    },
    {
        "file": "03_first_last_frame.json",
        "what": "Frame control — interpolate between a start and an end image",
        "nodes": [
            API_KEY,
            {"id": 2, "type": "LoadImage", "title": "2. Start frame",
             "pos": [40, 180], "widgets": ["start.png", "image"]},
            {"id": 3, "type": "LoadImage", "title": "3. End frame",
             "pos": [40, 540], "widgets": ["end.png", "image"]},
            gen(4, "4. Generate between the two frames", [460, 40], "seedance-2.0",
                "Smooth transformation between the two framings, cinematic", duration=5),
            save(5, "seedance_first_last", [950, 120]),
        ],
        "links": [(1, "api", 4, "api"), (2, "IMAGE", 4, "first_frame"),
                  (3, "IMAGE", 4, "last_frame"), (4, "video_url", 5, "video_url")],
    },
    {
        "file": "04_save_identity.json",
        "what": "Real person — upload once and SAVE it as a named identity",
        "nodes": [
            API_KEY,
            {"id": 2, "type": "LoadImage", "title": "2. Photo of the person",
             "pos": [40, 180], "widgets": ["portrait.png", "image"]},
            {"id": 3, "type": "SeedanceFaceRef",
             "title": "3. Upload as asset:// AND save it under a name you choose",
             "pos": [460, 40], "size": [400, 460],
             "widgets": ["comfyui-assets", False, EXAMPLE_IDENTITY]},
            gen(4, "4. Generate — @image1 places the reference", [900, 40], "seedance-2.0",
                "A person walking through a sunlit forest, cinematic @image1", duration=5),
            save(5, "seedance_identity_save", [1390, 40]),
            {"id": 6, "type": "SeedanceShowText",
             "title": "group_id — reconnect to skip liveness next time",
             "pos": [900, 460], "size": [440, 90], "widgets": []},
        ],
        "links": [(1, "api", 3, "api"), (2, "IMAGE", 3, "ref_image_1"),
                  (1, "api", 4, "api"), (3, "anyfast_refs", 4, "anyfast_refs"),
                  (4, "video_url", 5, "video_url"), (3, "group_id", 6, "text")],
    },
    {
        "file": "05_reuse_identity.json",
        "what": "Real person — REUSE a saved identity: no image, no upload",
        "nodes": [
            API_KEY,
            {"id": 2, "type": "SeedanceIdentity",
             "title": "2. Pick a saved person — resolves from disk, nothing uploaded",
             "pos": [40, 180], "size": [400, 150],
             "widgets": [EXAMPLE_IDENTITY, "reference_image", 0]},
            gen(3, "3. Generate — @image1 places the reference", [500, 40], "seedance-2.0",
                "Portrait in warm afternoon light, shallow depth of field @image1", duration=5),
            save(4, "seedance_identity_reuse", [990, 120]),
        ],
        "links": [(1, "api", 3, "api"), (2, "anyfast_refs", 3, "anyfast_refs"),
                  (3, "video_url", 4, "video_url")],
    },
    {
        "file": "06_lip_sync.json",
        "what": "Lip-sync — saved identity + voice sample + quoted dialogue",
        "nodes": [
            API_KEY,
            {"id": 2, "type": "SeedanceIdentity", "title": "2. Who is speaking",
             "pos": [40, 180], "size": [400, 150],
             "widgets": [EXAMPLE_IDENTITY, "reference_image", 0]},
            {"id": 3, "type": "SeedanceReferenceAudio",
             "title": "3. Voice sample to clone (2-15s)",
             "pos": [40, 380], "size": [400, 180],
             "widgets": ["voice.mp3", ""]},
            gen(4, "4. Dialogue goes in DOUBLE QUOTES; keep generate_audio ON",
                [500, 40], "seedance-2.0",
                'The person looks at camera and says "Hello, good to see you again." '
                'Warm indoor lighting @image1 @audio1', duration=5, audio=True),
            save(5, "seedance_lipsync", [990, 120]),
        ],
        "links": [(1, "api", 4, "api"), (2, "anyfast_refs", 4, "anyfast_refs"),
                  (3, "reference_audio", 4, "reference_audio"), (4, "video_url", 5, "video_url")],
    },
    {
        "file": "07_extend_video.json",
        "what": "Extend (2.0 only) — continue a clip via its task_id",
        "nodes": [
            API_KEY,
            gen(2, "2. First clip", [460, 40], "seedance-2.0",
                "A car driving down a coastal road at sunset", duration=5),
            {"id": 3, "type": "SeedanceExtend",
             "title": "3. Continue it — same model and resolution as the original",
             "pos": [950, 40], "size": [420, 260],
             "widgets": ["seedance", "The car turns inland toward the mountains", 5, "720p", True]},
            save(4, "seedance_extended", [1420, 120]),
        ],
        "links": [(1, "api", 2, "api"), (1, "api", 3, "api"),
                  (2, "task_id", 3, "task_id"), (3, "video_url", 4, "video_url")],
    },
    {
        "file": "08_v25_long_clip.json",
        "what": "Seedance 2.5 — a 30s single-pass clip (720p max on 2.5)",
        "nodes": [
            API_KEY,
            gen(2, "2. 30 seconds in one pass — 2.5 tops out at 720p", [460, 40],
                "seedance-2.5",
                "A continuous tracking shot through a miniature steampunk city at golden hour, "
                "the camera weaving between rooftops and airships",
                resolution="720p", duration=30),
            save(3, "seedance_v25_long", [950, 120]),
        ],
        "links": [(1, "api", 2, "api"), (2, "video_url", 3, "video_url")],
    },
    {
        "file": "09_v25_audio_only.json",
        "what": "Seedance 2.5 — generate from audio alone (2.0 cannot do this)",
        "nodes": [
            API_KEY,
            {"id": 2, "type": "SeedanceReferenceAudio",
             "title": "2. The only reference — no image, no video",
             "pos": [40, 180], "size": [400, 180],
             "widgets": ["music.mp3", ""]},
            gen(3, "3. duration -1 lets the model match the audio", [500, 40],
                "seedance-2.5",
                "Abstract visuals that follow the rhythm and mood of @audio1, "
                "flowing colour and light",
                resolution="720p", ratio="adaptive", duration=-1),
            save(4, "seedance_v25_audio_only", [990, 120]),
        ],
        "links": [(1, "api", 3, "api"), (2, "reference_audio", 3, "reference_audio"),
                  (3, "video_url", 4, "video_url")],
    },
    {
        "file": "10_v25_multi_reference.json",
        "what": "Seedance 2.5 — identity + motion video + music in one request",
        "nodes": [
            API_KEY,
            {"id": 2, "type": "SeedanceIdentity", "title": "2. Who appears",
             "pos": [40, 180], "size": [400, 150],
             "widgets": [EXAMPLE_IDENTITY, "reference_image", 0]},
            {"id": 3, "type": "SeedanceReferenceVideo",
             "title": "3. Motion to copy",
             "pos": [40, 380], "size": [400, 180],
             "widgets": ["", "motion.mp4"]},
            {"id": 4, "type": "SeedanceReferenceAudio",
             "title": "4. Music to pace it (one URL per line for several)",
             "pos": [40, 610], "size": [400, 180],
             "widgets": ["music.mp3", ""]},
            gen(5, "5. 2.5 takes 30 images / 10 videos / 10 audio", [500, 40],
                "seedance-2.5",
                "@image1 performs the motion from @video1, paced to @audio1, "
                "cinematic lighting",
                resolution="720p", duration=15, audio=False),
            save(6, "seedance_v25_multi", [990, 120]),
        ],
        "links": [(1, "api", 5, "api"), (1, "api", 3, "api"),
                  (2, "anyfast_refs", 5, "anyfast_refs"),
                  (3, "reference_video", 5, "reference_video"),
                  (4, "reference_audio", 5, "reference_audio"),
                  (5, "video_url", 6, "video_url")],
    },
    {
        "file": "11_v25_web_search.json",
        "what": "Seedance 2.5 — ground a text-to-video prompt in current information",
        "nodes": [
            API_KEY,
            gen(2, "2. web_search ON — text-to-video only", [460, 40], "seedance-2.5",
                "A product showcase reflecting this season's dominant colour trends",
                resolution="720p", duration=10, web_search=True),
            save(3, "seedance_v25_websearch", [950, 120]),
        ],
        "links": [(1, "api", 2, "api"), (2, "video_url", 3, "video_url")],
    },
]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true", help="write the JSON files")
    args = ap.parse_args()

    out_dir = os.path.join(REPO, "examples")
    problems = []
    built = {}

    for workflow in WORKFLOWS:
        for node in workflow["nodes"]:
            for problem in validate_node(workflow["file"], node):
                problems.append(f"{workflow['file']}: {problem}")
        built[workflow["file"]] = build(workflow)

    if problems:
        print("VALIDATION FAILED\n")
        for problem in problems:
            print(f"  {problem}")
        return 1

    print(f"{len(built)} workflow(s) validated against the live node definitions.\n")
    existing = {f for f in os.listdir(out_dir) if f.endswith(".json")}
    stale = sorted(existing - set(built))

    for name, data in built.items():
        mark = " (new)" if name not in existing else ""
        what = next(w["what"] for w in WORKFLOWS if w["file"] == name)
        print(f"  {name:<32} {what}{mark}")
    if stale:
        print("\n  stale, will be removed: " + ", ".join(stale))

    if not args.write:
        print("\nDry run. Re-run with --write to regenerate examples/.")
        return 0

    for name, data in built.items():
        with open(os.path.join(out_dir, name), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    for name in stale:
        os.remove(os.path.join(out_dir, name))
    print(f"\nWrote {len(built)} file(s)" + (f", removed {len(stale)}." if stale else "."))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
