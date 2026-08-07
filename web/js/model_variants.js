import { app } from "../../scripts/app.js";

// Mirrors MODEL_SPECS in nodes.py. Python is the source of truth and enforces
// these limits on every request — this only narrows the widgets so an invalid
// combination is not reachable in the UI. Adding a model means adding it here
// AND in nodes.py; if the two drift, Python wins and the node raises.
const MODEL_SPECS = {
    "seedance-2.0":       { resolutions: ["1080p", "720p", "480p"], durationMin: 4,  durationMax: 15, webSearch: true },
    "seedance-2.0-fast":  { resolutions: ["1080p", "720p", "480p"], durationMin: 4,  durationMax: 15, webSearch: true },
    "seedance-2.0-mini":  { resolutions: ["1080p", "720p", "480p"], durationMin: 4,  durationMax: 15, webSearch: true },
    "seedance-2.0-ultra": { resolutions: ["2k", "1080p", "720p"],   durationMin: 4,  durationMax: 15, webSearch: true },
    "seedance-2.5":       { resolutions: ["720p", "480p"],          durationMin: -1, durationMax: 30, webSearch: true },
};

function getWidget(node, name) {
    return node.widgets?.find((w) => w.name === name);
}

function applySpec(node) {
    const modelWidget = getWidget(node, "model");
    const spec = MODEL_SPECS[modelWidget?.value];
    if (!spec) return;

    const resolution = getWidget(node, "resolution");
    if (resolution) {
        // Widget option lists live in different places across ComfyUI versions.
        if (resolution.options) resolution.options.values = spec.resolutions;
        resolution.values = spec.resolutions;
        // Snap to the model's default when the current pick is not supported.
        if (!spec.resolutions.includes(resolution.value)) {
            resolution.value = spec.resolutions.includes("720p") ? "720p" : spec.resolutions[0];
            resolution.callback?.(resolution.value);
        }
    }

    const duration = getWidget(node, "duration");
    if (duration) {
        duration.options = duration.options || {};
        duration.options.min = spec.durationMin;
        duration.options.max = spec.durationMax;
        // -1 is "let the model choose"; anything between 0 and 3 is never valid.
        if (duration.value > spec.durationMax) {
            duration.value = spec.durationMax;
        } else if (duration.value < 4 && !(duration.value === -1 && spec.durationMin === -1)) {
            duration.value = Math.max(4, spec.durationMin === -1 ? 4 : spec.durationMin);
        }
    }

    app.graph.setDirtyCanvas(true);
}

app.registerExtension({
    name: "Seedance.ModelVariants",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "SeedanceVideo") return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            onNodeCreated?.apply(this, arguments);

            const modelWidget = getWidget(this, "model");
            if (!modelWidget) return;

            const originalCallback = modelWidget.callback;
            modelWidget.callback = (value, ...args) => {
                originalCallback?.call(modelWidget, value, ...args);
                applySpec(this);
            };

            applySpec(this);
        };

        // Re-apply after a saved workflow restores widget values.
        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            onConfigure?.apply(this, arguments);
            applySpec(this);
        };
    },
});
