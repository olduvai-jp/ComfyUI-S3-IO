import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";

const EXTENSION_NAME = "comfy.s3io.upload";
const PREVIEW_NODE_CONFIGS = {
    LoadImageS3: {
        previewRoute: "/s3io/preview/image",
    },
    LoadVideoUploadS3: {
        previewRoute: "/s3io/preview/video",
    },
};
const ACCEPTED_IMAGE_TYPES = "image/png,image/jpeg,image/webp";
const ACCEPTED_VIDEO_TYPES =
    "video/webm,video/mp4,video/quicktime,video/x-matroska,image/gif";

const NODE_UPLOAD_CONFIGS = {
    LoadImageS3: {
        inputName: "image",
        accept: ACCEPTED_IMAGE_TYPES,
        uploadRoute: "/s3io/upload/image",
        formField: "image",
        allowBatchFromInput: true,
    },
    LoadVideoUploadS3: {
        inputName: "video",
        accept: ACCEPTED_VIDEO_TYPES,
        uploadRoute: "/s3io/upload/video",
        formField: "video",
    },
    VHS_LoadVideo: {
        inputName: "video",
        accept: ACCEPTED_VIDEO_TYPES,
        uploadRoute: "/s3io/upload/video",
        formField: "video",
    },
    VHS_LoadVideoFFmpeg: {
        inputName: "video",
        accept: ACCEPTED_VIDEO_TYPES,
        uploadRoute: "/s3io/upload/video",
        formField: "video",
    },
};

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

const addToComboValues = (widget, value) => {
    if (!widget.options) widget.options = { values: [] };
    if (!widget.options.values) widget.options.values = [];
    if (!widget.options.values.includes(value)) {
        widget.options.values.push(value);
    }
};

const normalizeComboValue = (value) => {
    if (Array.isArray(value)) return value[0];
    return value;
};

const isImageFile = (file) => file?.type?.startsWith("image/");
const isVideoFile = (file) =>
    file?.type?.startsWith("video/") || file?.type === "image/gif";

const fetchS3PreviewEntry = async (name, previewRoute) => {
    if (!name || !previewRoute) return null;
    const resp = await api.fetchApi(
        `${previewRoute}?name=${encodeURIComponent(name)}`
    );
    if (resp.status !== 200) return null;
    return resp.json();
};

const setNodePreviewOutput = (node, entry) => {
    if (!node || !entry?.filename) return;
    if (!app.nodeOutputs) app.nodeOutputs = {};
    app.nodeOutputs[`${node.id}`] = {
        images: [entry],
        animated: [false],
    };
    node.graph?.setDirtyCanvas(true);
};

const uploadFile = async (
    file,
    { isPasted = false, uploadRoute, formField }
) => {
    const body = new FormData();
    body.append(formField, file);
    if (isPasted) body.append("subfolder", "pasted");

    const resp = await api.fetchApi(uploadRoute, {
        method: "POST",
        body,
    });

    if (resp.status !== 200) {
        toast("Upload failed", `${resp.status} - ${resp.statusText}`, "error");
        return null;
    }

    const data = await resp.json();
    return data.subfolder ? `${data.subfolder}/${data.name}` : data.name;
};

const createFileInput = ({ accept, allow_batch, fileFilter, onSelect }) => {
    let fileInput = document.createElement("input");
    fileInput.type = "file";
    fileInput.accept = accept ?? "*";
    fileInput.multiple = !!allow_batch;

    fileInput.onchange = () => {
        if (!fileInput?.files?.length) return;
        const files = Array.from(fileInput.files).filter(fileFilter);
        if (files.length) onSelect(files);
    };

    return {
        openFileSelection: () => fileInput?.click(),
        cleanup: () => {
            if (fileInput) {
                fileInput.onchange = null;
                fileInput = null;
            }
        },
    };
};

