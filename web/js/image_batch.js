import { app } from "../../scripts/app.js";

app.registerExtension({
    name: "Seedance.ImageBatch",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "SeedanceImageBatch") return;

        console.log("[Seedance] ImageBatch extension registered");

        nodeType.prototype._syncImageInputs = function (count) {
            const current = this.inputs.filter(i => /^image_\d+$/.test(i.name)).length;
            console.log(`[Seedance] _syncImageInputs: current=${current} target=${count}`);

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
            console.log("[Seedance] onNodeCreated — widgets:", this.widgets?.map(w => w.name), "countWidget:", countWidget);

            if (!countWidget) {
                console.warn("[Seedance] inputcount widget NOT found — button will not be added");
                return;
            }

            this.addWidget("button", "Update Inputs", null, () => {
                console.log("[Seedance] Update Inputs clicked, count =", countWidget.value);
                this._syncImageInputs(countWidget.value);
            }, { serialize: false });

            console.log("[Seedance] Update Inputs button added");
            this._syncImageInputs(countWidget.value);
        };

        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function (config) {
            onConfigure?.apply(this, arguments);
            const countWidget = this.widgets?.find(w => w.name === "inputcount");
            if (countWidget) this._syncImageInputs(countWidget.value);
        };
    },
});
