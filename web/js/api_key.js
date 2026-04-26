import { app } from "../../scripts/app.js";

const PROVIDER_URLS = {
    "anyfast": "https://www.anyfast.ai",
    "fal.ai": "https://fal.run",
};

function getWidget(node, name) {
    return node.widgets?.find((w) => w.name === name);
}

function syncBaseUrl(node) {
    const providerWidget = getWidget(node, "provider");
    const baseUrlWidget = getWidget(node, "base_url");
    if (!providerWidget || !baseUrlWidget) return;

    const nextUrl = PROVIDER_URLS[providerWidget.value];
    if (!nextUrl) return;

    if (baseUrlWidget.value !== nextUrl) {
        baseUrlWidget.value = nextUrl;
        baseUrlWidget.callback?.(nextUrl);
        app.graph.setDirtyCanvas(true);
    }
}

app.registerExtension({
    name: "Seedance.ApiKey",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (!["SeedanceApiKey", "SeedanceApiKeyV2"].includes(nodeData.name)) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            onNodeCreated?.apply(this, arguments);

            const providerWidget = getWidget(this, "provider");
            if (!providerWidget) return;

            const originalCallback = providerWidget.callback;
            providerWidget.callback = (value, ...args) => {
                originalCallback?.call(providerWidget, value, ...args);
                syncBaseUrl(this);
            };

            syncBaseUrl(this);
        };

        const onDrawForeground = nodeType.prototype.onDrawForeground;
        nodeType.prototype.onDrawForeground = function () {
            onDrawForeground?.apply(this, arguments);
            syncBaseUrl(this);
        };
    },
});
