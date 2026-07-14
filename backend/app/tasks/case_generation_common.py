from __future__ import annotations

import json
import os
import re
import uuid
import zipfile
from pathlib import Path


def make_writable_file(path: str) -> str:
    try:
        os.chmod(path, 0o666)
    except OSError:
        pass
    return path


def validate_xmindmark(text: str) -> None:
    lines = text.splitlines()
    if not lines:
        raise ValueError("XMindMark 内容为空")
    if lines[0].startswith("- "):
        raise ValueError("XMindMark 第一行必须是根节点纯文本")
    for index, line in enumerate(lines[1:], start=2):
        if not line.strip():
            raise ValueError(f"XMindMark 第 {index} 行为空行")
        if not line.startswith("- ") and not re.match(r"^(  )+- ", line):
            raise ValueError(f"XMindMark 第 {index} 行不是标准列表节点")
        indent = len(line) - len(line.lstrip(" "))
        if indent % 2 != 0:
            raise ValueError(f"XMindMark 第 {index} 行缩进不是 2 空格倍数")
        if line.lstrip().startswith("#"):
            raise ValueError(f"XMindMark 第 {index} 行不能使用 Markdown 标题")


def _topic(title: str) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "class": "topic",
        "title": title,
        "titleUnedited": True,
        "boundaries": [],
        "summaries": [],
    }


