#!/usr/bin/env python3
"""
stitcher_viz.py — 缝合结果可视化：生成 Mermaid 调用图、Graphviz DOT 图和调用树文本。

用法：
    python3 stitcher_viz.py stitched_result.json
    python3 stitcher_viz.py stitched_result.json --mermaid call_tree.md
    python3 stitcher_viz.py stitched_result.json --dot call_tree.dot
    python3 stitcher_viz.py stitched_result.json --tree call_tree.txt
    python3 stitcher_viz.py stitched_result.json --all
"""

import json
import argparse
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# 颜色配置（对应 call_graph_static.json 的 layer 颜色）
# ---------------------------------------------------------------------------
LAYER_COLORS = {
    "go_cgo_bridge": "#e74c3c",
    "llama_api":     "#e67e22",
    "batch_sampler": "#f39c12",
    "sched_compute": "#27ae60",
    "ggml_backend":  "#2980b9",
    "ggml_ops":      "#8e44ad",
    "vocab":         "#16a085",
    "memory":        "#2c3e50",
    "unknown":       "#95a5a6",
}

LAYER_LABELS = {
    "go_cgo_bridge": "Go↔CGO 边界",
    "llama_api":     "Llama API 层",
    "batch_sampler": "批处理/采样",
    "sched_compute": "GGML 调度",
    "ggml_backend":  "GGML 后端",
    "ggml_ops":      "GGML 算子",
    "vocab":         "词表/分词",
    "memory":        "内存分配",
    "unknown":       "未知层",
}

# ---------------------------------------------------------------------------
# Mermaid 图生成
# ---------------------------------------------------------------------------

def to_mermaid_label(name: str, layer: str) -> str:
    """生成 Mermaid 节点标签。"""
    short = name
    if layer == "go_cgo_bridge":
        short = f"🦘{name}"
    elif layer == "llama_api":
        short = f"🔶{name}"
    elif layer == "sched_compute":
        short = f"🟢{name}"
    elif layer == "ggml_ops":
        short = f"🟣{name}"
    elif layer == "batch_sampler":
        short = f"🟡{name}"
    return short


