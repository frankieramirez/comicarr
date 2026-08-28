#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Validation, normalization, and safe storage for Library Chat images."""

import base64
import io
import re
import shutil
import uuid
import warnings
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

import comicarr
from comicarr import logger

MAX_IMAGES = 4
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
MAX_LONG_EDGE = 2048
MAX_FILENAME_LENGTH = 120
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}

_UNSAFE_FILENAME_CHARS = re.compile(r'[\x00-\x1f\x7f"]')


class InvalidChatImage(ValueError):
    pass


def safe_filename(filename):
    """Reduce an uploaded filename to a bare, printable, length-capped name."""
    name = (filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = _UNSAFE_FILENAME_CHARS.sub("_", name).strip()
    return name[:MAX_FILENAME_LENGTH] or "image"


def attachment_root():
    return Path(comicarr.DATA_DIR).resolve() / "chat_attachments"


def resolve_relative_path(relative_path):
    expected_root = attachment_root()
    candidate = (Path(comicarr.DATA_DIR).resolve() / relative_path).resolve()
    if not candidate.is_relative_to(expected_root):
        raise InvalidChatImage("Invalid attachment path")
    return candidate


async def save_uploads(thread_id, uploads):
    if len(uploads) > MAX_IMAGES:
        raise InvalidChatImage("A maximum of 4 images is allowed")

    saved = []
    written = []
    try:
        for upload in uploads:
            raw = await upload.read(MAX_IMAGE_BYTES + 1)
            if len(raw) > MAX_IMAGE_BYTES:
                raise InvalidChatImage("Each image must be 10 MB or smaller")
            if not raw:
                raise InvalidChatImage("Images must not be empty")

            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("error", Image.DecompressionBombWarning)
                    with Image.open(io.BytesIO(raw)) as probe:
                        if probe.format not in ALLOWED_FORMATS:
                            raise InvalidChatImage("Only JPEG, PNG, and WebP images are supported")
                        if probe.width * probe.height > MAX_IMAGE_PIXELS:
                            raise InvalidChatImage("Image dimensions are too large")
                        if getattr(probe, "n_frames", 1) != 1:
                            raise InvalidChatImage("Animated images are not supported")
                        probe.verify()
                    with Image.open(io.BytesIO(raw)) as source:
                        source.seek(0)
                        image = ImageOps.exif_transpose(source)
                        image.load()
                        image.thumbnail((MAX_LONG_EDGE, MAX_LONG_EDGE), Image.Resampling.LANCZOS)
                        if image.mode not in ("RGB", "RGBA"):
                            image = image.convert("RGBA" if "transparency" in image.info else "RGB")
                        normalized = image.copy()
            except InvalidChatImage:
                raise
            except (Image.DecompressionBombError, Image.DecompressionBombWarning):
                raise InvalidChatImage("Image dimensions are too large") from None
            except (UnidentifiedImageError, OSError, SyntaxError, ValueError):
                raise InvalidChatImage("Image is corrupt or unsupported") from None

            attachment_id = uuid.uuid4().hex
            relative_path = Path("chat_attachments") / thread_id / (attachment_id + ".webp")
            path = resolve_relative_path(str(relative_path))
            path.parent.mkdir(parents=True, exist_ok=True)
            written.append(str(relative_path))
            normalized.save(path, format="WEBP", quality=88, method=4, exif=b"")
            saved.append(
                {
                    "id": attachment_id,
                    "filename": safe_filename(upload.filename),
                    "media_type": "image/webp",
                    "byte_size": path.stat().st_size,
                    "width": normalized.width,
                    "height": normalized.height,
                    "relative_path": str(relative_path),
                }
            )
    except Exception:
        delete_paths(written)
        raise
    return saved


def delete_paths(relative_paths):
    failed = []
    for relative_path in relative_paths:
        try:
            path = resolve_relative_path(relative_path)
            path.unlink(missing_ok=True)
            try:
                path.parent.rmdir()
            except OSError:
                pass
        except (OSError, InvalidChatImage) as e:
            failed.append(relative_path)
            logger.error("[AI-CHAT] Failed to delete attachment %s: %s" % (relative_path, e))
    return failed


def quarantine_thread(thread_id):
    """Atomically hide a thread directory so database deletion can be rolled back."""
    source = resolve_relative_path(str(Path("chat_attachments") / thread_id))
    if not source.exists():
        return None
    quarantine_root = attachment_root() / ".trash"
    quarantine_root.mkdir(parents=True, exist_ok=True)
    target = quarantine_root / uuid.uuid4().hex
    source.replace(target)
    return source, target


def restore_quarantine(quarantine):
    if quarantine is None:
        return
    source, target = quarantine
    if target.exists():
        source.parent.mkdir(parents=True, exist_ok=True)
        target.replace(source)


def delete_quarantine(quarantine):
    if quarantine is None:
        return True
    _, target = quarantine
    try:
        shutil.rmtree(target)
        return True
    except OSError as e:
        logger.error("[AI-CHAT] Failed to remove quarantined thread attachments %s: %s" % (target, e))
        return False


def as_data_url(relative_path):
    path = resolve_relative_path(relative_path)
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return "data:image/webp;base64," + encoded
