import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

async function uploadToInputDir(file) {
    const body = new FormData();
    body.append("image", file);
    body.append("type", "input");
    body.append("subfolder", "");
    const resp = await api.fetchApi("/upload/image", { method: "POST", body });
    if (!resp.ok) throw new Error(`Upload failed: ${resp.status}`);
    return (await resp.json()).name;
}

async function refreshCombo(node, widgetName, nodeTypeName) {
    try {
        const resp = await api.fetchApi(`/object_info/${nodeTypeName}`);
        const defs = await resp.json();
        const inputDef = defs[nodeTypeName]?.input;
        const newValues =
            inputDef?.required?.[widgetName]?.[0] ??
            inputDef?.optional?.[widgetName]?.[0];
        if (!newValues) return;
        const widget = node.widgets?.find(w => w.name === widgetName);
        if (widget) widget.options.values = newValues;
    } catch (_) {}
}

function addFileButtonToNode(node, widgetName, buttonLabel, acceptTypes, nodeTypeName) {
    node.addWidget("button", buttonLabel, null, async () => {
        const input = document.createElement("input");
        input.type = "file";
        input.accept = acceptTypes;
        input.onchange = async () => {
            if (!input.files.length) return;
            try {
                const filename = await uploadToInputDir(input.files[0]);
                await refreshCombo(node, widgetName, nodeTypeName);
                const widget = node.widgets?.find(w => w.name === widgetName);
                if (widget) {
                    widget.value = filename;
                    widget.callback?.(filename);
                }
                app.graph.setDirtyCanvas(true);
            } catch (e) {
                alert("Upload error: " + e.message);
            }
        };
        input.click();
    });
}

app.registerExtension({
    name: "Seedance.FileLoaders",
    nodeCreated(node) {
        if (node.comfyClass === "SeedanceReferenceVideo") {
            addFileButtonToNode(
                node,
                "video_file",
                "📁 Choose Video",
                ".mp4,.mov,.avi,.webm,video/mp4,video/quicktime,video/x-msvideo,video/webm",
                "SeedanceReferenceVideo"
            );
        }
        if (node.comfyClass === "SeedanceReferenceAudio") {
            addFileButtonToNode(
                node,
                "audio_file",
                "📁 Choose Audio",
                ".mp3,.wav,.ogg,.flac,.m4a,audio/mpeg,audio/wav,audio/ogg,audio/flac,audio/mp4",
                "SeedanceReferenceAudio"
            );
        }
    },
});
