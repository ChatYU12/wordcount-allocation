# -*- coding: utf-8 -*-
"""用大模型做编写分工。

交给模型的是「章节序号」而不是页码——让模型算页码必错，但让它把一串章节
按顺序切成若干段，它做得还不错。页码换算、字数计算、约束校验都在本地完成。

模型输出必须满足：
  * 从第 1 章连续切到最后一章，不跳不重不漏
  * 每位编写人只出现一次，且全部用上
  * 联合编写只能是「主编 + 副主编」
校验不过就把错误回给模型让它重来，最多两次。
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Dict, List, Optional, Tuple

ENV_FILE = os.path.expanduser("~/.dsh/.env")

# 可用的模型提供方。deepseek 走 WorkBuddy Manager 反代，本地 magpie 作备用。
PROVIDERS: Dict[str, Dict[str, str]] = {
    "deepseek": {
        "label": "DeepSeek v4.1",
        "base": "https://newpower.zjzaki.cn/workbuddy-manager/v1",
        "key_env": "MARIO_WORKBUDDY_MANAGER_API_KEY",
        "model": "cn:deepseek-v4.1-flash",
        # 反代网关 60 秒硬超时，留点余量提前放弃，好尽快换备用模型
        "timeout": "35",
    },
    "local": {
        "label": "本地网关 gpt-6-luna",
        "base": "http://127.0.0.1:3425/v1",
        "key_env": "MAGPIE_GATEWAY_KEY",
        "model": "codex/gpt-6-luna",
        "timeout": "120",
    },
}
DEFAULT_PROVIDER = "deepseek"


def _read_env(name: str) -> Optional[str]:
    val = os.environ.get(name, "").strip()
    if val:
        return val
    try:
        for line in open(ENV_FILE, encoding="utf-8"):
            if line.startswith(name):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return None


def _api_key(provider: str = DEFAULT_PROVIDER) -> Optional[str]:
    cfg = PROVIDERS.get(provider) or PROVIDERS[DEFAULT_PROVIDER]
    return _read_env(cfg["key_env"])


def available(provider: str = DEFAULT_PROVIDER) -> bool:
    return bool(_api_key(provider))


def provider_info(provider: str = DEFAULT_PROVIDER) -> Dict[str, str]:
    cfg = PROVIDERS.get(provider) or PROVIDERS[DEFAULT_PROVIDER]
    return {"provider": provider, "label": cfg["label"], "model": cfg["model"]}


def _call_llm(prompt: str, model: str, timeout: int = 0,
              provider: str = DEFAULT_PROVIDER) -> str:
    cfg = PROVIDERS.get(provider) or PROVIDERS[DEFAULT_PROVIDER]
    timeout = timeout or int(cfg.get("timeout") or 120)
    key = _api_key(provider)
    if not key:
        raise RuntimeError(f"没有可用的模型凭据（{cfg['key_env']}）")
    body = json.dumps({
        "model": model or cfg["model"],
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 4000,
        "temperature": 0.1,
    }).encode()
    req = urllib.request.Request(
        f"{cfg['base']}/chat/completions", data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.load(resp)
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError(f"模型没有返回内容：{str(data)[:200]}")
    return (choices[0].get("message") or {}).get("content") or ""


def _build_prompt(units: List[Dict], people: List[Dict], per_page_words: int) -> str:
    total_pages = sum(u["pages"] for u in units)
    lines = [
        f"[{i}] {u['label']}（{u['pages']}页）" for i, u in enumerate(units, 1)
    ]
    plist = [
        f"- {p['name']}｜{p['role']}｜目标 {p['target_words']:,} 字 ≈ {p['target_words'] / per_page_words:.1f} 页"
        for p in people
    ]
    # 提示哪些章节大到单人吃不下，需要联合承担
    big = [
        f"第 {i} 章「{u['label']}」有 {u['pages']} 页" 
        for i, u in enumerate(units, 1)
        if u["pages"] > max((p["target_words"] / per_page_words) for p in people)
    ]
    big_note = ""
    if big:
        big_note = (
            "\n【注意】以下章节单独一个章节就超过了任何人的配额，"
            "必须由「主编 + 副主编」联合承担，否则一定严重超标：\n  "
            + "\n  ".join(big) + "\n"
        )
    return f"""把 {len(units)} 个章节按顺序切成若干段，分给 {len(people)} 位编写人。正文共 {total_pages} 页，每页约 {per_page_words} 字。

