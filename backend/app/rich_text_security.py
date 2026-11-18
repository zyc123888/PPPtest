from __future__ import annotations

import html
import warnings
from io import BytesIO

import nh3
from PIL import Image, UnidentifiedImageError


_ALLOWED_TAGS = {
    "a", "blockquote", "br", "code", "em", "h1", "h2", "h3", "i",
    "img", "li", "ol", "p", "pre", "s", "strike", "strong", "u", "ul",
}
_ALLOWED_ATTRIBUTES = {
    "a": {"href", "target", "title"},
    "img": {"alt", "src", "title"},
}
_IMAGE_FORMAT_EXTENSIONS = {
    "PNG": ".png",
    "JPEG": ".jpg",
    "GIF": ".gif",
    "WEBP": ".webp",
    "BMP": ".bmp",
}


def sanitize_rich_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = nh3.clean(
        value,
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRIBUTES,
        url_schemes={"http", "https"},
        link_rel="noopener noreferrer",
    ).strip()
    return cleaned or None


def plain_text_to_safe_html(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    return "<p>" + html.escape(text).replace("\n", "<br>") + "</p>"


def validate_image_content(data: bytes, declared_extension: str) -> str:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as image:
                detected_format = str(image.format or "").upper()
                image.verify()
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        UnidentifiedImageError,
        OSError,
        ValueError,
    ) as exc:
        raise ValueError("上传内容不是有效图片或图片已损坏") from exc

    detected_extension = _IMAGE_FORMAT_EXTENSIONS.get(detected_format)
    if detected_extension is None:
        raise ValueError("图片真实格式不受支持")
    normalized_declared = ".jpg" if declared_extension.lower() in {".jpg", ".jpeg"} else declared_extension.lower()
    if detected_extension != normalized_declared:
        raise ValueError("图片声明格式与真实内容不一致")
    return detected_extension
