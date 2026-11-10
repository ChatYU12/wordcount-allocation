# -*- coding: utf-8 -*-
"""字数分配算法。

业务模型
--------
书稿被切成一串「不可再拆的单元」（任务 / 项目标题 / 项目尾部三件套），按书的先后顺序排列。
编写队伍按角色排成有序名单（主编 → 副主编 → 参编），每个人领取序列中**一个连续区间**。

三条硬规则：
1. 单元不可拆：一个任务不会分给两个人，只会整体属于某一段。
2. 一段可以由 1 人独立承担，也可以由「主编 + 副主编」两人共同承担（合作编写）。
   合作时两人目标字数相加，只要该段实际字数落在两人目标合计的容差范围内即可。
3. 全书必须被完整覆盖，不能有单元没人领、也不能重复领。

求解
----
在「单元位置 × 人员前缀长度」上做动态规划：
    f[i][t] = 用人序列前 t 个人恰好覆盖前 i 个单元的最小代价
转移时，最后一个人 t-1 单独领一段，或最后两人 (t-2, t-1) 合作领一段。
代价函数对「超出容差的偏差」做平方惩罚，超额比不足罚得更重（超字要扣钱）。
"""
from __future__ import annotations

import itertools
from typing import Dict, List, Optional, Tuple

ROLE_CHIEF = "主编"
ROLE_VICE = "副主编"
ROLE_MEMBER = "参编"
ROLE_CHIEF_EDITOR = "总主编"

# 默认允许的合作组合（顺序敏感：前者带后者）
# 硬性规则：联合编写只能是「主编 + 副主编」。
# 主编带主编、副主编带副主编都不允许。
DEFAULT_PAIRS: List[List[str]] = [
    [ROLE_CHIEF, ROLE_VICE],
    [ROLE_VICE, ROLE_CHIEF],   # 顺序不影响判定，但两个人谁在前由名单顺序决定
]


def _pair_allowed(a: Dict, b: Dict, allowed_pairs: List[List[str]]) -> bool:
    if not a.get("allow_pair", True) or not b.get("allow_pair", True):
        return False
    return [a["role"], b["role"]] in allowed_pairs


def _penalty(words: int, target: int, tol: float, w_over: float, w_under: float) -> float:
    """偏差代价：容差内为 0，超出部分平方加权。"""
    if target <= 0:
        return 10.0
    ratio = (words - target) / target
    if abs(ratio) <= tol:
        return 0.0
    excess = abs(ratio) - tol
    if ratio > 0:
        return (excess ** 2) * w_over
    return (excess ** 2) * w_under


def compress_chapter_text(seg_unit_idx: List[int], units: List[Dict]) -> str:
    """把一段包含的单元压缩成编辑看得懂的章节描述。

    整项目都给同一人时只写「项目三 躯体功能评估」；
    只拿到项目的一部分时写成「项目七 健康问题评估（任务二、任务三）」。
    """
    by_proj: Dict[object, List[int]] = {}
    order: List[object] = []
    for ui in seg_unit_idx:
        p = units[ui].get("project_no")
        if p not in by_proj:
            by_proj[p] = []
            order.append(p)
        by_proj[p].append(ui)

    parts: List[str] = []
    for p in order:
        sel = by_proj[p]
        if p is None:
            for ui in sel:
                parts.append(units[ui]["label"])
            continue
        proj_units = [u for u in units if u.get("project_no") == p]
        head = next((u for u in proj_units if u.get("kind") == "project-head"), None)
        proj_name = head["label"] if head else f"项目{p}"

        all_idx = {u["index"] for u in proj_units}
        if set(sel) == all_idx:
            parts.append(proj_name)
            continue

        bits: List[str] = []
        for ui in sel:
            u = units[ui]
            if u.get("kind") == "project-head":
                bits.append("项目首页")
            elif u.get("kind") == "project-tail":
                bits.append("项目检测等")
            else:
                bits.append(u["label"].split(" ")[0].split("　")[0])
        parts.append(f"{proj_name}（{'、'.join(bits)}）")
    return "；".join(parts)


