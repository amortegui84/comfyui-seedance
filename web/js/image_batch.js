import { app } from "../../scripts/app.js";

app.registerExtension({
    name: "Seedance.ImageBatch",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "SeedanceImageBatch") return;

        nodeType.prototype._syncImageInputs = function (count) {
            // image_1 and image_2 are always defined in Python — only manage 3..9
            const current = this.inputs.filter(i => /^image_\d+$/.test(i.name)).length;

            if (count > current) {
                for (let n = current + 1; n <= count; n++) {
                    this.addInput("image_" + n, "IMAGE");
                }
            } else if (count < current) {
                for (let n = current; n > count; n--) {
                    const idx = this.inputs.findIndex(i => i.name === "image_" + n);
                    if (idx !== -1) this.removeInput(idx);
                }
            }

            this.setSize(this.computeSize());
            app.graph.setDirtyCanvas(true, true);
        };

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            onNodeCreated?.apply(this, arguments);
            const countWidget = this.widgets?.find(w => w.name === "inputcount");
            if (!countWidget) return;

            // "Update Inputs" button — same pattern as KJ nodes ImageBatchMulti
            this.addWidget("button", "Update Inputs", null, () => {
                this._syncImageInputs(countWidget.value);
            });

            // Sync immediately on node creation
            this._syncImageInputs(countWidget.value);
        };

        // Restore correct number of inputs when loading a saved workflow
        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function (config) {
            onConfigure?.apply(this, arguments);
            const countWidget = this.widgets?.find(w => w.name === "inputcount");
            if (countWidget) this._syncImageInputs(countWidget.value);
        };
    },
});
