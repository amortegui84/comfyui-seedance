import { app } from '../../../scripts/app.js'
import { api } from '../../../scripts/api.js'

function chainCallback(object, property, callback) {
    if (object == undefined) return;
    if (property in object && object[property]) {
        const orig = object[property];
        object[property] = function () {
            const r = orig.apply(this, arguments);
            return callback.apply(this, arguments) ?? r;
        };
    } else {
        object[property] = callback;
    }
}

async function uploadFile(file) {
    const body = new FormData();
    body.append("image", new File([file], file.name, { type: file.type, lastModified: file.lastModified }));
    const url = api.apiURL("/upload/image");
    const resp = await new Promise((resolve) => {
        const req = new XMLHttpRequest();
        req.onload = () => resolve(req);
        req.open('post', url, true);
        req.send(body);
    });
    if (resp.status !== 200) {
        alert(resp.status + " - " + resp.statusText);
    }
    return resp;
}

function addUploadButton(nodeType, widgetName, type) {
    const accept = {
        video: ["video/mp4", "video/webm", "video/quicktime", "video/x-msvideo"],
        audio: ["audio/mpeg", "audio/wav", "audio/x-wav", "audio/ogg", "audio/flac", "audio/mp4"],
    }[type];

    chainCallback(nodeType.prototype, "onNodeCreated", function () {
        const node = this;
        const pathWidget = this.widgets?.find((w) => w.name === widgetName);
        if (!pathWidget) return;

        const fileInput = document.createElement("input");
        chainCallback(this, "onRemoved", () => fileInput?.remove());

        Object.assign(fileInput, {
            type: "file",
            accept: accept.join(","),
            style: "display: none",
            onchange: async () => {
                if (!fileInput.files.length) return;
                const resp = await uploadFile(fileInput.files[0]);
                if (resp.status !== 200) return;
                const filename = JSON.parse(resp.responseText).name;
                pathWidget.options.values.push(filename);
                pathWidget.value = filename;
                pathWidget.callback?.(filename);
            },
        });

        this.onDragOver = (e) => !!e?.dataTransfer?.types?.includes?.("Files");
        this.onDragDrop = async (e) => {
            const item = e?.dataTransfer?.files?.[0];
            if (!item || !accept.includes(item.type)) return false;
            const resp = await uploadFile(item);
            if (resp.status !== 200) return false;
            const filename = JSON.parse(resp.responseText).name;
            pathWidget.options.values.push(filename);
            pathWidget.value = filename;
            pathWidget.callback?.(filename);
            return true;
        };

        document.body.append(fileInput);

        const btn = this.addWidget("button", "choose " + type + " to upload", "image", () => {
            app.canvas.node_widget = null;
            fileInput.click();
        });
        btn.options.serialize = false;
    });
}

app.registerExtension({
    name: "Seedance.FileLoaders",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name === "SeedanceReferenceVideo") {
            addUploadButton(nodeType, "video_file", "video");
        }
        if (nodeData.name === "SeedanceReferenceAudio") {
            addUploadButton(nodeType, "audio_file", "audio");
        }
    },
});
