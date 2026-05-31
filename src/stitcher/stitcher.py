#!/usr/bin/env python3
"""
stitcher.py — 统一调用链缝合器

将静态调用图 + 动态追踪轨迹缝合，生成带置信度的完整调用链。

用法：
    python3 stitcher.py trace_unified.jsonl [OPTIONS]
    python3 stitcher.py trace_unified.jsonl --graph call_graph_static.json --summary
    python3 stitcher.py trace_unified.jsonl --flame
    python3 stitcher.py trace_unified.jsonl --export缝合结果.json
"""

import sys
import os
import json
import argparse
import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from cg_loader import CallGraph
from anchor import AnchorMatcher
from confidence import ConfidenceCalculator, Confidence


# ---------------------------------------------------------------------------
# 复用 trace_unify.py 的解析逻辑（避免重复导入同一文件）
# ---------------------------------------------------------------------------
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Event:
    ts_ns: int
    tid: int
    type: str
    func: str
    duration_us: int
    stack: list = field(default_factory=list)
    comm: str = ""
    extra: dict = field(default_factory=dict)
    trace_id: str = ""  # HybriChain: cross-process trace ID from X-Request-ID


def parse_jsonl(path: str):
    """解析统一追踪文件。"""
    events = []
    cur_type = None
    cur_func = ""
    cur_ts_ns = 0
    cur_tid = 0
    cur_dur = 0
    cur_stack = []
    cur_trace_id = ''
    extra = {}
    active_trace_id = {}  # tid(int) -> trace_id(str), updated by @TRACEID@ events

    for raw in open(path, "r"):
        line = raw.rstrip("\n")
        stripped = line.strip()

        if (not stripped or stripped.startswith("Tracing") or
            stripped.startswith("Stop") or stripped.startswith("---")):
            continue

        if stripped.startswith("@TRACEID@ "):
            # @TRACEID@ daemon_entry|runner_entry ts_ns pid traceID
            parts = stripped.split(maxsplit=4)
            if len(parts) >= 5:
                tid_key = int(parts[3])
                active_trace_id[tid_key] = parts[4]
                ev = Event(ts_ns=int(parts[2]), tid=tid_key, type="traceid",
                            func=parts[1], duration_us=0, trace_id=parts[4])
                events.append(ev)

        elif stripped.startswith("@UPROBE@ "):
            parts = stripped.split()
            cur_type = "uprobe"
            cur_func = parts[1]
            cur_ts_ns = int(parts[2])
            cur_tid = int(parts[3])
            cur_dur = int(parts[4])
            cur_stack = []
            cur_trace_id = active_trace_id.get(cur_tid, '')

        elif stripped.startswith("@SYSCALL@ "):
            parts = stripped.split()
            cur_type = "syscall"
            cur_func = parts[1]
            cur_ts_ns = int(parts[2])
            cur_tid = int(parts[3])
            cur_dur = 0
            cur_stack = []
            cur_trace_id = active_trace_id.get(cur_tid, '')
            extra = {}
            for p in reversed(parts[4:]):
                if p.startswith("dur="):
                    cur_dur = int(p[4:])
                    break
            for p in parts[4:]:
                if "=" in p:
                    k, v = p.split("=", 1)
                    try:
                        extra[k] = int(v)
                    except ValueError:
                        extra[k] = v

        elif stripped == "@END@":
            if cur_type == "uprobe":
                clean = [f.strip() for f in cur_stack if f.strip() and not f.strip().startswith("0x")]
                ev = Event(ts_ns=cur_ts_ns, tid=cur_tid, type="uprobe",
                            func=cur_func, duration_us=cur_dur, stack=clean,
                            trace_id=cur_trace_id, extra=extra)
                events.append(ev)
            elif cur_type == "syscall":
                ev = Event(ts_ns=cur_ts_ns, tid=cur_tid, type="syscall",
                            func=cur_func, duration_us=cur_dur, stack=[], extra=extra,
                            trace_id=cur_trace_id)
                events.append(ev)
            cur_type = None

        elif cur_type == "uprobe" and stripped:
            cur_stack.append(stripped)

    events.sort(key=lambda e: e.ts_ns)
    return events


