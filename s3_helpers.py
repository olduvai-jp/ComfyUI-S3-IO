import hashlib
import os
import time
from dataclasses import dataclass
from typing import Iterable, Optional

import boto3
from botocore.exceptions import ClientError
from PIL import Image, ImageOps

import folder_paths


LIST_CACHE_TTL_SECONDS = 0
THUMB_MAX_SIZE = 256
THUMB_PREFIX_DEFAULT = "thumbs"
ENV_PREFIX = "S3IO_"
LEGACY_ENV_PREFIX = "S3_"
ENV_KEYS = (
    "ACCESS_KEY_ID",
    "SECRET_ACCESS_KEY",
    "BUCKET",
    "ENDPOINT_URL",
    "REGION",
    "INPUT_PREFIX",
    "OUTPUT_PREFIX",
    "THUMB_PREFIX",
)


@dataclass(frozen=True)
class S3Config:
    endpoint: Optional[str]
    region: Optional[str]
    access_key: str
    secret_key: str
    bucket: str
    input_prefix: str
    output_prefix: str
    thumb_prefix: str


_list_cache: dict[str, tuple[float, list[str]]] = {}
_force_refresh = False
_cached_client = None
_cached_config: Optional[S3Config] = None


def _normalize_prefix(prefix: Optional[str]) -> str:
    if not prefix:
        return ""
    return prefix.strip("/") + "/"


def _join_prefix(prefix: str, key: str) -> str:
    if not prefix:
        return key.lstrip("/")
    return prefix.rstrip("/") + "/" + key.lstrip("/")


def _strip_prefix(key: str, prefix: str) -> str:
    if prefix and key.startswith(prefix):
        return key[len(prefix):]
    return key


def _read_text_file(path: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read().strip()
    except FileNotFoundError:
        return None


def _write_text_file(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(content)


def _get_cache_dir() -> str:
    base_dir = folder_paths.get_temp_directory()
    cache_dir = os.path.join(base_dir, "s3-io")
    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir


def _cache_path_for_key(key: str, kind: str) -> str:
    safe_key = key.replace("/", os.sep)
    return os.path.join(_get_cache_dir(), kind, safe_key)


def _etag_path_for_cache(cache_path: str) -> str:
    return cache_path + ".etag"


def _content_type_for_extension(path: str) -> Optional[str]:
    ext = os.path.splitext(path)[1].lower()
    if ext in (".jpg", ".jpeg"):
        return "image/jpeg"
    if ext == ".png":
        return "image/png"
    if ext == ".webp":
        return "image/webp"
    if ext == ".gif":
        return "image/gif"
    if ext == ".mp4":
        return "video/mp4"
    if ext == ".mov":
        return "video/quicktime"
    if ext == ".webm":
        return "video/webm"
    if ext == ".mkv":
        return "video/x-matroska"
    return None


def content_type_for_path(path: str) -> Optional[str]:
    return _content_type_for_extension(path)


def _resolve_config() -> S3Config:
    global _cached_config
    if _cached_config is not None:
        return _cached_config
    prefixed_names = [ENV_PREFIX + key for key in ENV_KEYS]
    env_prefix = ENV_PREFIX if any(name in os.environ for name in prefixed_names) else LEGACY_ENV_PREFIX
    def env(name: str) -> Optional[str]:
        return os.environ.get(env_prefix + name)
    missing = []
    access_key = env("ACCESS_KEY_ID")
    secret_key = env("SECRET_ACCESS_KEY")
    bucket = env("BUCKET")
    if not access_key:
        missing.append(env_prefix + "ACCESS_KEY_ID")
    if not secret_key:
        missing.append(env_prefix + "SECRET_ACCESS_KEY")
    if not bucket:
        missing.append(env_prefix + "BUCKET")
    if missing:
        raise RuntimeError("Missing S3 IO configuration: " + ", ".join(missing))
    config = S3Config(
        endpoint=env("ENDPOINT_URL") or None,
        region=env("REGION") or None,
        access_key=access_key,
        secret_key=secret_key,
        bucket=bucket,
        input_prefix=_normalize_prefix(env("INPUT_PREFIX")),
        output_prefix=_normalize_prefix(env("OUTPUT_PREFIX")),
        thumb_prefix=_normalize_prefix(env("THUMB_PREFIX") or THUMB_PREFIX_DEFAULT),
    )
    _cached_config = config
    return config


def get_s3_client():
    global _cached_client
    if _cached_client is not None:
        return _cached_client
    config = _resolve_config()
    kwargs = {
        "aws_access_key_id": config.access_key,
        "aws_secret_access_key": config.secret_key,
    }
    if config.region:
        kwargs["region_name"] = config.region
    if config.endpoint:
        kwargs["endpoint_url"] = config.endpoint
    _cached_client = boto3.client("s3", **kwargs)
    return _cached_client


def get_config() -> S3Config:
    return _resolve_config()


def invalidate_list_cache() -> None:
    global _force_refresh
    _force_refresh = True


def list_objects(prefix: str, refresh: bool = False) -> list[str]:
    global _force_refresh
    now = time.time()
    if LIST_CACHE_TTL_SECONDS <= 0:
        refresh = True
    cached = _list_cache.get(prefix)
    if not refresh and not _force_refresh and cached:
        cached_at, keys = cached
        if now - cached_at < LIST_CACHE_TTL_SECONDS:
            return keys
    client = get_s3_client()
    config = _resolve_config()
    keys = []
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=config.bucket, Prefix=prefix):
        for entry in page.get("Contents", []):
            key = entry.get("Key")
            if not key:
                continue
            keys.append(key)
    _list_cache[prefix] = (now, keys)
    _force_refresh = False
    return keys


def list_media_keys(prefix: str, extensions: Iterable[str], refresh: bool = False) -> list[str]:
    normalized_exts = {ext.lower().lstrip(".") for ext in extensions}
    keys = list_objects(prefix, refresh=refresh)
    results = []
    for key in keys:
        if key.endswith("/"):
            continue
        rel = _strip_prefix(key, prefix)
        if not rel:
            continue
        ext = os.path.splitext(rel)[1].lower().lstrip(".")
        if ext in normalized_exts:
            results.append(rel)
    return sorted(results)


def head_object(key: str) -> dict:
    client = get_s3_client()
    config = _resolve_config()
    try:
        return client.head_object(Bucket=config.bucket, Key=key)
    except ClientError as exc:
        raise FileNotFoundError(f"S3 object not found: {key}") from exc


def object_exists(key: str) -> bool:
    try:
        head_object(key)
        return True
    except FileNotFoundError:
        return False


def download_to_cache(key: str, refresh: bool = False, kind: str = "objects") -> str:
    client = get_s3_client()
    config = _resolve_config()
    cache_path = _cache_path_for_key(key, kind)
    etag_path = _etag_path_for_cache(cache_path)
    remote = head_object(key)
    remote_etag = remote.get("ETag", "").strip('"')
    local_etag = _read_text_file(etag_path)
    if refresh or not os.path.exists(cache_path) or (remote_etag and local_etag != remote_etag):
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        client.download_file(config.bucket, key, cache_path)
        if remote_etag:
            _write_text_file(etag_path, remote_etag)
    return cache_path


def upload_file(local_path: str, key: str, content_type: Optional[str] = None, attempts: int = 3) -> None:
    client = get_s3_client()
    config = _resolve_config()
    extra_args = {}
    if content_type:
        extra_args["ContentType"] = content_type
    for attempt in range(attempts):
        try:
            if extra_args:
                client.upload_file(local_path, config.bucket, key, ExtraArgs=extra_args)
            else:
                client.upload_file(local_path, config.bucket, key)
            return
        except ClientError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.5 * (attempt + 1))