【章节清单】
{chr(10).join(lines)}
{big_note}
【编写人】
{chr(10).join(plist)}

【铁律】
1. 段落必须从第 1 章连续切到第 {len(units)} 章，不许跳章、不许重叠、不许漏章。
2. 每位编写人只能出现一次，{len(people)} 位必须全部用上，一个都不能少。
3. 联合编写只允许「主编 + 副主编」两两组合。
   ✗ 禁止：主编 + 主编、副主编 + 副主编、三个人一段
4. 每段页数要尽量接近该段人员目标页数之和。

【输出格式】
只输出 JSON，不要解释、不要 markdown 代码块：
{{"segments":[{{"members":["姓名"],"from":1,"to":5}},{{"members":["姓名甲","姓名乙"],"from":6,"to":12}}]}}"""


def _extract_json(text: str) -> Optional[Dict]:
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        # 容忍尾逗号
        cleaned = re.sub(r",\s*([}\]])", r"\1", m.group(0))
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return None


def _validate(segs: List[Dict], units: List[Dict], people: List[Dict]) -> Tuple[bool, str]:
    n = len(units)
    roles = {p["name"]: p["role"] for p in people}
    if not isinstance(segs, list) or not segs:
        return False, "segments 为空"
    prev = 0
    used: List[str] = []
    for s in segs:
        if not isinstance(s, dict):
            return False, "segments 元素格式不对"
        members = s.get("members")
        a, b = s.get("from"), s.get("to")
        if not isinstance(members, list) or not members:
            return False, "某一段没有 members"
        if not isinstance(a, int) or not isinstance(b, int):
            return False, "from/to 必须是整数"
        if a != prev + 1:
            return False, f"第 {a} 章前不连续（上一段结束于第 {prev} 章）"
        if b < a or b > n:
            return False, f"章节范围 {a}-{b} 越界"
        for m in members:
            if m not in roles:
                return False, f"「{m}」不在名单里"
            if m in used:
                return False, f"「{m}」被分到了多段"
            used.append(m)
        if len(members) > 2:
            return False, f"第 {a}-{b} 章有 {len(members)} 人，最多两人"
        if len(members) == 2:
            got = [roles[m] for m in members]
            if set(got) != {"主编", "副主编"}:
                return False, f"第 {a}-{b} 章的「{' + '.join(members)}」是 {'+'.join(got)}，只允许主编+副主编"
        prev = b
    if prev != n:
        return False, f"只分到第 {prev} 章，应分到第 {n} 章"
    missing = [p["name"] for p in people if p["name"] not in used]
    if missing:
        return False, f"这些人没被分配：{'、'.join(missing)}"
    return True, ""


def _to_result(segs: List[Dict], units: List[Dict], people: List[Dict],
               per_page_words: int, model: str) -> Dict:
    from allocator import (  # noqa: PLC0415
        compress_chapter_text, split_cooperative_assignment, split_segment_words,
    )

    prefix = [0]
    for u in units:
        prefix.append(prefix[-1] + (u.get("words") or 0))
    by_name = {p["name"]: p for p in people}

    out_segments = []
    for idx, s in enumerate(segs):
        a, b = s["from"] - 1, s["to"]  # 转成 0-based 切片
        members = [by_name[m] for m in s["members"]]
        unit_idx = list(range(a, b))
        words = prefix[b] - prefix[a]
        target = sum(m["target_words"] for m in members)
        seg = {
            "order": idx + 1,
            "members": members,
            "unit_idx": unit_idx,
            "start": units[a]["start"],
            "end": units[b - 1]["end"],
            "pages": units[b - 1]["end"] - units[a]["start"] + 1,
            "words": words,
            "target": target,
            "delta": words - target,
            "delta_ratio": (words - target) / target if target else 0.0,
            "cooperative": len(members) == 2,
            "labels": [units[x]["label"] for x in unit_idx],
            "chapter_text": compress_chapter_text(unit_idx, units),
            "project_nos": sorted({
                units[x]["project_no"] for x in unit_idx if units[x].get("project_no")
            }),
            "figure_pages": sum(units[x].get("figure_pages", 0) for x in unit_idx),
        }
        seg["within_tolerance"] = abs(seg["delta_ratio"]) <= 0.10
        seg["cross_project"] = len(seg["project_nos"]) > 1
        seg["shares"] = split_segment_words(members, words)
        seg["assignments"] = (
            split_cooperative_assignment(unit_idx, units, members)
            if seg["cooperative"] else None
        )
        out_segments.append(seg)

    total_words = prefix[len(units)]
    total_target = sum(p["target_words"] for p in people)
    worst = max((abs(s["delta_ratio"]) for s in out_segments), default=0.0)
    return {
        "segments": out_segments,
        "total_words": total_words,
        "total_target": total_target,
        "gap": total_words - total_target,
        "tolerance": 0.10,
        "best_bound": worst,
        "mode": "ai",
        "model": model,
        "warnings": [
            f"本方案由 {model} 生成，最大偏差 {worst * 100:.1f}%。"
            f"模型只负责切分章节，页码、字数与偏差都在本地核算。"
        ],
        "solved_units": len(units),
        "people_count": len(people),
    }


def ai_allocate(
    units: List[Dict],
    people: List[Dict],
    per_page_words: int = 1300,
    model: str = "",
    max_attempts: int = 2,
    samples: int = 1,
    provider: str = DEFAULT_PROVIDER,
) -> Dict:
    """调用大模型生成分配方案，带校验与重试。

    samples > 1 时多次采样，取偏差最小的那份——模型每次输出都不一样，
    单次结果好坏波动很大。
    """
    workable = [p for p in people if (p.get("target_words") or 0) > 0]
    if not units or not workable:
        raise ValueError("缺少章节或编写人")

    cfg = PROVIDERS.get(provider) or PROVIDERS[DEFAULT_PROVIDER]
    model = model or cfg["model"]
    best: Optional[Dict] = None
    last_err = ""
    attempts_total = 0
    for _ in range(max(1, samples)):
        prompt = _build_prompt(units, workable, per_page_words)
        for attempt in range(max_attempts):
            attempts_total += 1
            text = _call_llm(prompt, model, provider=provider)
            obj = _extract_json(text)
            if not obj or "segments" not in obj:
                last_err = "没有返回合法的 JSON"
            else:
                ok, err = _validate(obj["segments"], units, workable)
                if ok:
                    res = _to_result(obj["segments"], units, workable, per_page_words, model)
                    res["attempts"] = attempts_total
                    if best is None or res["best_bound"] < best["best_bound"]:
                        best = res
                    break
                last_err = err
            prompt += f"\n\n上一次的输出有问题：{last_err}。请严格按铁律修正后重新输出 JSON。"

    if best is None:
        raise ValueError(f"模型没能给出合规方案（{last_err}）。可以改用算法分配。")
    best["samples"] = samples
    best["provider"] = provider
    best["provider_label"] = cfg["label"]
    return best


def ai_allocate_resilient(
    units: List[Dict],
    people: List[Dict],
    per_page_words: int = 1300,
    provider: str = DEFAULT_PROVIDER,
    samples: int = 2,
) -> Dict:
    """先按指定 provider 跑，失败就换备用 provider。

    DeepSeek 走的是第三方反代，网关有 60 秒硬超时且负载波动大，
    同一个请求可能秒回也可能 504；本地网关没有这个限制。
    """
    errors: List[str] = []
    order = [provider] + [p for p in ("local",) if p != provider]
    for prov in order:
        if not available(prov):
            errors.append(f"{prov}: 无凭据")
            continue
        try:
            res = ai_allocate(units, people, per_page_words=per_page_words,
                              provider=prov, samples=samples)
            if prov != provider:
                res["warnings"].insert(
                    0, f"{PROVIDERS[provider]['label']} 调用失败，已自动改用 {PROVIDERS[prov]['label']} 生成。"
                )
                res["fallback_from"] = provider
            return res
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{prov}: {str(exc)[:80]}")
    raise ValueError("所有模型都没能给出方案 —— " + "；".join(errors))