def build_trace_chains(events):
    """
    HybriChain 跨进程调用链缝合。

    策略：按 trace_id 分组，相同 trace_id 的 daemon 侧和 runner 侧事件
    归并到同一棵调用树中。trace_id 由 withTraceID uprobe 提供，
    形式为 @TRACEID@ daemon_entry|runner_entry <ts> <pid> <traceID>。

    事件流（单次推理）：
      daemon:  @TRACEID@ daemon_entry  t0  pid  <traceID>
               @UPROBE@  llama_xxx    t1   tid  (→ llama.cpp)
               @SYSCALL@ futex        t2   tid  (→ 内核)
      runner:  @TRACEID@ runner_entry t3   pid  <traceID>  ← 同 traceID
               @UPROBE@  llama_decode t4   tid  (→ llama.cpp)
               @SYSCALL@ mmap         t5   tid  (→ 内核)

    同一 trace_id 下的所有事件，按时间戳排序，构成完整调用链。
    无 trace_id 的事件（遗留或不支持的场景）回退到按 TID 分组。
    """
    by_trace = defaultdict(list)
    no_trace = []  # 事件没有 trace_id 的原始 TID 分组

    traceid_events = [e for e in events if e.type == "traceid"]
    # 按 trace_id 分组
    for ev in events:
        if ev.trace_id:
            by_trace[ev.trace_id].append(ev)
        else:
            no_trace.append(ev)

    chains = []
    for trace_id, evs in by_trace.items():
        evs.sort(key=lambda e: e.ts_ns)
        # 提取涉及的 PID（daemon 和 runner）
        pids = list({e.tid for e in evs if e.type in ("uprobe", "syscall")})
        chains.append({
            "trace_id": trace_id,
            "layer": "cross_process",
            "pids": pids,
            "events": evs,
            "total_us": evs[-1].ts_ns - evs[0].ts_ns if evs else 0,
        })

    # 无 trace_id 的回退到原 TID 策略
    by_tid_fallback = defaultdict(list)
    for ev in no_trace:
        by_tid_fallback[ev.tid].append(ev)
    for tid, evs in by_tid_fallback.items():
        evs.sort(key=lambda e: e.ts_ns)
        chains.append({
            "trace_id": "",
            "layer": "single_process",
            "tid": tid,
            "events": evs,
            "total_us": evs[-1].ts_ns - evs[0].ts_ns if evs else 0,
        })

    chains.sort(key=lambda c: -c["total_us"])
    return chains


def build_call_tree(events):
    """按 TID 分组，时间窗口内的事件构成一个调用链。"""
    by_tid = defaultdict(list)
    for ev in events:
        by_tid[ev.tid].append(ev)

    trees = []
    for tid, evs in by_tid.items():
        if not evs:
            continue
        requests = []
        current = []
        last_ts = None
        for ev in evs:
            if last_ts is not None and (ev.ts_ns - last_ts) > 50_000_000:
                if current:
                    requests.append(current)
                current = []
            current.append(ev)
            last_ts = ev.ts_ns
        if current:
            requests.append(current)

        for req in requests:
            trees.append({
                "tid": tid,
                "trace_id": req[0].trace_id if req else "",
                "comm": req[0].comm,
                "events": req,
                "total_us": req[-1].ts_ns - req[0].ts_ns,
            })
    return trees


# ---------------------------------------------------------------------------
# 缝合引擎
# ---------------------------------------------------------------------------

