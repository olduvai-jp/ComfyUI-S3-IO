import { app } from "../../../scripts/app.js";

const EXTENSION_NAME = "comfy.s3io.download";
const TARGET_NODES = new Set(["SaveImageS3", "VideoCombineS3"]);

const toast = (summary, detail, severity = "info") => {
    try {
        app.extensionManager?.toast?.add({
            severity,
            summary,
            detail,
            life: 3000,
        });
    } catch (err) {
        console.warn(summary, detail, err);
    }
};

const normalizeSubfolder = (value) => {
    if (!value) return "";
    const normalized = value.replace(/\\/g, "/").replace(/^\/+/, "");
    if (!normalized || normalized === ".") return "";
    const parts = normalized.split("/").filter(Boolean);
    if (parts.some((part) => part === "..")) return null;
    return parts.join("/");
};

const normalizeFilename = (value) => {
    if (!value) return null;
    const name = value.split(/[\\/]/).pop();
    if (!name || name === "." || name === "..") return null;
    if (name.includes("..")) return null;
    return name;
};

const buildRelativePath = (subfolder, filename) => {
    const safeSubfolder = normalizeSubfolder(subfolder);
    const safeFilename = normalizeFilename(filename);
    if (safeSubfolder === null || !safeFilename) return null;
    return safeSubfolder ? `${safeSubfolder}/${safeFilename}` : safeFilename;
};

const buildViewUrl = (filename, subfolder, type) => {
    const url = new URL("/view", window.location.origin);
    url.searchParams.set("filename", filename);
    if (subfolder) url.searchParams.set("subfolder", subfolder);
    if (type) url.searchParams.set("type", type);
    return url.toString();
};

const collectEntries = (output) => {
    const entries = [];
    if (Array.isArray(output?.downloads)) entries.push(...output.downloads);
    if (Array.isArray(output?.images)) entries.push(...output.images);
    if (Array.isArray(output?.gifs)) entries.push(...output.gifs);
    return entries;
};

const requestDownloads = (output) => {
    const comfyDl = window.comfyuiDL;
    if (!comfyDl?.requestDownload) return;

    const entries = collectEntries(output);
    if (!entries.length) return;

    const seen = new Set();
    for (const entry of entries) {
        const filename = entry?.filename;
        if (!filename) continue;
        const subfolder = entry?.subfolder ?? "";
        const type = entry?.type ?? "output";
        const relativePath = buildRelativePath(subfolder, filename);
        if (!relativePath) {
            toast("Download skipped", "Invalid output path", "warn");
            continue;
        }
        const key = `${type}:${relativePath}`;
        if (seen.has(key)) continue;
        seen.add(key);

        const url = buildViewUrl(filename, subfolder, type);
        const request = comfyDl.requestDownload({ url, relativePath });
        Promise.resolve(request).catch((err) => {
            console.warn("Download failed", err);
            toast("Download failed", filename, "error");
        });
    }
};

app.registerExtension({
    name: EXTENSION_NAME,
    beforeRegisterNodeDef(nodeType, nodeData) {
        if (!TARGET_NODES.has(nodeData?.name)) return;

        const onExecuted = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (message) {
            onExecuted?.apply(this, arguments);
            try {
                requestDownloads(message ?? {});
            } catch (err) {
                console.warn("Download hook failed", err);
            }
        };
    },
});
