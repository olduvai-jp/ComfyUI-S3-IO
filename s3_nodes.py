import os
from typing import Optional

import numpy as np
import torch
from PIL import Image, ImageOps, ImageSequence

import folder_paths
import node_helpers
from comfy.k_diffusion.utils import FolderOfImages

import nodes as comfy_nodes

from . import s3_helpers
from .s3_vhs import load_video_nodes as vhs_load_video
from .s3_vhs import nodes as vhs_nodes


IMAGE_EXTENSIONS = {ext.lstrip(".") for ext in FolderOfImages.IMG_EXTENSIONS}
VIDEO_EXTENSIONS = vhs_load_video.video_extensions


def _strip_annotation(name: str) -> str:
    return folder_paths.annotated_filepath(name)[0]


def _resolve_local_path(name: str) -> str:
    return folder_paths.get_annotated_filepath(name)


def _preview_ui_for_path(path: str) -> dict:
    subfolder, filename = s3_helpers.local_temp_preview_path(path)
    return {
        "images": [
            {
                "filename": filename,
                "subfolder": subfolder,
                "type": "temp",
            }
        ]
    }


def _download_entry_for_file(path: str) -> Optional[dict]:
    if not path:
        return None
    file_path = os.path.abspath(path)
    if not os.path.exists(file_path):
        return None
    output_dir = os.path.abspath(folder_paths.get_output_directory())
    temp_dir = os.path.abspath(folder_paths.get_temp_directory())
    if os.path.commonpath((file_path, output_dir)) == output_dir:
        base_dir = output_dir
        file_type = "output"
    elif os.path.commonpath((file_path, temp_dir)) == temp_dir:
        base_dir = temp_dir
        file_type = "temp"
    else:
        return None
    rel_dir = os.path.relpath(os.path.dirname(file_path), base_dir)
    if rel_dir == ".":
        rel_dir = ""
    return {
        "filename": os.path.basename(file_path),
        "subfolder": rel_dir,
        "type": file_type,
    }


def _load_image_from_path(image_path: str):
    img = node_helpers.pillow(Image.open, image_path)

    output_images = []
    output_masks = []
    w, h = None, None

    excluded_formats = ["MPO"]

    for i in ImageSequence.Iterator(img):
        i = node_helpers.pillow(ImageOps.exif_transpose, i)

        if i.mode == "I":
            i = i.point(lambda x: x * (1 / 255))
        image = i.convert("RGB")

        if len(output_images) == 0:
            w = image.size[0]
            h = image.size[1]

        if image.size[0] != w or image.size[1] != h:
            continue

        image = np.array(image).astype(np.float32) / 255.0
        image = torch.from_numpy(image)[None,]
        if "A" in i.getbands():
            mask = np.array(i.getchannel("A")).astype(np.float32) / 255.0
            mask = 1.0 - torch.from_numpy(mask)
        elif i.mode == "P" and "transparency" in i.info:
            mask = np.array(i.convert("RGBA").getchannel("A")).astype(np.float32) / 255.0
            mask = 1.0 - torch.from_numpy(mask)
        else:
            mask = torch.zeros((64, 64), dtype=torch.float32, device="cpu")
        output_images.append(image)
        output_masks.append(mask.unsqueeze(0))

    if len(output_images) > 1 and img.format not in excluded_formats:
        output_image = torch.cat(output_images, dim=0)
        output_mask = torch.cat(output_masks, dim=0)
    else:
        output_image = output_images[0]
        output_mask = output_masks[0]

    return output_image, output_mask