def gen_mermaid(data: dict) -> str:
    """生成 Mermaid 调用图。"""
    lines = [
        "```mermaid",
        "flowchart LR",
        "    %% === 分层布局 ===",
        "    subgraph go_cgo_bridge [Go↔CGO 边界]",
        "        direction TB",
        '        gocgo(("🦘 Go/CGO Bridge"))',
        "    end",
        "    subgraph llama_api [Llama API 层]",
        "        direction TB",
        '        llamaapi(("🔶 Llama API"))',
        "    end",
        "    subgraph batch_sampler [批处理/采样层]",
        "        direction TB",
        '        batchsam(("🟡 Batch/Sampler"))',
        "    end",
        "    subgraph sched_compute [GGML 调度层]",
        "        direction TB",
        '        sched(("🟢 Sched/Compute"))',
        "    end",
        "    subgraph ggml_ops [GGML 算子层]",
        "        direction TB",
        '        ops(("🟣 GGML Ops"))',
        "    end",
        "",
        "    %% === 层间边 ===",
        "    %% Confirmed 边（粗实线）",
    ]

    # 节点名 → 简化 ID
    node_id_map = {}
    uid = 0
    for edge in data.get("confirmed_edges", []) + data.get("inferred_edges", []):
        for n in [edge["from"], edge["to"]]:
            if n not in node_id_map:
                node_id_map[n] = f"N{uid}"
                uid += 1

    # 按层分组节点
    layer_nodes = {}
    for node, uid in node_id_map.items():
        # 从边数据推断层（用已知的层信息）
        for edge in data.get("confirmed_edges", []) + data.get("inferred_edges", []):
            if edge["from"] == node:
                layer = edge.get("layer_from", "unknown")
                break
            elif edge["to"] == node:
                layer = edge.get("layer_to", "unknown")
                break
        else:
            layer = "unknown"
        layer_nodes.setdefault(layer, []).append((node, uid))

    # 生成层内节点
    for layer, nodes in layer_nodes.items():
        label = LAYER_LABELS.get(layer, layer)
        for node, uid in nodes:
            layer_id = layer.replace("_", "")
            lines.append(f'    {uid}{{"{node}"}}:::{layer_id}')

    lines.append("")
    lines.append("    classDef go_cgo_bridge fill:#e74c3c,stroke:#c0392b,color:#fff")
    lines.append("    classDef llama_api fill:#e67e22,stroke:#d35400,color:#fff")
    lines.append("    classDef batch_sampler fill:#f39c12,stroke:#e67e22,color:#fff")
    lines.append("    classDef sched_compute fill:#27ae60,stroke:#1e8449,color:#fff")
    lines.append("    classDef ggml_ops fill:#8e44ad,stroke:#6c3483,color:#fff")
    lines.append("    classDef ggml_backend fill:#2980b9,stroke:#1a5276,color:#fff")
    lines.append("    classDef vocab fill:#16a085,stroke:#0e6655,color:#fff")
    lines.append("    classDef memory fill:#2c3e50,stroke:#1a252f,color:#fff")
    lines.append("    classDef unknown fill:#95a5a6,stroke:#7f8c8d,color:#fff")
    lines.append("")

    # Confirmed 边
    for e in data.get("confirmed_edges", []):
        fid = node_id_map.get(e["from"], "")
        tid = node_id_map.get(e["to"], "")
        if fid and tid:
            lf, lt = e.get("layer_from", ""), e.get("layer_to", "")
            style = "bold" if lf != lt else ""
            lines.append(f'    {fid} -->|"✓ confirmed"| {tid}    %% {e["from"]} → {e["to"]}')

    lines.append("")
    lines.append("    %% === Inferred 边（虚线）===")
    for e in data.get("inferred_edges", []):
        fid = node_id_map.get(e["from"], "")
        tid = node_id_map.get(e["to"], "")
        if fid and tid:
            lines.append(f'    {fid} -.->|"? inferred"| {tid}    %% {e["from"]} → {e["to"]}')

    lines.append("```")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Graphviz DOT 图生成
# ---------------------------------------------------------------------------

