from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import httpx

from app.core.config import settings


class UnsafeURL(ValueError):
    pass


class DownloadTooLarge(ValueError):
    pass


@dataclass(frozen=True)
class FetchedResource:
    url: str
    content: bytes
    content_type: str


def _validate_resolved_addresses(hostname: str) -> None:
    try:
        addresses = {
            item[4][0]
            for item in socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
        }
    except socket.gaierror as exc:
        raise UnsafeURL(f"无法解析下载地址：{hostname}") from exc
    if not addresses:
        raise UnsafeURL(f"下载地址没有可用 IP：{hostname}")
    if settings.case_gen_allow_private_urls:
        return
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise UnsafeURL(f"下载地址解析到受限网络：{hostname} -> {ip}")


def validate_public_http_url(url: str) -> str:
    normalized = str(url or "").strip()
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"}:
        raise UnsafeURL("仅允许 http/https 下载地址")
    if not parsed.hostname:
        raise UnsafeURL("下载地址缺少主机名")
    if parsed.username or parsed.password:
        raise UnsafeURL("下载地址不能包含用户名或密码")
    _validate_resolved_addresses(parsed.hostname)
    return normalized


def _validate_content_type(content_type: str, accepted_prefixes: tuple[str, ...], url: str) -> None:
    normalized = content_type.split(";", 1)[0].strip().lower()
    if any(normalized.startswith(prefix) for prefix in accepted_prefixes):
        return
    if "application/octet-stream" == normalized and urlparse(url).path.lower().endswith((".md", ".txt")):
        return
    raise ValueError(f"下载内容类型不受支持：{content_type or 'unknown'}")


def fetch_resource(
    url: str,
    *,
    max_bytes: int,
    accepted_prefixes: tuple[str, ...],
    timeout_seconds: float,
    max_redirects: int = 5,
) -> FetchedResource:
    current_url = validate_public_http_url(url)
    with httpx.Client(follow_redirects=False, timeout=timeout_seconds) as client:
        for _ in range(max_redirects + 1):
            with client.stream("GET", current_url, headers={"User-Agent": "OmniTest/1.1"}) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        raise ValueError("下载重定向缺少 Location")
                    current_url = validate_public_http_url(urljoin(current_url, location))
                    continue
                response.raise_for_status()
                content_type = response.headers.get("content-type", "")
                _validate_content_type(content_type, accepted_prefixes, current_url)
                declared = response.headers.get("content-length")
                if declared and declared.isdigit() and int(declared) > max_bytes:
                    raise DownloadTooLarge(f"下载内容超过 {max_bytes} 字节限制")
                chunks: list[bytes] = []
                size = 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > max_bytes:
                        raise DownloadTooLarge(f"下载内容超过 {max_bytes} 字节限制")
                    chunks.append(chunk)
                return FetchedResource(current_url, b"".join(chunks), content_type)
    raise ValueError(f"下载重定向超过 {max_redirects} 次")


async def fetch_resource_async(
    client: httpx.AsyncClient,
    url: str,
    *,
    max_bytes: int,
    accepted_prefixes: tuple[str, ...],
    max_redirects: int = 5,
) -> FetchedResource:
    current_url = validate_public_http_url(url)
    for _ in range(max_redirects + 1):
        async with client.stream(
            "GET",
            current_url,
            headers={"User-Agent": "OmniTest/1.1"},
            follow_redirects=False,
        ) as response:
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location")
                if not location:
                    raise ValueError("图片重定向缺少 Location")
                current_url = validate_public_http_url(urljoin(current_url, location))
                continue
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            _validate_content_type(content_type, accepted_prefixes, current_url)
            declared = response.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > max_bytes:
                raise DownloadTooLarge(f"下载内容超过 {max_bytes} 字节限制")
            chunks: list[bytes] = []
            size = 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > max_bytes:
                    raise DownloadTooLarge(f"下载内容超过 {max_bytes} 字节限制")
                chunks.append(chunk)
            return FetchedResource(current_url, b"".join(chunks), content_type)
    raise ValueError(f"图片重定向超过 {max_redirects} 次")