class LoadImageS3:
    @classmethod
    def INPUT_TYPES(s):
        try:
            config = s3_helpers.get_config()
            keys = s3_helpers.list_media_keys(config.input_prefix, IMAGE_EXTENSIONS)
        except Exception:
            keys = []
        return {
            "required": {
                "image": (sorted(keys), {"image_upload": True}),
            }
        }

    CATEGORY = "image"
    RETURN_TYPES = ("IMAGE", "MASK")
    FUNCTION = "load_image"

    def load_image(self, image):
        name = _strip_annotation(image)
        local_path = _resolve_local_path(image)
        preview_path = None

        if os.path.exists(local_path):
            s3_key = s3_helpers.input_key_for(name)
            s3_helpers.upload_file(local_path, s3_key, content_type=s3_helpers.content_type_for_path(local_path))
            preview_path = s3_helpers.ensure_thumbnail(local_path, s3_key)
            image_path = local_path
        else:
            s3_key = s3_helpers.resolve_input_key(name)
            image_path = s3_helpers.download_to_cache(s3_key)
            thumb_key = s3_helpers.thumb_key_for(s3_key)
            if s3_helpers.object_exists(thumb_key):
                preview_path = s3_helpers.download_to_cache(thumb_key, kind="thumbs")
            else:
                preview_path = image_path

        output_image, output_mask = _load_image_from_path(image_path)
        ui = _preview_ui_for_path(preview_path)
        return {"ui": ui, "result": (output_image, output_mask)}

    @classmethod
    def IS_CHANGED(s, image):
        name = _strip_annotation(image)
        local_path = _resolve_local_path(image)
        if os.path.exists(local_path):
            return s3_helpers.file_hash(local_path)
        s3_key = s3_helpers.resolve_input_key(name)
        try:
            head = s3_helpers.head_object(s3_key)
            etag = head.get("ETag", "").strip('"')
            return f"{s3_key}:{etag}"
        except FileNotFoundError:
            return s3_key

    @classmethod
    def VALIDATE_INPUTS(s, image):
        name = _strip_annotation(image)
        local_path = _resolve_local_path(image)
        if os.path.exists(local_path):
            return True
        s3_key = s3_helpers.resolve_input_key(name)
        if not s3_helpers.object_exists(s3_key):
            return f"Invalid image file: {image}"
        return True


class SaveImageS3(comfy_nodes.SaveImage):
    def __init__(self):
        super().__init__()

    @classmethod
    def INPUT_TYPES(s):
        return comfy_nodes.SaveImage.INPUT_TYPES()

    RETURN_TYPES = ()
    FUNCTION = "save_images"
    OUTPUT_NODE = True
    CATEGORY = "image"

    def save_images(self, images, filename_prefix="ComfyUI", prompt=None, extra_pnginfo=None):
        results = super().save_images(images, filename_prefix=filename_prefix, prompt=prompt, extra_pnginfo=extra_pnginfo)
        for entry in results.get("ui", {}).get("images", []):
            filename = entry.get("filename")
            subfolder = entry.get("subfolder") or ""
            if not filename:
                continue
            local_path = os.path.join(self.output_dir, subfolder, filename)
            _, s3_keys = s3_helpers.resolve_unique_output_filenames(subfolder, [filename])
            s3_key = s3_keys[0]
            s3_helpers.upload_file(local_path, s3_key, content_type="image/png")
        return results


