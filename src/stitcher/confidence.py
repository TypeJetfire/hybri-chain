"""
confidence.py — 置信度计算：为每条缝合边打上 confirmed / partial / conflicting 标签。

缝合边的置信度由以下因素决定：
1. 直接锚点命中次数（≥N 次 → confirmed）
2. 跨语言边界（Go→CGO 边界有特殊置信度）
3. 静态边存在但动态未观测（partial）
4. 拓扑冲突（conflicting）
"""

from enum import Enum
from typing import Dict, Set, List, Tuple
from collections import defaultdict


class Confidence(Enum):
    CONFIRMED = "confirmed"      # 动态直接观测到 A→B
    INFERRED = "inferred"        # 静态图有边，动态只观测到 A 或 B
    PARTIAL = "partial"          # 跨层但中间层未 instrument
    CONFLICTING = "conflicting"  # 拓扑矛盾
    UNKNOWN = "unknown"          # 静态图无边，动态也未观测


# 缝合置信度阈值
MIN_CONFIRMED_HITS = 2     # 动态观测到 A→B 至少 2 次才能标记 confirmed
MIN_INFERRED_HITS = 1     # 动态观测到 A 或 B 至少 1 次才能标记 inferred


class ConfidenceCalculator:
    """
    计算每条缝合边的置信度。

    算法：
    对每条静态边 (A, B)：
      - 在动态轨迹中查找同时包含 A 和 B 的请求（同一个 TID）
      - 若 A → B 在时间序上成立且出现 ≥ MIN_CONFIRMED_HITS 次 → confirmed
      - 若只观测到 A（或 B），但静态图有边 → inferred
      - 若观测到 B 先于 A 出现 → conflicting
      - 若静态无边、动态也未观测 → unknown（忽略）
    """

    def __init__(self, min_confirmed=MIN_CONFIRMED_HITS, min_inferred=MIN_INFERRED_HITS):
        self.min_confirmed = min_confirmed
        self.min_inferred = min_inferred

    def compute(self, cg_edges, anchor_index, events, build_tree_fn):
        """
        计算所有静态边的置信度。

        参数：
          cg_edges: List[CGEdge]  静态调用图的边
          anchor_index: { node_name: [events] }  锚点索引
          events: List[Event]  所有动态事件
          build_tree_fn: callable(events) -> [RequestTree]  构建请求树函数

        返回：
          { (from, to): Confidence }  每条边的置信度
        """
        # 按 TID 构建请求
        trees = build_tree_fn(events)

        # { node_name: [(tree_id, ts), ...] }
        node_hits: Dict[str, List[Tuple[int, int]]] = defaultdict(list)

        # CGO Wrapper 等价映射（与 anchor.py 保持一致）
        from anchor import AnchorMatcher
        cgo_equiv = AnchorMatcher.CGO_EQUIV

        for ti, tree in enumerate(trees):
            for ev in tree["events"]:
                if ev.type != "uprobe":
                    continue
                # 记录 ev.func 本身（用等价映射）
                func_key = cgo_equiv.get(ev.func, ev.func)
                node_hits[func_key].append((ti, ev.ts_ns))
                # 同时记录栈帧中的函数
                frames = ev.stack if isinstance(ev.stack, list) else []
                for frame in frames:
                    clean = frame.split("+")[0].strip()
                    node_hits[clean].append((ti, ev.ts_ns))

        results = {}

        for edge in cg_edges:
            a, b = edge.from_node, edge.to_node
            key = (a, b)

            # 在同一请求中同时观测到 A 和 B
            trees_with_a = {h[0] for h in node_hits.get(a, [])}
            trees_with_b = {h[0] for h in node_hits.get(b, [])}
            common_trees = trees_with_a & trees_with_b

            if not common_trees:
                # 只观测到 A 或 B
                if node_hits.get(a) or node_hits.get(b):
                    results[key] = Confidence.INFERRED
                else:
                    results[key] = Confidence.UNKNOWN
                continue

            # 检查时间序：在共同请求中，是否存在 A → B
            count_ab = 0
            count_ba = 0

            for tid in common_trees:
                hits_a = sorted([h[1] for h in node_hits.get(a, []) if h[0] == tid])
                hits_b = sorted([h[1] for h in node_hits.get(b, []) if h[0] == tid])

                # 检查是否存在 a 在 b 之前
                for ta in hits_a:
                    for tb in hits_b:
                        if ta < tb:
                            count_ab += 1
                        elif tb < ta:
                            count_ba += 1

            if count_ab >= self.min_confirmed:
                results[key] = Confidence.CONFIRMED
            elif count_ab > 0:
                results[key] = Confidence.INFERRED
            elif count_ba > 0:
                results[key] = Confidence.CONFLICTING
            else:
                results[key] = Confidence.UNKNOWN

        return results

    def summarize(self, results: Dict[Tuple[str, str], Confidence]):
        """打印置信度统计。"""
        counts = defaultdict(int)
        for conf in results.values():
            counts[conf] += 1
        total = sum(counts.values())
        print(f"\n缝合置信度统计（共 {total} 条边）：")
        for level in [Confidence.CONFIRMED, Confidence.INFERRED,
                       Confidence.PARTIAL, Confidence.CONFLICTING, Confidence.UNKNOWN]:
            c = counts.get(level, 0)
            pct = c / max(total, 1) * 100
            print(f"  {level.value:<15} {c:>4} ({pct:5.1f}%)")

        confirmed = [k for k, v in results.items() if v == Confidence.CONFIRMED]
        print(f"\n  → confirmed 边（可直接用于论文数据）：{len(confirmed)} 条")
        return confirmed
