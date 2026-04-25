import { app } from "../../scripts/app.js";

app.registerExtension({
    name: "Seedance.HumanAsset",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "SeedanceCreateHumanAsset") return;

        // ── add the hidden verify-link panel on node creation ──
        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            onNodeCreated?.apply(this, arguments);

            const el = document.createElement("div");
            el.style.display  = "none";
            el.style.padding  = "4px 2px";

            this._sdVerifyEl = el;
            this.addDOMWidget("seedance_verify_link", "div", el, {
                serialize: false,
                computeSize: () => [this.size[0], 90],
            });
        };

        // ── populate / hide the panel after each execution ──
        const onExecuted = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (message) {
            onExecuted?.apply(this, arguments);

            const el  = this._sdVerifyEl;
            if (!el) return;

            const url = message?.verify_url?.[0] || "";

            if (url) {
                el.style.display = "";
                el.innerHTML = `
                    <div style="
                        background:#5a0e0e;border:1px solid #c03030;
                        border-radius:6px;padding:8px;font-size:12px;
                    ">
                        <div style="color:#ffaaaa;font-weight:bold;margin-bottom:6px;">
                            ⚠ Identity Verification Required
                        </div>
                        <a href="${url}"
                           target="_blank" rel="noopener noreferrer"
                           style="
                               display:block;background:#1a6b1a;color:#fff;
                               padding:7px 10px;border-radius:4px;text-decoration:none;
                               font-weight:bold;text-align:center;font-size:12px;
                               word-break:break-all;
                           ">
                            🔗 Open Verification Link
                        </a>
                        <div style="color:#aaa;font-size:11px;text-align:center;margin-top:5px;">
                            Complete the liveness check on your phone within 30 s,
                            then save the <strong style="color:#ddd">group_id</strong> output for future runs.
                        </div>
                    </div>`;
                this.setSize([this.size[0], this.computeSize()[1]]);
            } else {
                el.style.display = "none";
            }
        };
    },
});