def _default_theme() -> dict:
    return {
        "id": "f8c8e44f-4a4d-43a7-8381-11a152eaf8a3",
        "centralTopic": {
            "id": "c5069014-b642-4cf5-bb50-1d29bd0df2a1",
            "properties": {
                "svg:fill": "#000229",
                "line-color": "#000229",
                "shape-class": "org.xmind.topicShape.roundedRect",
                "line-class": "org.xmind.branchConnection.curve",
                "line-width": "3pt",
                "line-pattern": "solid",
                "fill-pattern": "solid",
                "border-line-width": "0pt",
                "arrow-end-class": "org.xmind.arrowShape.none",
                "alignment-by-level": "inactived",
                "fo:font-family": "NeverMind",
                "fo:font-style": "normal",
                "fo:font-weight": 500,
                "fo:font-size": "30pt",
                "fo:text-transform": "manual",
                "fo:text-decoration": "none",
                "fo:text-align": "center",
            },
        },
        "mainTopic": {
            "id": "70cef26a-bf8a-4a75-a3ba-c39b54a6401d",
            "properties": {
                "shape-class": "org.xmind.topicShape.roundedRect",
                "line-class": "org.xmind.branchConnection.roundedElbow",
                "line-width": "2pt",
                "fill-pattern": "solid",
                "border-line-width": "0pt",
                "fo:font-family": "NeverMind",
                "fo:font-style": "normal",
                "fo:font-weight": 500,
                "fo:font-size": "18pt",
                "fo:text-transform": "manual",
                "fo:text-decoration": "none",
                "fo:text-align": "left",
            },
        },
        "subTopic": {
            "id": "d5c7d9c0-e954-4c99-9e01-91cccd629c22",
            "properties": {
                "shape-class": "org.xmind.topicShape.roundedRect",
                "line-class": "org.xmind.branchConnection.roundedElbow",
                "line-width": "2pt",
                "fill-pattern": "solid",
                "border-line-width": "0pt",
                "fo:font-family": "NeverMind",
                "fo:font-style": "normal",
                "fo:font-weight": 400,
                "fo:font-size": "14pt",
                "fo:text-transform": "manual",
                "fo:text-decoration": "none",
                "fo:text-align": "left",
            },
        },
        "summaryTopic": {
            "id": "dc5d147f-2c2a-423f-8d4f-26c6e4cdc4ec",
            "properties": {
                "svg:fill": "none",
                "border-line-color": "#000229",
                "shape-class": "org.xmind.topicShape.roundedRect",
                "line-class": "org.xmind.branchConnection.roundedElbow",
                "fill-pattern": "solid",
                "fo:font-family": "NeverMind",
                "fo:font-style": "normal",
                "fo:font-weight": "400",
                "fo:font-size": "14pt",
                "fo:text-transform": "manual",
                "fo:text-decoration": "none",
                "fo:text-align": "left",
            },
        },
        "calloutTopic": {
            "id": "b2ccd2cb-e4d0-4c1d-8615-fea7a1b98854",
            "properties": {
                "svg:fill": "#000229",
                "border-line-color": "#000229",
                "callout-shape-class": "org.xmind.calloutTopicShape.balloon.roundedRect",
                "fill-pattern": "solid",
                "fo:font-family": "NeverMind",
                "fo:font-style": "normal",
                "fo:font-weight": 400,
                "fo:font-size": "14pt",
                "fo:text-transform": "manual",
                "fo:text-decoration": "none",
                "fo:text-align": "left",
            },
        },
        "floatingTopic": {
            "id": "1db99452-2bb0-4de8-87f5-cdeb8a591d7b",
            "properties": {
                "svg:fill": "#EEEBEE",
                "border-line-color": "#EEEBEE",
                "shape-class": "org.xmind.topicShape.roundedRect",
                "line-class": "org.xmind.branchConnection.roundedElbow",
                "line-width": "2pt",
                "line-pattern": "solid",
                "fill-pattern": "solid",
                "border-line-width": "0pt",
                "arrow-end-class": "org.xmind.arrowShape.none",
                "fo:font-family": "NeverMind",
                "fo:font-style": "normal",
                "fo:font-weight": 500,
                "fo:font-size": "14pt",
                "fo:text-transform": "manual",
                "fo:text-decoration": "none",
                "fo:text-align": "left",
            },
        },
        "boundary": {
            "id": "beaff7ce-691f-481d-847c-c5f43d125660",
            "properties": {
                "svg:fill": "#000229",
                "line-color": "#000229",
                "shape-class": "org.xmind.boundaryShape.roundedRect",
                "shape-corner": "20pt",
                "line-width": "2",
                "line-pattern": "dash",
                "fill-pattern": "solid",
                "fo:font-family": "'NeverMind','Microsoft YaHei','PingFang SC','Microsoft JhengHei','sans-serif',sans-serif",
                "fo:font-style": "normal",
                "fo:font-weight": 400,
                "fo:font-size": "14pt",
                "fo:text-transform": "manual",
                "fo:text-decoration": "none",
                "fo:text-align": "center",
            },
        },
        "summary": {
            "id": "7e7d8704-9339-4a37-a8dc-f3a3aa2f4cf2",
            "properties": {
                "line-color": "#000229",
                "shape-class": "org.xmind.summaryShape.round",
                "line-width": "2pt",
                "line-pattern": "solid",
                "line-corner": "8pt",
            },
        },
        "relationship": {
            "id": "81c8d0be-6082-4a1c-b88c-23b1445e0647",
            "properties": {
                "line-color": "#000229",
                "shape-class": "org.xmind.relationshipShape.curved",
                "line-width": "2",
                "line-pattern": "dash",
                "arrow-begin-class": "org.xmind.arrowShape.none",
                "arrow-end-class": "org.xmind.arrowShape.triangle",
                "fo:font-family": "'NeverMind','Microsoft YaHei','PingFang SC','Microsoft JhengHei','sans-serif',sans-serif",
                "fo:font-style": "normal",
                "fo:font-weight": 400,
                "fo:font-size": "13pt",
                "fo:text-transform": "manual",
                "fo:text-decoration": "none",
                "fo:text-align": "center",
            },
        },
        "map": {
            "id": "ea5bbe08-7b7a-4b13-a4ee-49b20dcc4de2",
            "properties": {
                "svg:fill": "#ffffff",
                "multi-line-colors": "#F9423A #F6A04D #F3D321 #00BC7B #486AFF #4D49BE",
                "color-list": "#000229 #1F2766 #52CC83 #4D86DB #99142F #245570",
                "line-tapered": "none",
            },
        },
        "importantTopic": {
            "id": "6c4e5a0a-db82-4dc6-9816-213ad1a38238",
            "properties": {"svg:fill": "#460400", "fill-pattern": "solid", "border-line-color": "#460400"},
        },
        "minorTopic": {
            "id": "febf0c47-d75e-4149-a07f-a44cf847e7ab",
            "properties": {"svg:fill": "#703D00", "fill-pattern": "solid", "border-line-color": "#703D00"},
        },
        "colorThemeId": "Rainbow-#000229-MULTI_LINE_COLORS",
        "expiredTopic": {
            "id": "c2afd293-7843-4ca4-b01f-4353768628ea",
            "properties": {"fo:text-decoration": "line-through", "svg:fill": "none"},
        },
        "global": {"id": "53109c3b-6577-4e2d-bd2e-b768723f6436", "properties": {}},
        "skeletonThemeId": "db4a5df4db39a8cd1310ea55ea",
    }