class Stitcher:
    """
    缝合引擎。
    输入：静态调用图 + 动态追踪事件
    输出：缝合后的调用链（带置信度）
    """

    def __init__(self, cg_path: str = "call_graph_static.json"):
        print(f"[Stitcher] 加载静态调用图: {cg_path}")
        self.cg = CallGraph(cg_path)

        print("[Stitcher] 初始化锚点匹配器...")
        self.matcher = AnchorMatcher(self.cg)

        print("[Stitcher] 初始化置信度计算器...")
        self.conf_calc = ConfidenceCalculator()

        self.events = []
        self.trees = []
        self.trace_chains = []
        self.anchor_index = {}
        self.edge_confidences = {}
        self.stitched_graph = None

    def load_events(self, trace_path: str):
        """加载动态追踪轨迹。"""
        print(f"[Stitcher] 加载动态轨迹: {trace_path}")
        self.events = parse_jsonl(trace_path)
        print(f"[Stitcher]   解析 {len(self.events)} 事件")

        uprobe_n = sum(1 for e in self.events if e.type == "uprobe")
        syscall_n = sum(1 for e in self.events if e.type == "syscall")
        print(f"[Stitcher]   uprobe={uprobe_n}, syscall={syscall_n}")

        print("[Stitcher] 构建请求树（单进程 TID 分组）...")
        self.trees = build_call_tree(self.events)
        print(f"[Stitcher]   {len(self.trees)} 个 TID 请求树")

        print("[Stitcher] 构建跨进程调用链（trace_id 分组）...")
        self.trace_chains = build_trace_chains(self.events)
        cross_chains = [c for c in self.trace_chains if c.get("layer") == "cross_process"]
        print(f"[Stitcher]   {len(self.trace_chains)} 条调用链（其中跨进程: {len(cross_chains)} 条）")

    def run(self):
        """执行缝合。"""
        if not self.events:
            print("[Stitcher] 错误：未加载动态轨迹", file=sys.stderr)
            return

        print("[Stitcher] 构建锚点索引...")
        self.anchor_index = self.matcher.build_anchor_index(self.events)
        print(f"[Stitcher]   锚点命中 {len(self.anchor_index)} 个节点")

        print("[Stitcher] 计算边置信度...")
        self.edge_confidences = self.conf_calc.compute(
            cg_edges=self.cg.edges,
            anchor_index=self.anchor_index,
            events=self.events,
            build_tree_fn=build_call_tree,
        )

        print("[Stitcher] 构建缝合图...")
        self._build_stitched_graph()
        print("[Stitcher]   完成")

    def _build_stitched_graph(self):
        """基于置信度构建最终缝合图。"""
        confirmed = []
        inferred = []
        conflicting = []
        unknown = []

        for edge in self.cg.edges:
            key = (edge.from_node, edge.to_node)
            conf = self.edge_confidences.get(key, Confidence.UNKNOWN)

            entry = {
                "from": edge.from_node,
                "to": edge.to_node,
                "confidence": conf.value,
                "layer_from": self.cg.get_layer(edge.from_node),
                "layer_to": self.cg.get_layer(edge.to_node),
            }

            if conf == Confidence.CONFIRMED:
                confirmed.append(entry)
            elif conf == Confidence.INFERRED:
                inferred.append(entry)
            elif conf == Confidence.CONFLICTING:
                conflicting.append(entry)
            else:
                unknown.append(entry)

        self.stitched_graph = {
            "stitched_at": datetime.datetime.now().isoformat(),
            "total_nodes": len(self.cg.nodes),
            "total_static_edges": len(self.cg.edges),
            "summary": {
                "confirmed": len(confirmed),
                "inferred": len(inferred),
                "conflicting": len(conflicting),
                "unknown": len(unknown),
            },
            "confirmed_edges": confirmed,
            "inferred_edges": inferred,
            "conflicting_edges": conflicting,
            "cross_process_chains": [
                {
                    "trace_id": c["trace_id"],
                    "pids": c.get("pids", []),
                    "events": [
                        {"ts_ns": e.ts_ns, "tid": e.tid, "type": e.type,
                         "func": e.func, "duration_us": e.duration_us}
                        for e in c["events"]
                    ],
                    "total_us": c["total_us"],
                }
                for c in self.trace_chains
                if c.get("layer") == "cross_process"
            ],
        }

    def print_summary(self):
        """打印缝合摘要。"""
        if not self.stitched_graph:
            print("[Stitcher] 未执行缝合，请先调用 stitcher.run()")
            return

        s = self.stitched_graph["summary"]
        print("\n" + "=" * 70)
        print("调用链缝合结果")
        print("=" * 70)
        print(f"  静态节点: {self.stitched_graph['total_nodes']}")
        print(f"  静态边:   {self.stitched_graph['total_static_edges']}")
        print(f"  confirmed: {s['confirmed']}")
        print(f"  inferred:  {s['inferred']}")
        print(f"  conflicting: {s['conflicting']}")
        print(f"  unknown:   {s['unknown']}")

        if s["confirmed"] > 0:
            print("\n[Confirmed 边 - 动态直接观测]")
            for e in self.stitched_graph["confirmed_edges"][:10]:
                print(f"  {e['from']:<45} → {e['to']}")

        if s["inferred"] > 0:
            print(f"\n[Inferred 边 - 静态存在，动态部分观测（前10）]")
            for e in self.stitched_graph["inferred_edges"][:10]:
                print(f"  {e['from']:<45} → {e['to']}")

    def print_anchor_hits(self):
        """打印锚点命中统计。"""
        print("\n[锚点命中详情]")
        print(f"{'函数名':<50} {'命中次数':>8} {'类型':<12}")
        print("-" * 72)
        sorted_hits = sorted(
            self.anchor_index.items(),
            key=lambda x: -len(x[1])
        )
        for node, evs in sorted_hits[:30]:
            layer = self.cg.get_layer(node)
            print(f"  {node:<48} {len(evs):>8}  {layer:<12}")

    def export_json(self, path: str):
        """导出缝合结果为 JSON。"""
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.stitched_graph, f, indent=2, ensure_ascii=False)
        print(f"[Stitcher] 导出: {path}")

    def print_layer_flow(self):
        """按推理流水线打印各层之间的调用关系（跨层边）。"""
        print("\n[推理流水线跨层调用]")
        print(f"{'源层':<20} → {'目标层':<20} {'边数':>5}")
        print("-" * 50)

        cross_layer = defaultdict(list)
        for edge in self.cg.edges:
            lf = self.cg.get_layer(edge.from_node)
            lt = self.cg.get_layer(edge.to_node)
            if lf != lt:
                cross_layer[(lf, lt)].append((edge.from_node, edge.to_node))

        for (lf, lt), pairs in sorted(cross_layer.items()):
            print(f"  {lf:<18} → {lt:<18} {len(pairs):>5}")
            for a, b in pairs[:3]:
                conf_key = (a, b)
                conf = self.edge_confidences.get(conf_key, Confidence.UNKNOWN)
                marker = "*" if conf == Confidence.CONFIRMED else " "
                print(f"    {marker} {a} → {b}")