const useNodeDragAndDrop = (node, { onDrop, fileFilter }) => {
    const filter = fileFilter ?? (() => true);
    const hasFiles = (items) =>
        !!Array.from(items ?? []).find((f) => f.kind === "file");
    const filterFiles = (files) =>
        Array.from(files ?? []).filter(filter);
    const hasValidFiles = (files) => filterFiles(files).length > 0;

    node.onDragOver = function (e) {
        if (!e?.dataTransfer?.items) return false;
        return hasFiles(e.dataTransfer.items);
    };

    node.onDragDrop = function (e) {
        if (!e?.dataTransfer?.files || !hasValidFiles(e.dataTransfer.files)) {
            return false;
        }
        const files = filterFiles(e.dataTransfer.files);
        void onDrop(files);
        return true;
    };
};

const useNodePaste = (node, { onPaste, fileFilter, allow_batch }) => {
    const filter = fileFilter ?? (() => true);
    node.pasteFiles = function (files) {
        const filtered = Array.from(files ?? []).filter(filter);
        if (!filtered.length) return false;
        const batch = allow_batch ? filtered : filtered.slice(0, 1);
        void onPaste(batch);
        return true;
    };
};

app.registerExtension({
    name: EXTENSION_NAME,
    beforeRegisterNodeDef(nodeType, nodeData) {
        const config = NODE_UPLOAD_CONFIGS[nodeData?.name];
        if (!config) return;

        const inputSpec = nodeData?.input?.required?.[config.inputName];
        const inputOptions = inputSpec?.[1] ?? {};
        const allow_batch = config.allowBatchFromInput
            ? !!inputOptions.allow_batch
            : false;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const r = onNodeCreated ? onNodeCreated.apply(this, arguments) : undefined;

            const comboWidget = this.widgets?.find(
                (w) => w.name === config.inputName
            );
            const uploadWidget = this.widgets?.find((w) => w.name === "upload");
            if (!comboWidget || !uploadWidget) return r;

            const previewConfig = PREVIEW_NODE_CONFIGS[nodeData?.name];
            if (previewConfig) {
                let previewToken = 0;
                const originalCallback = comboWidget.callback;
                const node = this;
                const requestPreview = (value) => {
                    const selected = normalizeComboValue(value ?? comboWidget.value);
                    if (!selected) return;
                    const token = ++previewToken;
                    void (async () => {
                        const entry = await fetchS3PreviewEntry(
                            selected,
                            previewConfig.previewRoute
                        );
                        if (token !== previewToken) return;
                        setNodePreviewOutput(node, entry);
                    })();
                };
                comboWidget.callback = function (value) {
                    if (originalCallback) {
                        originalCallback.apply(this, arguments);
                    }
                    requestPreview(value);
                };
                requestPreview(comboWidget.value);
            }

            const isVideo = config.uploadRoute.includes("/video");
            const fileFilter = isVideo ? isVideoFile : isImageFile;

            const handleUploadBatch = async (files, { isPasted = false } = {}) => {
                const batch = allow_batch ? files : files.slice(0, 1);
                const paths = await Promise.all(
                    batch.map((file) =>
                        uploadFile(file, {
                            isPasted,
                            uploadRoute: config.uploadRoute,
                            formField: config.formField,
                        })
                    )
                );
                const validPaths = paths.filter((p) => !!p);
                if (!validPaths.length) return;

                validPaths.forEach((path) => addToComboValues(comboWidget, path));
                comboWidget.value = allow_batch ? validPaths : validPaths[0];
                comboWidget.callback?.(comboWidget.value);
                this.graph?.setDirtyCanvas(true);
            };

            const { openFileSelection, cleanup } = createFileInput({
                accept: config.accept,
                allow_batch,
                fileFilter,
                onSelect: (files) => handleUploadBatch(files),
            });

            uploadWidget.callback = () => openFileSelection();

            useNodeDragAndDrop(this, {
                fileFilter,
                onDrop: (files) => handleUploadBatch(files),
            });

            useNodePaste(this, {
                allow_batch,
                fileFilter,
                onPaste: (files) => handleUploadBatch(files, { isPasted: true }),
            });

            const onRemoved = this.onRemoved;
            this.onRemoved = function () {
                cleanup();
                return onRemoved ? onRemoved.apply(this, arguments) : undefined;
            };

            return r;
        };
    },
});