def allocate(
    units: List[Dict],
    people: List[Dict],
    tolerance: float = 0.05,
    over_weight: float = 3.0,
    under_weight: float = 1.0,
    allowed_pairs: Optional[List[List[str]]] = None,
    boundary_penalty: float = 0.02,
    hard_bound: Optional[float] = None,
) -> Dict:
    """给出一个分配方案。

    参数
    ----
    units : [{index, label, start, end, pages, words, kind, project_no}]
    people : [{name, role, target_words, allow_pair}]
    tolerance : 允许的字数偏差比例，如 0.05 表示 ±5%
    over_weight : 超额惩罚权重（越大越不愿意超字）
    under_weight : 不足惩罚权重
    allowed_pairs : 允许合作的角色组合
    boundary_penalty : 切点若不在项目边界上的轻微惩罚，用于优先「整项目给一人」
    hard_bound : 硬约束，偏差超过该比例的分段直接判为不可行（用于最小化最大偏差）
    """
    if allowed_pairs is None:
        allowed_pairs = DEFAULT_PAIRS
    if not units:
        raise ValueError("没有可分配的单元")
    # 目标字数为 0 的人不承担编写，不占章节（参编在余量不足时就是这种情况）
    people = [p for p in people if (p.get("target_words") or 0) > 0]
    if not people:
        raise ValueError("没有编写人员")

    n, m = len(units), len(people)
    if n < m:
        raise ValueError(
            f"单元数（{n}）少于人数（{m}）：至少需要为每个人保留 1 个单元，请调大每页字数口径或合并人员。"
        )

    # 前缀和，便于 O(1) 求任意区间的字数
    prefix = [0] * (n + 1)
    for i, u in enumerate(units):
        prefix[i + 1] = prefix[i] + u["words"]

    # 项目边界位置（用于 boundary_penalty）
    proj_boundary = set()
    last_proj = None
    for i, u in enumerate(units):
        if u.get("project_no") != last_proj:
            proj_boundary.add(i)
            last_proj = u.get("project_no")

    INF = float("inf")
    # f[t][i] = 前 t 个人覆盖前 i 个单元的最小代价；choice 记录回溯信息
    f = [[INF] * (n + 1) for _ in range(m + 1)]
    choice: List[List[Optional[Tuple]]] = [[None] * (n + 1) for _ in range(m + 1)]
    f[0][0] = 0.0

    tol = tolerance
    wo, wu = over_weight, under_weight
    hb = hard_bound
    bp = boundary_penalty
    nb = proj_boundary

    def _pen(w, target):
        if target <= 0:
            return 10.0
        r = (w - target) / target
        if -tol <= r <= tol:
            return 0.0
        excess = abs(r) - tol
        return excess * excess * (wo if r > 0 else wu)

    for t in range(1, m + 1):
        person = people[t - 1]
        tgt = person["target_words"]
        pair_prev = people[t - 2] if t >= 2 else None
        can_pair = pair_prev is not None and _pair_allowed(pair_prev, person, allowed_pairs)
        ft = f[t]
        f1 = f[t - 1]
        f2 = f[t - 2] if can_pair else None
        pair_tgt = (pair_prev["target_words"] + tgt) if can_pair else 0

        for i in range(t, n + 1):
            wi = prefix[i]
            best = INF
            best_ch = None
            # --- 单人领 [k, i-1] ---
            for k in range(t - 1, i):
                base = f1[k]
                if base == INF:
                    continue
                w = wi - prefix[k]
                if hb is not None:
                    r = (w - tgt) / tgt if tgt > 0 else 0.0
                    if abs(r) > hb + 1e-12:
                        # w 随 k 增大而减小：一旦不足下界，后面只会更不足
                        if r < 0:
                            break
                        continue
                cost = base + _pen(w, tgt)
                if k not in nb:
                    cost += bp
                if cost < best:
                    best = cost
                    best_ch = ("single", k, t - 1)
            # --- 两人合作领 [k, i-1] ---
            if can_pair:
                for k in range(t - 2, i):
                    base = f2[k]
                    if base == INF:
                        continue
                    w = wi - prefix[k]
                    if hb is not None:
                        r = (w - pair_tgt) / pair_tgt if pair_tgt > 0 else 0.0
                        if abs(r) > hb + 1e-12:
                            if r < 0:
                                break
                            continue
                    cost = base + _pen(w, pair_tgt)
                    if k not in nb:
                        cost += bp
                    if cost < best:
                        best = cost
                        best_ch = ("pair", k, t - 2)
            ft[i] = best
            choice[t][i] = best_ch

    if f[m][n] == INF:
        if hard_bound is not None:
            raise Infeasible(f"在 ±{hard_bound * 100:.1f}% 偏差内无可行分配")
        raise ValueError("无可行解：请检查人员数量、单元数量与目标字数设置。")

    # ---- 回溯 ----
    segments: List[Dict] = []
    i, t = n, m
    while i > 0 and t > 0:
        ch = choice[t][i]
        if ch is None:
            raise ValueError("回溯失败")
        kind, k, t_prev = ch
        seg_units = list(range(k, i))
        words = prefix[i] - prefix[k]
        if kind == "single":
            members = [people[t - 1]]
            t = t_prev
        else:
            members = [people[t - 2], people[t - 1]]
            t = t_prev
        segments.append(
            {
                "members": members,
                "unit_idx": seg_units,
                "start": units[k]["start"],
                "end": units[i - 1]["end"],
                "pages": units[i - 1]["end"] - units[k]["start"] + 1,
                "words": words,
                "cooperative": kind == "pair",
            }
        )
        i = k
    segments.reverse()

    # ---- 补充展示信息 ----
    for idx, seg in enumerate(segments):
        seg["order"] = idx + 1
        seg["labels"] = [units[x]["label"] for x in seg["unit_idx"]]
        seg["chapter_text"] = compress_chapter_text(seg["unit_idx"], units)
        seg["project_nos"] = sorted(
            {units[x]["project_no"] for x in seg["unit_idx"] if units[x].get("project_no")}
        )
        seg["target"] = sum(p["target_words"] for p in seg["members"])
        seg["delta"] = seg["words"] - seg["target"]
        seg["delta_ratio"] = seg["delta"] / seg["target"] if seg["target"] else 0.0
        seg["within_tolerance"] = abs(seg["delta_ratio"]) <= tolerance
        seg["cross_project"] = len(seg["project_nos"]) > 1
        seg["figure_pages"] = sum(units[x].get("figure_pages", 0) for x in seg["unit_idx"])
        seg["shares"] = split_segment_words(seg["members"], seg["words"])
        # 合作段：标明每个人实际负责的章节区间
        if seg["cooperative"]:
            seg["assignments"] = split_cooperative_assignment(
                seg["unit_idx"], units, seg["members"]
            )
        else:
            seg["assignments"] = None

    total_words = prefix[n]
    total_target = sum(p["target_words"] for p in people)
    warnings = _build_warnings(segments, people, tolerance, total_words, total_target)

    result = {
        "segments": segments,
        "total_words": total_words,
        "total_target": total_target,
        "gap": total_words - total_target,
        "tolerance": tolerance,
        "warnings": warnings,
        "solved_units": n,
        "people_count": m,
    }
    result["warnings"] = warnings + check_role_hierarchy(result)
    return result