def xmindmark_to_content(text: str) -> list[dict]:
    validate_xmindmark(text)
    lines = text.splitlines()
    root = _topic(lines[0].strip())
    root["structureClass"] = "org.xmind.ui.logic.right"
    stack: list[tuple[int, dict]] = [(-1, root)]

    for line in lines[1:]:
        indent = len(line) - len(line.lstrip(" "))
        level = indent // 2
        title = line.lstrip()[2:].strip()
        topic = _topic(title)
        while stack and stack[-1][0] >= level:
            stack.pop()
        parent = stack[-1][1]
        parent.setdefault("children", {}).setdefault("attached", []).append(topic)
        stack.append((level, topic))

    if not root.get("children", {}).get("attached"):
        raise RuntimeError("XMind 内容生成失败：根节点没有子节点")
    return [
        {
            "id": str(uuid.uuid4()),
            "class": "sheet",
            "title": root["title"],
            "rootTopic": root,
            "topicPositioning": "fixed",
            "relationships": [],
            "theme": _default_theme(),
            "extensions": [
                {
                    "provider": "org.xmind.ui.skeleton.structure.style",
                    "content": {
                        "centralTopic": "org.xmind.ui.map.clockwise",
                        "mainTopic": "org.xmind.ui.logic.right",
                    },
                }
            ],
        }
    ]


def write_xmind_archive(xmind_path: str, xmindmark_text: str) -> str:
    content = xmindmark_to_content(xmindmark_text)
    manifest = {"file-entries": {"content.json": {}, "metadata.json": {}}}
    metadata = {
        "creator": {"name": "OmniTest deterministic exporter", "version": "1"},
        "format": "xmind-zen-json",
    }
    with zipfile.ZipFile(xmind_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("content.json", json.dumps(content, ensure_ascii=False))
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
        archive.writestr("metadata.json", json.dumps(metadata, ensure_ascii=False))
    return make_writable_file(xmind_path)


def inspect_xmind_archive(xmind_path: str) -> dict:
    """Parse the delivered XMind archive and recompute its structural counts."""
    if not os.path.isfile(xmind_path):
        raise ValueError(f"XMind 文件不存在：{xmind_path}")
    try:
        with zipfile.ZipFile(xmind_path, "r") as archive:
            names = set(archive.namelist())
            required = {"content.json", "manifest.json", "metadata.json"}
            missing = sorted(required - names)
            if missing:
                raise ValueError(f"XMind 缺少必要文件：{', '.join(missing)}")
            content = json.loads(archive.read("content.json").decode("utf-8"))
    except (zipfile.BadZipFile, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"XMind 文件无法解析：{exc}") from exc
    if not isinstance(content, list) or not content:
        raise ValueError("XMind content.json 必须是非空工作表数组")
    root = content[0].get("rootTopic") if isinstance(content[0], dict) else None
    if not isinstance(root, dict) or not str(root.get("title") or "").strip():
        raise ValueError("XMind 根主题为空")
    if not ((root.get("children") or {}).get("attached") or []):
        raise ValueError("XMind 根主题没有子节点")

    titles: list[str] = []

    def visit(topic: dict) -> None:
        title = str(topic.get("title") or "").strip()
        if title:
            titles.append(title)
        for child in ((topic.get("children") or {}).get("attached") or []):
            if isinstance(child, dict):
                visit(child)

    visit(root)
    counts = {}
    for prefix in ("SRC", "FP", "TC"):
        pattern = re.compile(rf"\b{prefix}-[A-Za-z0-9_-]+")
        counts[prefix.lower()] = len({match.group(0) for title in titles for match in pattern.finditer(title)})
    return {
        "root_title": str(root.get("title") or "").strip(),
        "topic_count": len(titles),
        "source_count": counts["src"],
        "function_point_count": counts["fp"],
        "testcase_count": counts["tc"],
        "file_size": os.path.getsize(xmind_path),
    }


def convert_xmindmark_to_xmind(output_dir: str, xmindmark_file_path: str, output_stem: str) -> str:
    final_path = os.path.join(output_dir, f"{output_stem}.xmind")
    for path in {final_path, os.path.join(output_dir, ".xmind")}:
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                make_writable_file(path)
                os.remove(path)
    text = Path(xmindmark_file_path).read_text(encoding="utf-8")
    return write_xmind_archive(final_path, text)
