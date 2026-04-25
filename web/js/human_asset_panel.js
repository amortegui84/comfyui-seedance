import { app } from "../../scripts/app.js";

app.registerExtension({
    name: "Seedance.HumanAssetPanel",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "SeedanceHumanAssetPanel") return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            onNodeCreated?.apply(this, arguments);

            const el = document.createElement("div");
            el.style.padding = "6px 2px";

            this._sdHumanPanelEl = el;
            this.addDOMWidget("seedance_human_asset_panel", "div", el, {
                serialize: false,
                computeSize: () => [Math.max(this.size[0], 340), 240],
            });
        };

        const onExecuted = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (message) {
            onExecuted?.apply(this, arguments);

            const el = this._sdHumanPanelEl;
            if (!el) return;

            const assetId = message?.asset_id?.[0] || "";
            const groupId = message?.group_id?.[0] || "";
            const verifyUrl = message?.verify_url?.[0] || "";
            const verified = !verifyUrl && !!groupId;

            const statusText = verifyUrl ? "Verification Required" : (verified ? "Ready" : "Waiting for Data");
            const statusColor = verifyUrl ? "#ffb3b3" : (verified ? "#b9ffd2" : "#ddd");
            const cardBorder = verifyUrl ? "#c03a3a" : "#2f7f57";
            const cardBg = verifyUrl ? "#401515" : "#13281f";

            const renderValue = (label, value) => `
                <div style="margin:8px 0 0;">
                    <div style="color:#cfcfcf;font-size:11px;text-transform:uppercase;letter-spacing:.08em;">${label}</div>
                    <div style="
                        margin-top:4px;padding:8px 10px;border-radius:6px;
                        background:#101010;border:1px solid #3a3a3a;color:#f3f3f3;
                        font-family:monospace;font-size:12px;word-break:break-all;
                    ">${value || "—"}</div>
                </div>
            `;

            const linkBlock = verifyUrl ? `
                <a href="${verifyUrl}" target="_blank" rel="noopener noreferrer" style="
                    display:block;margin-top:12px;background:#1d6f42;color:#fff;
                    padding:9px 12px;border-radius:6px;text-decoration:none;
                    font-weight:700;text-align:center;font-size:12px;word-break:break-all;
                ">Open Verification Link</a>
                <div style="margin-top:6px;color:#c8c8c8;font-size:11px;text-align:center;">
                    Complete the liveness check, then keep the returned <strong>group_id</strong> for future uploads.
                </div>
            ` : "";

            el.innerHTML = `
                <div style="
                    background:${cardBg};border:1px solid ${cardBorder};border-radius:10px;
                    padding:12px;text-align:center;
                ">
                    <div style="color:${statusColor};font-weight:700;font-size:13px;">
                        ${statusText}
                    </div>
                    ${linkBlock}
                    ${renderValue("asset_id", assetId)}
                    ${renderValue("group_id", groupId)}
                    ${verifyUrl ? renderValue("verify_url", verifyUrl) : ""}
                </div>
            `;

            this.setSize([Math.max(this.size[0], 360), this.computeSize()[1]]);
        };
    },
});