def input_key_for(name: str) -> str:
    config = _resolve_config()
    clean = name.lstrip("/")
    return _join_prefix(config.input_prefix, clean)


def resolve_input_key(name: str) -> str:
    config = _resolve_config()
    clean = name.lstrip("/")
    if config.input_prefix and clean.startswith(config.input_prefix):
        return clean
    return _join_prefix(config.input_prefix, clean)


def output_key_for(subfolder: str, filename: str) -> str:
    config = _resolve_config()
    if subfolder:
        return _join_prefix(config.output_prefix, f"{subfolder.strip('/')}/{filename}")
    return _join_prefix(config.output_prefix, filename)


def _apply_suffix(filename: str, suffix: int) -> str:
    if suffix <= 0:
        return filename
    stem, ext = os.path.splitext(filename)
    return f"{stem} ({suffix}){ext}"


def resolve_unique_output_filenames(subfolder: str, filenames: Iterable[str]) -> tuple[list[str], list[str]]:
    names = list(filenames)
    suffix = 0
    while True:
        candidate_names = [_apply_suffix(name, suffix) for name in names]
        candidate_keys = [output_key_for(subfolder, name) for name in candidate_names]
        if not any(object_exists(key) for key in candidate_keys):
            return candidate_names, candidate_keys
        suffix += 1


def thumb_key_for(source_key: str) -> str:
    config = _resolve_config()
    base, _ext = os.path.splitext(source_key)
    return _join_prefix(config.thumb_prefix, base + ".jpg")


def ensure_thumbnail(local_path: str, source_key: str) -> str:
    thumb_key = thumb_key_for(source_key)
    thumb_path = _cache_path_for_key(thumb_key, "thumbs")
    if not os.path.exists(thumb_path):
        os.makedirs(os.path.dirname(thumb_path), exist_ok=True)
        with Image.open(local_path) as img:
            img = ImageOps.exif_transpose(img)
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            img.thumbnail((THUMB_MAX_SIZE, THUMB_MAX_SIZE), Image.LANCZOS)
            img.save(thumb_path, "JPEG", quality=85, optimize=True)
    upload_file(thumb_path, thumb_key, content_type="image/jpeg")
    return thumb_path


def local_temp_preview_path(source_path: str) -> tuple[str, str]:
    temp_dir = folder_paths.get_temp_directory()
    if source_path.startswith(temp_dir):
        rel = os.path.relpath(source_path, temp_dir)
        return os.path.dirname(rel), os.path.basename(rel)
    filename = os.path.basename(source_path)
    preview_dir = os.path.join(temp_dir, "s3-io", "preview")
    os.makedirs(preview_dir, exist_ok=True)
    preview_path = os.path.join(preview_dir, filename)
    if source_path != preview_path:
        if not os.path.exists(preview_path):
            with open(source_path, "rb") as src, open(preview_path, "wb") as dst:
                dst.write(src.read())
    rel = os.path.relpath(preview_path, temp_dir)
    return os.path.dirname(rel), os.path.basename(rel)


def file_hash(path: str) -> str:
    m = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            m.update(chunk)
    return m.digest().hex()