def gen_dot(data: dict) -> str:
    """生成 Graphviz DOT 图。"""
    lines = [
        "digraph call_chain {",
        '    rankdir=LR;',
        '    node [fontname="Courier New", fontsize=11];',
        '    edge [fontname="Courier New", fontsize=9];',
        '    splines=ortho;',
        '    nodesep=0.4;',
        '    ranksep=0.8;',
        "",
        '    # 全局样式',
        '    graph [label="Ollama 推理调用链缝合图\\n(实线=confirmed, 虚线=inferred)", fontsize=14];',
        "",
    ]

    # 节点声明
    node_layers = {}
    for edge in data.get("confirmed_edges", []) + data.get("inferred_edges", []):
        for n, key in [(edge["from"], "layer_from"), (edge["to"], "layer_to")]:
            if n not in node_layers:
                node_layers[n] = edge.get(key, "unknown")

    for node, layer in node_layers.items():
        color = LAYER_COLORS.get(layer, "#95a5a6")
        # 简化显示
        short = node[:40] + "..." if len(node) > 40 else node
        lines.append(f'    "{node}" [label="{short}\\n[{layer}]", fillcolor="{color}", style=filled, fontcolor=white];')

    lines.append("")

    # Confirmed 边
    for e in data.get("confirmed_edges", []):
        conf_marker = "✓" if e.get("layer_from") != e.get("layer_to") else "↔"
        lines.append(f'    "{e["from"]}" -> "{e["to"]}" [color=darkgreen, penwidth=2, label="confirmed"];')

    lines.append("")
    lines.append("    # Inferred 边（虚线）")
    for e in data.get("inferred_edges", []):
        lines.append(f'    "{e["from"]}" -> "{e["to"]}" [color=gray, style=dashed, label="inferred"];')

    lines.append("}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 调用树文本生成（分层缩进）
# ---------------------------------------------------------------------------

def gen_call_tree(data: dict) -> str:
    """生成带缩进的调用树文本。"""
    LAYER_ORDER = [
        "go_cgo_bridge", "llama_api", "batch_sampler",
        "sched_compute", "ggml_backend", "ggml_ops", "vocab", "memory", "unknown"
    ]

    # 构建邻接表
    adj = {}
    for e in data.get("confirmed_edges", []) + data.get("inferred_edges", []):
        adj.setdefault(e["from"], []).append(e)

    lines = [
        "=" * 80,
        "Ollama 推理调用链缝合图",
        "=" * 80,
        "",
        "图例：",
        "  ✓ = confirmed（动态直接观测）",
        "  ? = inferred（静态存在 + 部分动态观测）",
        "  ↔ = 跨层调用（重点关注）",
        "",
    ]

    # 分层打印
    from collections import defaultdict
    layer_edges = defaultdict(list)
    for e in data.get("confirmed_edges", []) + data.get("inferred_edges", []):
        lf = e.get("layer_from", "unknown")
        lt = e.get("layer_to", "unknown")
        layer_edges[(lf, lt)].append(e)

    # 打印跨层 confirmed 边
    lines.append("【跨层 Confirmed 调用链（核心证据）】")
    lines.append("-" * 80)
    for (lf, lt), edges in sorted(layer_edges.items()):
        conf_edges = [e for e in edges if e["confidence"] == "confirmed"]
        if not conf_edges:
            continue
        label_lf = LAYER_LABELS.get(lf, lf)
        label_lt = LAYER_LABELS.get(lt, lt)
        lines.append(f"\n  {label_lf}  →  {label_lt}  [{len(conf_edges)} 条 confirmed]")
        for e in conf_edges:
            lines.append(f"    ✓ {e['from']}")
            lines.append(f"      ↓")
            lines.append(f"      {e['to']}")
            lines.append("")

    # 打印 llama.cpp 推理主路径
    lines.append("\n【 llama_decode 推理主路径 】")
    lines.append("-" * 80)
    main_caller = "llama_decode"
    callees = []
    for e in data.get("confirmed_edges", []) + data.get("inferred_edges", []):
        if e["from"] == main_caller:
            callees.append(e)

    lines.append(f"  {main_caller} (Llama API 层)")
    for e in sorted(callees, key=lambda x: x["confidence"], reverse=True):
        conf = "✓" if e["confidence"] == "confirmed" else "?"
        lt = LAYER_LABELS.get(e.get("layer_to", ""), e.get("layer_to", ""))
        lines.append(f"    {conf}→ {e['to']} [{lt}]")

    # 分层汇总
    lines.append("\n【各层调用统计】")
    lines.append("-" * 80)
    for layer in LAYER_ORDER:
        conf_n = sum(1 for e in data.get("confirmed_edges", [])
                     if e.get("layer_from") == layer or e.get("layer_to") == layer)
        inf_n = sum(1 for e in data.get("inferred_edges", [])
                     if e.get("layer_from") == layer or e.get("layer_to") == layer)
        if conf_n or inf_n:
            label = LAYER_LABELS.get(layer, layer)
            lines.append(f"  {label:<25} confirmed={conf_n:>2}  inferred={inf_n:>2}")

    lines.append("")
    lines.append("=" * 80)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 分层流水线 ASCII 图
# ---------------------------------------------------------------------------

def gen_pipeline(data: dict) -> str:
    """生成推理流水线 ASCII 拓扑图。"""
    LAYER_ORDER = [
        "go_cgo_bridge", "llama_api", "batch_sampler",
        "sched_compute", "ggml_backend", "ggml_ops", "vocab", "memory",
    ]

    lines = [
        "=" * 80,
        "Ollama 推理流水线分层调用图",
        "=" * 80,
        "",
        "                    LLM 推理调用链 (Ollama + llama.cpp)",
        "",
        "  ┌──────────────────────────────────────────────────────────────┐",
        "  │                                                              │",
    ]

    layer_nodes = {}
    for e in data.get("confirmed_edges", []) + data.get("inferred_edges", []):
        lf, lt = e.get("layer_from", ""), e.get("layer_to", "")
        for node, layer, direction in [(e["from"], lf, "caller"), (e["to"], lt, "callee")]:
            if layer not in layer_nodes:
                layer_nodes[layer] = {"callers": set(), "callees": set()}
            if direction == "caller":
                layer_nodes[layer]["callers"].add(node)
            else:
                layer_nodes[layer]["callees"].add(node)

    layer_labels = {
        "go_cgo_bridge": "Go↔CGO 边界",
        "llama_api":     "Llama API 层",
        "batch_sampler": "批处理/采样",
        "sched_compute": "GGML 调度",
        "ggml_backend":  "GGML 后端",
        "ggml_ops":      "GGML 算子",
        "vocab":         "词表/分词",
        "memory":        "内存分配",
    }

    arrows = []
    confirmed_pairs = set()
    for e in data.get("confirmed_edges", []):
        lf, lt = e.get("layer_from", ""), e.get("layer_to", "")
        if lf != lt:
            confirmed_pairs.add((lf, lt))

    for i, layer in enumerate(LAYER_ORDER):
        label = layer_labels.get(layer, layer)
        nodes = layer_nodes.get(layer, {})
        color_map = {
            "go_cgo_bridge": "🔴", "llama_api": "🟠", "batch_sampler": "🟡",
            "sched_compute": "🟢", "ggml_backend": "🔵", "ggml_ops": "🟣",
            "vocab": "🟢", "memory": "⚫",
        }
        icon = color_map.get(layer, "⚪")
        conf = sum(1 for p in confirmed_pairs if p[0] == layer or p[1] == layer)
        marker = f"[{conf} confirmed]" if conf else ""
        lines.append(f"  │  {icon} {label:<16} │ {marker}")
        if i < len(LAYER_ORDER) - 1:
            lines.append("  │                            │")

    lines.extend([
        "  │                                                              │",
        "  └──────────────────────────────────────────────────────────────┘",
        "",
    ])

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="缝合结果可视化")
    parser.add_argument("stitched_json", help="stitcher.py 导出的缝合结果 JSON")
    parser.add_argument("--mermaid", "-m", help="导出 Mermaid 图")
    parser.add_argument("--dot", "-d", help="导出 Graphviz DOT 图")
    parser.add_argument("--tree", "-t", help="导出调用树文本")
    parser.add_argument("--pipeline", "-p", help="导出流水线 ASCII 图")
    parser.add_argument("--all", "-a", action="store_true", help="导出全部格式")
    args = parser.parse_args()

    with open(args.stitched_json, "r", encoding="utf-8") as f:
        data = json.load(f)

    summary = data.get("summary", {})
    print(f"缝合结果：confirmed={summary.get('confirmed', 0)}, "
          f"inferred={summary.get('inferred', 0)}")

    do_all = args.all or not any([args.mermaid, args.dot, args.tree, args.pipeline])

    if do_all or args.mermaid:
        mm = gen_mermaid(data)
        if args.mermaid:
            with open(args.mermaid, "w", encoding="utf-8") as f:
                f.write(mm)
            print(f"Mermaid 图已保存: {args.mermaid}")
        else:
            print("\n" + mm)

    if do_all or args.dot:
        dot = gen_dot(data)
        if args.dot:
            with open(args.dot, "w", encoding="utf-8") as f:
                f.write(dot)
            print(f"DOT 图已保存: {args.dot}")
        else:
            print("\n" + dot)

    if do_all or args.tree:
        tree = gen_call_tree(data)
        if args.tree:
            with open(args.tree, "w", encoding="utf-8") as f:
                f.write(tree)
            print(f"调用树已保存: {args.tree}")
        else:
            print("\n" + tree)

    if do_all or args.pipeline:
        pipeline = gen_pipeline(data)
        if args.pipeline:
            with open(args.pipeline, "w", encoding="utf-8") as f:
                f.write(pipeline)
            print(f"流水线图已保存: {args.pipeline}")
        else:
            print("\n" + pipeline)


if __name__ == "__main__":
    main()
