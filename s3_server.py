import os

import folder_paths
import node_helpers
import server

from . import s3_helpers


web = server.web


def _safe_subfolder(value: str) -> str:
    if not value:
        return ""
    normalized = os.path.normpath(value).replace("\\", "/")
    if normalized in ("", "."):
        return ""
    if normalized.startswith("../") or normalized.startswith("..") or normalized.startswith("/"):
        raise ValueError("Invalid subfolder")
    return normalized


def _compare_file_hash(filepath: str, payload) -> bool:
    hasher = node_helpers.hasher()
    if os.path.exists(filepath):
        local = hasher()
        uploaded = hasher()
        with open(filepath, "rb") as handle:
            local.update(handle.read())
            uploaded.update(payload.file.read())
            payload.file.seek(0)
        return local.hexdigest() == uploaded.hexdigest()
    return False


@server.PromptServer.instance.routes.post("/s3io/upload/image")
async def upload_image_to_s3(request):
    post = await request.post()
    image = post.get("image")
    overwrite = post.get("overwrite")

    if image is None or not getattr(image, "file", None):
        return web.Response(status=400)

    filename = os.path.basename(image.filename or "")
    if not filename:
        return web.Response(status=400)

    try:
        subfolder = _safe_subfolder(post.get("subfolder", ""))
    except ValueError:
        return web.Response(status=400)

    upload_dir = folder_paths.get_input_directory()
    full_output_folder = os.path.join(upload_dir, subfolder)
    filepath = os.path.abspath(os.path.join(full_output_folder, filename))

    if os.path.commonpath((upload_dir, filepath)) != upload_dir:
        return web.Response(status=400)

    if not os.path.exists(full_output_folder):
        os.makedirs(full_output_folder)

    split = os.path.splitext(filename)
    image_is_duplicate = False

    if overwrite is not None and (overwrite == "true" or overwrite == "1"):
        pass
    else:
        i = 1
        while True:
            local_exists = os.path.exists(filepath)
            if local_exists and _compare_file_hash(filepath, image):
                image_is_duplicate = True
                break
            rel_name = os.path.join(subfolder, filename) if subfolder else filename
            if not local_exists and not s3_helpers.object_exists(s3_helpers.input_key_for(rel_name)):
                break
            filename = f"{split[0]} ({i}){split[1]}"
            filepath = os.path.join(full_output_folder, filename)
            i += 1

    if not image_is_duplicate:
        with open(filepath, "wb") as handle:
            handle.write(image.file.read())

    rel_name = os.path.join(subfolder, filename) if subfolder else filename
    s3_key = s3_helpers.input_key_for(rel_name)
    s3_helpers.upload_file(
        filepath,
        s3_key,
        content_type=s3_helpers.content_type_for_path(filepath),
    )
    s3_helpers.ensure_thumbnail(filepath, s3_key)
    s3_helpers.invalidate_list_cache()

    return web.json_response({"name": filename, "subfolder": subfolder, "type": "input"})


@server.PromptServer.instance.routes.post("/s3io/upload/video")
async def upload_video_to_s3(request):
    post = await request.post()
    video = post.get("video") or post.get("image")
    overwrite = post.get("overwrite")

    if video is None or not getattr(video, "file", None):
        return web.Response(status=400)

    filename = os.path.basename(video.filename or "")
    if not filename:
        return web.Response(status=400)

    try:
        subfolder = _safe_subfolder(post.get("subfolder", ""))
    except ValueError:
        return web.Response(status=400)

    upload_dir = folder_paths.get_input_directory()
    full_output_folder = os.path.join(upload_dir, subfolder)
    filepath = os.path.abspath(os.path.join(full_output_folder, filename))

    if os.path.commonpath((upload_dir, filepath)) != upload_dir:
        return web.Response(status=400)

    if not os.path.exists(full_output_folder):
        os.makedirs(full_output_folder)

    split = os.path.splitext(filename)
    video_is_duplicate = False

    if overwrite is not None and (overwrite == "true" or overwrite == "1"):
        pass
    else:
        i = 1
        while True:
            local_exists = os.path.exists(filepath)
            if local_exists and _compare_file_hash(filepath, video):
                video_is_duplicate = True
                break
            rel_name = os.path.join(subfolder, filename) if subfolder else filename
            if not local_exists and not s3_helpers.object_exists(s3_helpers.input_key_for(rel_name)):
                break
            filename = f"{split[0]} ({i}){split[1]}"
            filepath = os.path.join(full_output_folder, filename)
            i += 1

    if not video_is_duplicate:
        with open(filepath, "wb") as handle:
            handle.write(video.file.read())

    rel_name = os.path.join(subfolder, filename) if subfolder else filename
    s3_key = s3_helpers.input_key_for(rel_name)
    s3_helpers.upload_file(
        filepath,
        s3_key,
        content_type=s3_helpers.content_type_for_path(filepath),
    )
    s3_helpers.invalidate_list_cache()

    return web.json_response({"name": filename, "subfolder": subfolder, "type": "input"})