def _build_warnings(
    segments: List[Dict],
    people: List[Dict],
    tolerance: float,
    total_words: int,
    total_target: int,
) -> List[str]:
    out: List[str] = []
    if total_words != total_target:
        diff = total_words - total_target
        direction = "多" if diff > 0 else "少"
        out.append(
            f"全书可分配字数（{total_words:,}）与名单需求合计（{total_target:,}）不相等，"
            f"实际{direction} {abs(diff):,} 字，差额会被分摊到各段。"
        )
    for seg in segments:
        if not seg["within_tolerance"]:
            out.append(
                f"第 {seg['order']} 段（{'、'.join(p['name'] for p in seg['members'])}）"
                f"实际 {seg['words']:,} 字 / 目标 {seg['target']:,} 字，"
                f"偏差 {seg['delta_ratio'] * 100:+.1f}%，超出 ±{tolerance * 100:.0f}% 容差。"
            )
        if seg["cooperative"]:
            names = " + ".join(p["name"] for p in seg["members"])
            out.append(f"第 {seg['order']} 段由 {names} 合作编写（第 {seg['start']}-{seg['end']} 页）。")
    unassigned = [p for p in people if p["target_words"] > 0 and not any(
        p in seg["members"] for seg in segments
    )]
    for p in unassigned:
        out.append(f"{p['name']} 没有分到任何单元。")
    return out


