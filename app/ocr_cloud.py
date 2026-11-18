# -*- coding: utf-8 -*-
"""扉页文字识别——走云端视觉模型。

原来用 macOS 的 Vision 框架，只能在 Mac 上跑；部署到服务器后必须换成云端。
这里调用 WorkBuddy Manager 反代的多模态模型（默认 glm-5.3，5 秒左右，
输出样式最接近原始版面）。macOS 的 Vision 保留作本地兜底。
"""
from __future__ import annotations

import base64
import json
import os
import platform
import re
import urllib.error
import urllib.request
from typing import Dict, List, Optional, Tuple

ENV_FILE = os.path.expanduser("~/.dsh/.env")
ENV_KEY = "MARIO_WORKBUDDY_MANAGER_API_KEY"
GATEWAY = os.environ.get("OCR_GATEWAY", "https://newpower.zjzaki.cn/workbuddy-manager/v1")
DEFAULT_VISION_MODEL = os.environ.get("OCR_MODEL", "cn:glm-5.3")

# 能读图的模型（按优先级）。反代上并非每个都稳定，失败就换下一个。
VISION_MODELS = [
    "cn:glm-5.3",
    "cn:kimi-k3.1-pro",
    "cn:hy4-preview-exp",
    "cn:step-5-preview",
    "cn:deepseek-v4-pro",
]

OCR_PROMPT = (
    "识别这张图片里的全部文字，按图片中的行顺序逐行输出。"
    "只输出识别到的文字本身：不要加任何解释、标题、Markdown 标记或项目符号；"
    "保留每行原有的空格分隔；识别不出的字用 □ 代替。"
)


def _api_key() -> Optional[str]:
    # 环境变量优先（服务器上就是这么注入的）
    for name in ("OCR_API_KEY", ENV_KEY):
        val = os.environ.get(name, "").strip()
        if val:
            return val
    # 本机开发时读 ~/.dsh/.env
    try:
        for line in open(ENV_FILE, encoding="utf-8"):
            if line.startswith(ENV_KEY):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return None


def cloud_available() -> bool:
    return bool(_api_key())


def _guess_mime(data: bytes) -> str:
    if data[:8].startswith(b"\x89PNG"):
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/png"


def _call_vision(model: str, image_b64: str, mime: str, timeout: int = 90) -> str:
    key = _api_key()
    if not key:
        raise RuntimeError("没有可用的视觉模型凭据（MARIO_WORKBUDDY_MANAGER_API_KEY）")
    body = json.dumps({
        "model": model,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": OCR_PROMPT},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image_b64}"}},
            ],
        }],
        "max_tokens": 2000,
        "temperature": 0.0,
    }).encode()
    req = urllib.request.Request(
        f"{GATEWAY}/chat/completions", data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.load(resp)
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError(f"模型没有返回内容：{str(data)[:150]}")
    return (choices[0].get("message") or {}).get("content") or ""


def clean_ocr_text(text: str) -> str:
    """去掉模型爱加的各种包装：Markdown 标记、序号、解释性抬头。"""
    if not text:
        return ""
    # 去掉 ``` 代码块
    text = re.sub(r"```[a-zA-Z]*\n?", "", text)
    lines: List[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        # 去掉行首的 markdown 标记：**、-、*、#、>
        line = re.sub(r"^[#>*\-\s]+", "", line)
        line = line.replace("**", "")
        # 形如「1. 」「1）」的行首编号
        line = re.sub(r"^\d+[\.、)）]\s*", "", line)
        # 「图中文字如下：」这类抬头
        if re.match(r"^(图中|图片|以下|识别|文字)[^\n]{0,12}[：:]$", line):
            continue
        # 冒号改成空格，避免「主审：杨晔琴」被当成一个整体
        line = line.replace("：", " ").replace(":", " ")
        if line:
            lines.append(line)
    return "\n".join(lines)


def ocr_image(image_bytes: bytes) -> Tuple[List[List[str]], str]:
    """识别图片文字，返回 (按行拆好的单元格, 使用的模型名)。

    云端优先；云端不可用时回退到 macOS Vision（仅本机可用）。
    """
    errors: List[str] = []
    if cloud_available():
        b64 = base64.b64encode(image_bytes).decode()
        mime = _guess_mime(image_bytes)
        for model in VISION_MODELS:
            if model != DEFAULT_VISION_MODEL:
                continue  # 只试默认那个，其余的留给显式配置
            try:
                text = clean_ocr_text(_call_vision(model, b64, mime))
                if text.strip():
                    from cover_parser import _rows_from_text  # noqa: PLC0415
                    return _rows_from_text(text), model
                errors.append(f"{model}: 返回空文本")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{model}: {str(exc)[:60]}")
        # 默认模型失败，尝试备选
        for model in VISION_MODELS:
            if model == DEFAULT_VISION_MODEL:
                continue
            try:
                text = clean_ocr_text(_call_vision(model, b64, mime))
                if text.strip():
                    from cover_parser import _rows_from_text  # noqa: PLC0415
                    return _rows_from_text(text), model
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{model}: {str(exc)[:40]}")

    # 兜底：macOS Vision
    if platform.system() == "Darwin":
        try:
            from cover_parser import (  # noqa: PLC0415
                _ensure_ocr_binary, _rows_from_image, OCR_SWIFT,
            )
            import tempfile  # noqa: PLC0415
            if _ensure_ocr_binary() or os.path.exists(OCR_SWIFT):
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
                tmp.write(image_bytes)
                tmp.close()
                try:
                    return _rows_from_image(tmp.name), "macos-vision"
                finally:
                    try:
                        os.unlink(tmp.name)
                    except OSError:
                        pass
        except Exception as exc:  # noqa: BLE001
            errors.append(f"macos-vision: {str(exc)[:40]}")

    hint = "；".join(errors) if errors else "没有可用的识别通道"
    raise RuntimeError(f"图片文字识别失败（{hint}）")


def status() -> Dict:
    return {
        "cloud": cloud_available(),
        "gateway": GATEWAY,
        "model": DEFAULT_VISION_MODEL,
        "local_macos": platform.system() == "Darwin",
    }
