import { app } from "../../../scripts/app.js";
import { applyTextReplacements } from "../../../scripts/utils.js";

const EXTENSION_NAME = "comfy.s3io.prefix_format";
const TARGET_NODES = new Set(["SaveImageS3", "VideoCombineS3"]);
const TARGET_WIDGET = "filename_prefix";

const log = (...args) => console.debug?.("[S3-IO prefix]", ...args);
const logWarn = (...args) => console.warn?.("[S3-IO prefix]", ...args);

const chainCallback = (object, property, callback) => {
    if (!object) return;
    const original = object[property];
    object[property] = function () {
        const r = original ? original.apply(this, arguments) : undefined;
        return callback.apply(this, arguments) ?? r;
    };
};

const enhancePrefixWidget = (node) => {
    const widget = node.widgets?.find?.((w) => w.name === TARGET_WIDGET);
    if (!widget) return;

    log("hook widget", node.type, widget.name);

    const originalSerialize = widget.serializeValue?.bind(widget);
    widget.serializeValue = async (workflowNode, widgetIndex) => {
        const raw = originalSerialize
            ? await originalSerialize(workflowNode, widgetIndex)
            : widget.value;

        if (typeof raw !== "string") {
            logWarn("skip replace (non-string)", node.type, { raw });
            return raw;
        }

        const graph = workflowNode?.graph ?? app.graph;
        let replaced = raw;
        try {
            // Primary: current ComfyUI utils signature (app, value)
            replaced = applyTextReplacements(app, raw);
        } catch (errApp) {
            try {
                // Fallback: older signature (graph, value)
                replaced = applyTextReplacements(graph, raw);
            } catch (errGraph) {
                logWarn("replace failed", { raw, errApp, errGraph });
                replaced = raw;
            }
        }

        log("serialize", node.type, { raw, replaced });
        return replaced;
    };
};

app.registerExtension({
    name: EXTENSION_NAME,
    beforeRegisterNodeDef(nodeType, nodeData) {
        if (!TARGET_NODES.has(nodeData?.name)) return;

        log("register node", nodeData.name);
        chainCallback(nodeType.prototype, "onNodeCreated", function () {
            enhancePrefixWidget(this);
        });
    },
});