# ---------- 辅助：按名单总额反推每页字数 ----------

class Infeasible(Exception):
    """在给定硬约束下不存在可行分配。"""


def allocate_best(
    units: List[Dict],
    people: List[Dict],
    tolerance: float = 0.05,
    over_weight: float = 3.0,
    under_weight: float = 1.0,
    allowed_pairs: Optional[List[List[str]]] = None,
    boundary_penalty: float = 0.02,
    precision: float = 0.004,
) -> Dict:
    """两阶段求解：先最小化「最大偏差」，再在该约束下最小化总偏差。

    单元粒度决定了理论上的最小偏差——任务动辄 6000~15000 字，任何切分都不可能做到人人 ±2%。
    所以先二分出这本书「必然能做到的最小容差」，再在这个容差里找最均衡的方案。
    """
    if allowed_pairs is None:
        allowed_pairs = DEFAULT_PAIRS

    lo, hi = 0.0, 1.0
    # 先确认极端情况可行（单元远大于目标时偏差可能很大）
    hi = 1.0
    while True:
        try:
            allocate(
                units, people, tolerance=hi, allowed_pairs=allowed_pairs,
                boundary_penalty=0.0, hard_bound=hi,
            )
            break
        except Infeasible:
            hi *= 2
            if hi > 100:
                raise ValueError("无法找到可行方案，请检查人员数量与单元数量的关系。")

    # 二分最小可行偏差
    for _ in range(24):
        mid = (lo + hi) / 2
        if hi - lo < precision:
            break
        try:
            allocate(
                units, people, tolerance=mid, allowed_pairs=allowed_pairs,
                boundary_penalty=0.0, hard_bound=mid,
            )
            hi = mid
        except Infeasible:
            lo = mid

    best_bound = hi
    # 在该偏差内做总偏差最小化（带项目边界偏好）
    try:
        result = allocate(
            units, people, tolerance=best_bound, over_weight=over_weight,
            under_weight=under_weight, allowed_pairs=allowed_pairs,
            boundary_penalty=boundary_penalty, hard_bound=best_bound + 1e-9,
        )
    except Infeasible:
        result = allocate(
            units, people, tolerance=best_bound, over_weight=over_weight,
            under_weight=under_weight, allowed_pairs=allowed_pairs,
            boundary_penalty=0.0, hard_bound=best_bound + 1e-9,
        )
    result["best_bound"] = best_bound
    result["within_declared_tolerance"] = best_bound <= tolerance
    return result


def infer_per_page_words(units: List[Dict], total_target: int, base_per_page: int = 1200) -> int:
    """已知总需求字数与总页数，反推「每页字数」。

    这是本工具最常用的校准手段：把版面字数口径调到让总字数正好等于名单需求。
    """
    total_pages = sum(u["pages"] for u in units)
    if total_pages <= 0:
        return base_per_page
    return max(1, round(total_target / total_pages))


