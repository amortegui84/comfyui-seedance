"""One-shot import of the old hash cache into the identity store.

The hash cache (seedance_asset_cache.json) knows which asset:// id belongs to
which image, but not who that image is of — the old uploader named every asset
"face_reference_image_1". This groups the cached entries by the AnyFast group
they were uploaded to and writes one identity file per group, named
unnamed-1, unnamed-2, ... Rename the files afterwards (the file stem IS the
identity name) and the Identity node dropdown picks the new names up.

    python migrate_identities.py            # show what it would do
    python migrate_identities.py --apply    # write the identity files

Nothing is deleted: the hash cache keeps working exactly as before, so this is
safe to run and safe to skip.
"""
import argparse
import os
import sys
import types

# Windows consoles default to cp1252 and cannot encode the arrows in the output.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

# Stub ComfyUI's folder_paths so nodes.py imports outside ComfyUI. get_user_directory
# is what decides where both stores live, so resolve it the same way ComfyUI would.
def _resolve_user_dir(explicit=None):
    """Locate ComfyUI's user/ directory.

    Order: --user-dir, then $COMFYUI_USER_DIR, then derived from where this file
    sits. A custom node lives at ComfyUI/custom_nodes/<repo>/, so ComfyUI's user
    directory is two levels up — which holds for every install layout rather than
    for one particular machine."""
    if explicit:
        return explicit
    env = os.environ.get("COMFYUI_USER_DIR", "").strip()
    if env:
        return env

    here = os.path.dirname(os.path.abspath(__file__))
    derived = os.path.normpath(os.path.join(here, "..", "..", "user"))
    if os.path.isdir(derived):
        return derived
    return here


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="actually write the identity files")
    ap.add_argument("--user-dir", default=None,
                    help="ComfyUI user directory (default: autodetect, or $COMFYUI_USER_DIR)")
    ap.add_argument("--prefix", default="unnamed", help="name prefix for imported identities")
    args = ap.parse_args()

    user_dir = _resolve_user_dir(args.user_dir)
    fp = types.ModuleType("folder_paths")
    fp.get_user_directory = lambda: user_dir
    fp.get_input_directory = lambda: os.getcwd()
    fp.get_output_directory = lambda: os.getcwd()
    sys.modules["folder_paths"] = fp

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import nodes

    cache = nodes._load_asset_cache()
    if not cache:
        print(f"No cached assets found under {user_dir}. Nothing to migrate.")
        return 0

    # Group by the AnyFast group each asset was uploaded to — assets uploaded
    # together in one run share a group, so that is the best available proxy for
    # "these images are the same subject".
    by_group = {}
    for image_hash, entry in cache.items():
        by_group.setdefault(entry.get("group_id") or "no-group", []).append((image_hash, entry))

    ordered = sorted(by_group.items(), key=lambda kv: min(e[1].get("uploaded_at", "") for e in kv[1]))

    print(f"cache      : {len(cache)} image(s) in {len(by_group)} group(s)")
    print(f"identities : {nodes._identities_dir()}")
    print()

    existing = set(nodes._list_identities())
    planned = []
    for i, (group_id, entries) in enumerate(ordered, start=1):
        name = f"{args.prefix}-{i}"
        entries.sort(key=lambda e: e[1].get("uploaded_at", ""))
        planned.append((name, group_id, entries))
        flag = "  (SKIP — already exists)" if name in existing else ""
        print(f"{name:<14} {len(entries):>2} image(s)  group={group_id}{flag}")

    if not args.apply:
        print("\nDry run. Re-run with --apply to write these files.")
        return 0

    written = 0
    for name, group_id, entries in planned:
        if name in existing:
            continue
        record = {
            "identity": name,
            "group_id": group_id if group_id != "no-group" else "",
            "notes":    "Imported from seedance_asset_cache.json. Rename this file to "
                        "rename the identity.",
            "assets": [
                {
                    "asset_id":    entry["asset_id"],
                    "role":        "reference_image",
                    "image_sha":   image_hash,
                    "uploaded_at": entry.get("uploaded_at", ""),
                }
                for image_hash, entry in entries
            ],
        }
        nodes._save_identity(record)
        written += 1

    print(f"\nWrote {written} identity file(s). Rename them to something meaningful, "
          f"then restart ComfyUI so the Identity dropdown reloads.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
