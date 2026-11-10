# -*- coding: utf-8 -*-
"""编写字数的公司制度。

制度（据编写组口径）：
    主　审　　不承担编写，不分配字数
    总主编　　不承担编写，不分配字数
    主　编　　依次 6 万 / 5 万 / 3 万（第 4 位及以后按 3 万）
    副主编　　各 2 万
    参　编　　常规不分配；全书字数有剩余时各 1 万

「剩余」的口径：全书可分配字数 −（主编 + 副主编 的制度合计）。
够一位参编就发一位，按扉页顺序先到先得。
"""
from __future__ import annotations

from typing import Dict, List, Optional

CHIEF_TIERS = [60000, 50000, 30000]
CHIEF_FLOOR = 30000
VICE_WORDS = 20000
MEMBER_WORDS = 10000

# 不参与字数分配的角色
NON_WRITING_ROLES = ("主审", "总主编")


def _chief_words(index: int) -> int:
    """第 index 位主编（0-based）的制度字数。"""
    if index < len(CHIEF_TIERS):
        return CHIEF_TIERS[index]
    return CHIEF_FLOOR


def build_initial_people(authors: List[Dict]) -> Dict:
    """按制度把扉页名单换算成带目标字数的名单。

    返回：
        people      可分配的人员（跳过主审/总主编）
        skipped     未纳入分配的人及原因
        policy_total 主编 + 副主编的制度合计
        member_pool 参编人数（余量够时可各加 1 万）
    """
    people: List[Dict] = []
    skipped: List[Dict] = []
    chief_idx = 0
    policy_total = 0

    for a in authors:
        name = a.get("name", "").strip()
        role = a.get("role") or "参编"
        if not name:
            continue

        if role in NON_WRITING_ROLES:
            skipped.append({"name": name, "role": role, "reason": "只署名，不承担编写"})
            continue

        if role == "主编":
            words = _chief_words(chief_idx)
            chief_idx += 1
            policy_total += words
        elif role == "副主编":
            words = VICE_WORDS
            policy_total += words
        else:
            words = 0  # 参编默认 0，等余量

        people.append({
            "name": name,
            "role": role,
            "target_words": words,
            "allow_pair": True,
        })

    members = [p for p in people if p["role"] == "参编"]
    return {
        "people": people,
        "skipped": skipped,
        "policy_total": policy_total,
        "member_pool": len(members),
        "member_words_each": MEMBER_WORDS,
    }


def suggest_members(people: List[Dict], total_words: Optional[int]) -> Dict:
    """已知全书可分配字数时，算出能给多少参编各分 1 万。

    返回 {gap, can_fill, fill_words, note}。
    """
    if not people:
        return {"gap": 0, "can_fill": 0, "fill_words": 0, "note": ""}

    need = sum(p.get("target_words", 0) for p in people)
    members = [p for p in people if p.get("role") == "参编" and not p.get("target_words")]
    if total_words is None or total_words <= 0:
        return {"gap": 0, "can_fill": 0, "fill_words": 0, "note": ""}

    gap = total_words - need
    if gap <= 0 or not members:
        return {
            "gap": gap,
            "can_fill": 0,
            "fill_words": 0,
            "note": (
                f"全书可分配 {total_words:,} 字，制度需求 {need:,} 字，"
                f"已无余量可分给参编。" if gap <= 0 and members else ""
            ),
        }

    can_fill = min(len(members), gap // MEMBER_WORDS)
    fill_words = can_fill * MEMBER_WORDS
    if can_fill <= 0:
        note = (
            f"全书可分配 {total_words:,} 字，制度需求 {need:,} 字，余 {gap:,} 字，"
            f"不够给参编各分 1 万。"
        )
    elif can_fill < len(members):
        note = (
            f"全书可分配 {total_words:,} 字，制度需求 {need:,} 字，余 {gap:,} 字，"
            f"可给前 {can_fill} 位参编各 {MEMBER_WORDS // 10000} 万字，"
            f"其余 {len(members) - can_fill} 位参编不分配。"
        )
    else:
        note = (
            f"全书可分配 {total_words:,} 字，制度需求 {need:,} 字，余 {gap:,} 字，"
            f"可给全部 {can_fill} 位参编各 {MEMBER_WORDS // 10000} 万字。"
        )
    return {"gap": gap, "can_fill": can_fill, "fill_words": fill_words, "note": note}


def apply_member_fill(people: List[Dict], can_fill: int) -> List[Dict]:
    """按「先到先得」给前 can_fill 位参编各补 1 万。"""
    out = []
    used = 0
    for p in people:
        q = dict(p)
        if q.get("role") == "参编" and not q.get("target_words") and used < can_fill:
            q["target_words"] = MEMBER_WORDS
            used += 1
        out.append(q)
    return out