def distribute_words(units: List[Dict], total_words: int) -> List[Dict]:
    """把给定的全书总字数按各单元页数比例分摊下去，保证合计精确等于 total_words。

    用于「总字数由用户手动输入」的口径：不能让 页数×每页字数 的四舍五入把总额带偏。
    尾差用最大余数法补，单元字数会相差 1~2 字，无实际影响。
    """
    out = [dict(u) for u in units]
    weights = [_weight_of(u) for u in out]
    total_weight = sum(weights)
    if total_weight <= 0:
        for u in out:
            u["words"] = 0
        return out

    exact = [total_words * w / total_weight for w in weights]
    base = [int(x) for x in exact]
    remainder = total_words - sum(base)
    order = sorted(range(len(out)), key=lambda i: exact[i] - base[i], reverse=True)
    for k in range(max(0, remainder)):
        base[order[k % len(order)]] += 1
    for u, w in zip(out, base):
        u["words"] = w
    return out


def _weight_of(unit: Dict) -> float:
    """单元的字数权重。

    默认等于页数；若单元带 figure_pages，则按国标对整页图折减
    （插图占一面按满版 20% 计），weight = 页数 - 整页图页数 × 0.8。
    """
    w = unit.get("weight")
    if w is not None:
        return float(w)
    pages = float(unit.get("pages") or 0)
    figs = float(unit.get("figure_pages") or 0)
    return max(0.0, pages - figs * 0.8) if figs else pages


def rescale_units(units: List[Dict], per_page_words: int) -> List[Dict]:
    out = []
    for u in units:
        v = dict(u)
        v["words"] = int(round(_weight_of(v) * per_page_words))
        out.append(v)
    return out


def split_cooperative_assignment(
    unit_idx: List[int], units: List[Dict], members: List[Dict]
) -> Optional[List[Dict]]:
    """把合作段内的单元按目标字数比例分给两位成员，各自得到一个连续子区间。

    切点取「累积字数最接近目标比例」的单元边界。段内只有一个单元时无法再分，
    返回 None，此时按两人共同编写处理。
    """
    if len(members) != 2 or len(unit_idx) < 2:
        return None
    t0 = max(0, members[0].get("target_words") or 0)
    t1 = max(0, members[1].get("target_words") or 0)
    total_t = t0 + t1
    if total_t <= 0:
        return None

    words = [units[x].get("words") or 0 for x in unit_idx]
    total_w = sum(words)
    if total_w <= 0:
        return None

    want = t0 / total_t
    cum = 0
    best_k = 1
    best_diff = None
    for k in range(1, len(unit_idx)):
        cum += words[k - 1]
        diff = abs(cum / total_w - want)
        if best_diff is None or diff < best_diff:
            best_diff, best_k = diff, k

    out = []
    for member, slice_idx in ((members[0], unit_idx[:best_k]), (members[1], unit_idx[best_k:])):
        sub_units = [units[x] for x in slice_idx]
        w = sum(u.get("words") or 0 for u in sub_units)
        out.append({
            "name": member["name"],
            "role": member["role"],
            "target": member.get("target_words") or 0,
            "start": sub_units[0]["start"],
            "end": sub_units[-1]["end"],
            "pages": sub_units[-1]["end"] - sub_units[0]["start"] + 1,
            "words": w,
            "labels": [u["label"] for u in sub_units],
            "chapter_text": compress_chapter_text(slice_idx, units),
            "unit_count": len(slice_idx),
        })
    return out


def split_segment_words(members: List[Dict], words: int) -> List[Dict]:
    """把一段的字数分到具体人头上。

    单人段全额归他；合作段按各人目标字数比例切分（最大余数法保证合计不差 1 字）。
    这样「按人汇总」里不会出现「两人均分 8.5 万字」这种不合理的算法。
    """
    if not members:
        return []
    if len(members) == 1:
        p = members[0]
        return [{
            "name": p["name"], "role": p["role"], "words": words,
            "target": p["target_words"], "delta": words - p["target_words"],
        }]
    targets = [max(0, m["target_words"]) for m in members]
    total_t = sum(targets)
    if total_t <= 0:
        targets = [1] * len(members)
        total_t = len(members)
    exact = [words * t / total_t for t in targets]
    base = [int(x) for x in exact]
    rem = words - sum(base)
    order = sorted(range(len(members)), key=lambda i: exact[i] - base[i], reverse=True)
    for k in range(max(0, rem)):
        base[order[k % len(order)]] += 1
    return [
        {
            "name": m["name"], "role": m["role"], "words": base[i],
            "target": m["target_words"], "delta": base[i] - m["target_words"],
        }
        for i, m in enumerate(members)
    ]


