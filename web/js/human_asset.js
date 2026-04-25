import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const VERIFY_SESSION_PATH = "/proxy/seedance/visual-validate/sessions";

function renderMessage(el, { title, body, accent = "#c03030", background = "#5a0e0e" }) {
    el.style.display = "";
    el.innerHTML = `
        <div style="
            background:${background};border:1px solid ${accent};
            border-radius:6px;padding:8px;font-size:12px;
        ">
            <div style="color:#ffdddd;font-weight:bold;margin-bottom:6px;">${title}</div>
            ${body}
        </div>`;
}

function getWidget(node, name) {
    return node.widgets?.find((w) => w.name === name);
}

function renderIdleState(el) {
    renderMessage(el, {
        title: "Real Human Verification",
        body: `
            <div style="color:#ddd;text-align:center;line-height:1.45;">
                Run this node once with <strong style="color:#fff">existing_group_id</strong> empty.
                After execution, use the verification control shown here to start the H5 flow.
            </div>
        `,
        accent: "#3c5f8a",
        background: "#182433",
    });
}

function renderProxyHelp(el, details) {
    const safeDetails = details ? `<div style="margin-top:8px;color:#ffd1d1;">${details}</div>` : "";
    renderMessage(el, {
        title: "Verification Proxy Unavailable",
        body: `
            <div style="color:#ffe1e1;line-height:1.45;">
                The Seedance verification session could not be started from ComfyUI.
            </div>
            <div style="margin-top:8px;color:#ddd;line-height:1.45;">
                Check these requirements:
            </div>
            <div style="margin-top:6px;color:#ddd;line-height:1.5;">
                1. Update ComfyUI to the latest nightly or newest desktop build.<br>
                2. Open ComfyUI from <strong style="color:#fff">127.0.0.1</strong> or <strong style="color:#fff">localhost</strong>.<br>
                3. Make sure you are logged into ComfyUI API nodes / ByteDance access.<br>
                4. Avoid running this through <strong style="color:#fff">--listen</strong> on a LAN URL for verification.
            </div>
            <div style="margin-top:8px;color:#bbb;font-family:monospace;font-size:11px;word-break:break-all;">
                POST ${VERIFY_SESSION_PATH}
            </div>
            ${safeDetails}
        `,
    });
}

async function startVerification(node, el) {
    if (node._sdVerifyBusy) return;
    node._sdVerifyBusy = true;

    renderMessage(el, {
        title: "Starting Verification",
        body: `<div style="color:#ddd;text-align:center;">Requesting H5 verification session...</div>`,
        accent: "#8a6a1d",
        background: "#3a2e12",
    });

    try {
        const createResp = await api.fetchApi(VERIFY_SESSION_PATH, {
            method: "POST",
        });
        if (!createResp.ok) {
            let responseText = "";
            try {
                responseText = await createResp.text();
            } catch {
                responseText = "";
            }
            if (createResp.status === 404) {
                renderProxyHelp(el, "ComfyUI did not expose the Seedance verification endpoint.");
                node._sdVerifyBusy = false;
                return;
            }
            if (createResp.status === 401 || createResp.status === 403) {
                renderProxyHelp(el, "Authentication failed. ComfyUI may not be logged in for API partner nodes.");
                node._sdVerifyBusy = false;
                return;
            }
            throw new Error(`Session request failed: ${createResp.status}${responseText ? ` - ${responseText}` : ""}`);
        }

        const session = await createResp.json();
        const sessionId = session?.session_id || session?.SessionId || "";
        const h5Link = session?.h5_link || session?.h5Link || session?.url || "";
        if (!sessionId || !h5Link) {
            throw new Error("Verification session did not return session_id and h5_link.");
        }

        renderMessage(el, {
            title: "Identity Verification Required",
            body: `
                <a href="${h5Link}" target="_blank" rel="noopener noreferrer" style="
                    display:block;background:#1a6b1a;color:#fff;
                    padding:7px 10px;border-radius:4px;text-decoration:none;
                    font-weight:bold;text-align:center;font-size:12px;word-break:break-all;
                ">Open Verification Link</a>
                <div style="color:#ccc;font-size:11px;text-align:center;margin-top:6px;">
                    Complete the liveness check. This node will keep polling and auto-fill
                    <strong style="color:#fff">existing_group_id</strong> when the session completes.
                </div>
            `,
        });

        const poll = async () => {
            const statusResp = await api.fetchApi(`${VERIFY_SESSION_PATH}/${encodeURIComponent(sessionId)}`);
            if (!statusResp.ok) {
                throw new Error(`Status poll failed: ${statusResp.status}`);
            }
            const status = await statusResp.json();
            const state = (status?.status || "").toLowerCase();
            const groupId = status?.group_id || status?.GroupId || "";

            if (state === "completed" && groupId) {
                const widget = getWidget(node, "existing_group_id");
                if (widget) {
                    widget.value = groupId;
                    widget.callback?.(groupId);
                }
                app.graph.setDirtyCanvas(true);

                renderMessage(el, {
                    title: "Verification Complete",
                    body: `
                        <div style="
                            margin-top:4px;padding:8px 10px;border-radius:6px;
                            background:#101010;border:1px solid #3a3a3a;color:#f3f3f3;
                            font-family:monospace;font-size:12px;word-break:break-all;
                        ">${groupId}</div>
                        <div style="color:#c8ffd2;font-size:11px;text-align:center;margin-top:6px;">
                            existing_group_id was filled automatically. Queue this node again to create the final asset_id.
                        </div>
                    `,
                    accent: "#2f7f57",
                    background: "#13281f",
                });
                node._sdVerifyBusy = false;
                return;
            }

            if (state === "failed") {
                const errorText = status?.error_message || status?.error_code || "Verification failed.";
                throw new Error(errorText);
            }

            window.setTimeout(poll, 3000);
        };

        window.setTimeout(poll, 3000);
    } catch (err) {
        const message = String(err.message || err);
        if (message.includes("Failed to fetch")) {
            renderProxyHelp(el, "Browser request failed before reaching the verification endpoint.");
        } else {
            renderMessage(el, {
                title: "Verification Error",
                body: `<div style="color:#ffd1d1;text-align:center;line-height:1.45;">${message}</div>`,
            });
        }
        node._sdVerifyBusy = false;
    }
}

