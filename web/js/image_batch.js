import { app } from "../../scripts/app.js";

app.registerExtension({
    name: "Seedance.ImageBatch",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "SeedanceImageBatch") return;

        nodeType.prototype.onNodeCreated = function () {
            this._type = "IMAGE";
            this.addWidget("button", "Update Inputs", null, () => {
                if (!this.inputs) this.inputs = [];

                const countWidget = this.widgets.find(w => w.name === "inputcount");
                if (!countWidget) return;

                const target  = countWidget.value;
                const current = this.inputs.filter(i => i.type === this._type).length;

                if (target === current) return;

                if (target < current) {
                    const toRemove = current - target;
                    for (let i = 0; i < toRemove; i++) {
                        this.removeInput(this.inputs.length - 1);
                    }
                } else {
                    for (let i = current + 1; i <= target; i++) {
                        this.addInput(`image_${i}`, this._type, { shape: 7 });
                    }
                }
            });
        };
    },
});