ROLE_RANK = {"总主编": 0, "主编": 1, "副主编": 2, "参编": 3}


def check_role_hierarchy(res: Dict) -> List[str]:
    """角色层级合理性检查（软约束，只提示不改结果）。

    行业惯例是主编 > 副主编 > 参编 的编写量。任务粒度受限时可能倒挂，
    提示出来让人自己决定要不要调整名单顺序或允许拆任务。
    """
    out: List[str] = []
    by_role: Dict[str, List[int]] = {}
    for seg in res.get("segments", []):
        for sh in seg.get("shares", []):
            by_role.setdefault(sh["role"], []).append(sh["words"])
    roles = [r for r in ("主编", "副主编", "参编") if r in by_role]
    for upper, lower in zip(roles, roles[1:]):
        hi = sum(by_role[upper]) / len(by_role[upper])
        lo = sum(by_role[lower]) / len(by_role[lower])
        if lo > hi * 1.05:
            out.append(
                f"角色层级倒挂：{lower}的平均分配字数（{lo:,.0f} 字）高于{upper}（{hi:,.0f} 字）。"
                f"任务不可拆时可能出现这种情况，建议调整名单顺序或允许拆分该章节。"
            )
    return out


def _group_people(people: List[Dict]) -> List[tuple]:
    """按（角色, 目标字数）分组，同组的人互换不改变结果。"""
    groups: Dict[tuple, List[Dict]] = {}
    order: List[tuple] = []
    for p in people:
        key = (p.get("role"), p.get("target_words") or 0)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(p)
    return [(k, groups[k]) for k in order]


def _multiset_orders(groups: List[tuple]) -> List[List[int]]:
    """生成「组序号」的所有不重复排列：第 gi 组恰好出现 len(group) 次。"""
    n = len(groups)
    counts = [len(items) for _, items in groups]
    total = sum(counts)
    out: List[List[int]] = []

    def walk(seq: List[int], remain: List[int]) -> None:
        if len(seq) == total:
            out.append(list(seq))
            return
        for gi in range(n):
            if remain[gi] <= 0:
                continue
            remain[gi] -= 1
            seq.append(gi)
            walk(seq, remain)
            seq.pop()
            remain[gi] += 1

    walk([], list(counts))
    return out


def optimize_order(
    units: List[Dict],
    people: List[Dict],
    tolerance: float = 0.10,
    max_orders: int = 3000,
) -> Dict:
    """自动搜索偏差最小的名单顺序。

    名单顺序决定两件事：谁先领前面的章节、谁能和谁搭档。
    同角色同目标的人互换不影响结果，因此只需搜索「组」的排列。
    """
    workable = [p for p in people if (p.get("target_words") or 0) > 0]
    if len(workable) < 2:
        raise ValueError("至少需要两位有字数的编写人")

    groups = _group_people(workable)
    orders = _multiset_orders(groups)
    truncated = False
    if len(orders) > max_orders:
        truncated = True
        step = len(orders) / max_orders
        orders = [orders[int(i * step)] for i in range(max_orders)]

    best: Optional[Dict] = None
    best_order: Optional[List[Dict]] = None
    for seq in orders:
        picks = [0] * len(groups)
        candidate: List[Dict] = []
        for gi in seq:
            candidate.append(groups[gi][1][picks[gi]])
            picks[gi] += 1
        try:
            res = allocate_best(units, candidate, tolerance=tolerance)
        except Exception:  # noqa: BLE001
            continue
        if best is None or res["best_bound"] < best["best_bound"]:
            best = res
            best_order = candidate

    if best is None or best_order is None:
        raise ValueError("没有找到可行的分配方案")

    best["optimized"] = {
        "order": [
            {"name": p["name"], "role": p["role"], "target_words": p["target_words"]}
            for p in best_order
        ],
        "searched": len(orders),
        "truncated": truncated,
    }
    return best
