try:
    from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS
    print(f"[Seedance] Loaded {len(NODE_CLASS_MAPPINGS)} nodes successfully")
except Exception as e:
    import traceback
    print(f"[Seedance] ERROR — failed to load nodes: {e}")
    traceback.print_exc()
    NODE_CLASS_MAPPINGS = {}
    NODE_DISPLAY_NAME_MAPPINGS = {}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