# ---------------------------------------------------------------------------
# 命令行入口
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Ollama 调用链缝合器：将静态调用图与动态追踪轨迹缝合"
    )
    parser.add_argument("trace", help="统一追踪 JSONL 文件")
    parser.add_argument("--graph", "-g", default="call_graph_static.json",
                        help="静态调用图 JSON（默认: call_graph_static.json）")
    parser.add_argument("--summary", "-s", action="store_true", help="打印缝合摘要")
    parser.add_argument("--anchors", "-a", action="store_true", help="打印锚点命中")
    parser.add_argument("--layer-flow", "-l", action="store_true", help="打印跨层调用")
    parser.add_argument("--export", "-e", help="导出缝合结果 JSON")
    parser.add_argument("--all", action="store_true", help="全部输出")
    args = parser.parse_args()

    if not os.path.exists(args.graph):
        print(f"[ERROR] 找不到调用图: {args.graph}", file=sys.stderr)
        print(f"  请先运行: python3 extract_symbols.py", file=sys.stderr)
        sys.exit(1)

    stitcher = Stitcher(args.graph)
    stitcher.load_events(args.trace)
    stitcher.run()

    do_all = args.all or not any([args.summary, args.anchors, args.layer_flow, args.export])

    if do_all or args.summary:
        stitcher.print_summary()
    if do_all or args.anchors:
        stitcher.print_anchor_hits()
    if do_all or args.layer_flow:
        stitcher.print_layer_flow()
    if args.export:
        stitcher.export_json(args.export)


if __name__ == "__main__":
    main()