app.registerExtension({
    name: "Seedance.HumanAsset",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "SeedanceCreateHumanAsset") return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            onNodeCreated?.apply(this, arguments);

            const el = document.createElement("div");
            el.style.display = "";
            el.style.padding = "4px 2px";

            this._sdVerifyEl = el;
            this.addDOMWidget("seedance_verify_link", "div", el, {
                serialize: false,
                computeSize: () => [this.size[0], 130],
            });
            renderIdleState(el);
        };

        const onExecuted = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (message) {
            onExecuted?.apply(this, arguments);

            const el = this._sdVerifyEl;
            if (!el) return;

            const url = message?.verify_url?.[0] || "";
            const needsH5Auth = (message?.needs_h5_auth?.[0] || "") === "1";
            const assetId = message?.asset_id?.[0] || "";
            const groupId = message?.group_id?.[0] || "";
            const lines = Array.isArray(message?.text) ? message.text : [];

            if (needsH5Auth) {
                renderMessage(el, {
                    title: "Verification Required",
                    body: `
                        <button type="button" style="
                            display:block;width:100%;background:#1a6b1a;color:#fff;
                            padding:8px 10px;border-radius:4px;border:none;cursor:pointer;
                            font-weight:bold;text-align:center;font-size:12px;
                        ">Start Verification</button>
                        <div style="color:#ccc;font-size:11px;text-align:center;margin-top:6px;">
                            This uses the same local ComfyUI Seedance verification flow as the base ByteDance workflow.
                        </div>
                    `,
                });
                const button = el.querySelector("button");
                button?.addEventListener("click", () => startVerification(this, el));
                this.setSize([this.size[0], this.computeSize()[1]]);
                return;
            }

            if (lines.length && !url && !assetId && !groupId) {
                renderMessage(el, {
                    title: "Node Output",
                    body: `
                        <div style="
                            margin-top:4px;padding:8px 10px;border-radius:6px;
                            background:#101010;border:1px solid #3a3a3a;color:#f3f3f3;
                            font-family:monospace;font-size:12px;line-height:1.45;white-space:pre-wrap;
                        ">${lines.join("\n")}</div>
                    `,
                    accent: "#3c5f8a",
                    background: "#182433",
                });
                this.setSize([this.size[0], this.computeSize()[1]]);
                return;
            }

            if (url) {
                renderMessage(el, {
                    title: "Identity Verification Required",
                    body: `
                        <a href="${url}" target="_blank" rel="noopener noreferrer" style="
                            display:block;background:#1a6b1a;color:#fff;
                            padding:7px 10px;border-radius:4px;text-decoration:none;
                            font-weight:bold;text-align:center;font-size:12px;word-break:break-all;
                        ">Open Verification Link</a>
                        <div style="color:#aaa;font-size:11px;text-align:center;margin-top:5px;">
                            Complete the liveness check, then save the <strong style="color:#ddd">group_id</strong> output for future runs.
                        </div>
                    `,
                });
                this.setSize([this.size[0], this.computeSize()[1]]);
                return;
            }

            if (assetId || groupId) {
                renderMessage(el, {
                    title: "Human Asset Ready",
                    body: `
                        <div style="color:#c8ffd2;text-align:center;margin-bottom:8px;">Asset created successfully.</div>
                        <div style="
                            margin-top:4px;padding:8px 10px;border-radius:6px;
                            background:#101010;border:1px solid #3a3a3a;color:#f3f3f3;
                            font-family:monospace;font-size:12px;word-break:break-all;
                        ">asset_id: ${assetId || "-"}<br>group_id: ${groupId || "-"}</div>
                    `,
                    accent: "#2f7f57",
                    background: "#13281f",
                });
                this.setSize([this.size[0], this.computeSize()[1]]);
                return;
            }

            renderIdleState(el);
        };
    },
});