class LoadVideoUploadS3:
    @classmethod
    def INPUT_TYPES(s):
        try:
            config = s3_helpers.get_config()
            keys = s3_helpers.list_media_keys(config.input_prefix, VIDEO_EXTENSIONS)
        except Exception:
            keys = []
        return {
            "required": {
                "video": (sorted(keys), {"video_upload": True}),
                "force_rate": (vhs_load_video.floatOrInt, {"default": 0, "min": 0, "max": 60, "step": 1, "disable": 0}),
                "custom_width": ("INT", {"default": 0, "min": 0, "max": vhs_load_video.DIMMAX, "disable": 0}),
                "custom_height": ("INT", {"default": 0, "min": 0, "max": vhs_load_video.DIMMAX, "disable": 0}),
                "frame_load_cap": ("INT", {"default": 0, "min": 0, "max": vhs_load_video.BIGMAX, "step": 1, "disable": 0}),
                "skip_first_frames": ("INT", {"default": 0, "min": 0, "max": vhs_load_video.BIGMAX, "step": 1}),
                "select_every_nth": ("INT", {"default": 1, "min": 1, "max": vhs_load_video.BIGMAX, "step": 1}),
            },
            "optional": {
                "meta_batch": ("VHS_BatchManager",),
                "vae": ("VAE",),
                "format": vhs_load_video.get_load_formats(),
            },
            "hidden": {
                "force_size": "STRING",
                "unique_id": "UNIQUE_ID",
            },
        }

    CATEGORY = "video"

    RETURN_TYPES = (vhs_load_video.imageOrLatent, "INT", "AUDIO", "VHS_VIDEOINFO")
    RETURN_NAMES = ("IMAGE", "frame_count", "audio", "video_info")
    FUNCTION = "load_video"

    def load_video(self, **kwargs):
        video = kwargs.get("video")
        name = _strip_annotation(video)
        local_path = _resolve_local_path(video)
        if os.path.exists(local_path):
            s3_key = s3_helpers.input_key_for(name)
            s3_helpers.upload_file(local_path, s3_key, content_type=s3_helpers.content_type_for_path(local_path))
            video_path = local_path
        else:
            s3_key = s3_helpers.resolve_input_key(name)
            video_path = s3_helpers.download_to_cache(s3_key)
        kwargs["video"] = video_path
        return vhs_load_video.load_video(**kwargs)

    @classmethod
    def IS_CHANGED(s, video, **kwargs):
        name = _strip_annotation(video)
        local_path = _resolve_local_path(video)
        if os.path.exists(local_path):
            return vhs_load_video.calculate_file_hash(local_path)
        s3_key = s3_helpers.resolve_input_key(name)
        try:
            head = s3_helpers.head_object(s3_key)
            etag = head.get("ETag", "").strip('"')
            return f"{s3_key}:{etag}"
        except FileNotFoundError:
            return s3_key

    @classmethod
    def VALIDATE_INPUTS(s, video):
        name = _strip_annotation(video)
        local_path = _resolve_local_path(video)
        if os.path.exists(local_path):
            return True
        s3_key = s3_helpers.resolve_input_key(name)
        if not s3_helpers.object_exists(s3_key):
            return f"Invalid video file: {video}"
        return True


class VideoCombineS3(vhs_nodes.VideoCombine):
    CATEGORY = "video"

    def combine_video(self, *args, **kwargs):
        result = super().combine_video(*args, **kwargs)
        if not isinstance(result, dict):
            return result
        res_tuple = result.get("result")
        if not res_tuple:
            return result
        save_output, output_files = res_tuple[0]
        if output_files:
            seen = set()
            download_entries = []
            for file_path in output_files[1:]:
                entry = _download_entry_for_file(file_path)
                if not entry:
                    continue
                key = (entry["type"], entry["subfolder"], entry["filename"])
                if key in seen:
                    continue
                seen.add(key)
                download_entries.append(entry)
            if download_entries:
                ui = result.get("ui") or {}
                ui.setdefault("downloads", []).extend(download_entries)
                result["ui"] = ui
        if not save_output:
            return result
        output_root = folder_paths.get_output_directory()
        grouped_files = {}
        for file_path in output_files:
            if not os.path.exists(file_path):
                continue
            subfolder = os.path.relpath(os.path.dirname(file_path), output_root)
            if subfolder == ".":
                subfolder = ""
            filename = os.path.basename(file_path)
            stem, _ = os.path.splitext(filename)
            group_stem = stem[:-6] if stem.endswith("-audio") else stem
            grouped_files.setdefault((subfolder, group_stem), []).append((file_path, filename))

        for (subfolder, _), entries in grouped_files.items():
            filenames = [entry[1] for entry in entries]
            _, s3_keys = s3_helpers.resolve_unique_output_filenames(subfolder, filenames)
            for (file_path, _), s3_key in zip(entries, s3_keys):
                s3_helpers.upload_file(
                    file_path,
                    s3_key,
                    content_type=s3_helpers.content_type_for_path(file_path),
                )
        return result


NODE_CLASS_MAPPINGS = {
    "LoadImageS3": LoadImageS3,
    "SaveImageS3": SaveImageS3,
    "LoadVideoUploadS3": LoadVideoUploadS3,
    "VideoCombineS3": VideoCombineS3,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "LoadImageS3": "Load Image from S3",
    "SaveImageS3": "Save Image to S3",
    "LoadVideoUploadS3": "Load Video (Upload) from S3",
    "VideoCombineS3": "Video Combine to S3",
}
