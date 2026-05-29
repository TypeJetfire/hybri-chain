#!/usr/bin/env python3
"""
extract_symbols.py — 从 ollama-debug 二进制提取 llama.cpp 符号，构建静态调用图 JSON。

用法：
    python3 extract_symbols.py [BINARY_PATH] [OUTPUT_JSON]
"""

import subprocess
import json
import re
import sys
import argparse
from collections import defaultdict


# llama.cpp 层划分（按推理流水线顺序）
LAYERS = {
    "go_cgo_bridge": {
        "description": "Go → CGO 边界桥接函数",
        "color": "#e74c3c",
    },
    "llama_api": {
        "description": "Llama API 层（顶层推理接口）",
        "color": "#e67e22",
    },
    "batch_sampler": {
        "description": "批处理与采样层",
        "color": "#f39c12",
    },
    "sched_compute": {
        "description": "GGML 调度与计算层",
        "color": "#27ae60",
    },
    "ggml_backend": {
        "description": "GGML 后端内存与调度",
        "color": "#2980b9",
    },
    "ggml_ops": {
        "description": "GGML 张量运算（MulMat/Softmax/RMSNorm 等）",
        "color": "#8e44ad",
    },
    "vocab": {
        "description": "词表与分词/Detokenize",
        "color": "#16a085",
    },
    "memory": {
        "description": "内存分配与 mmap/munmap",
        "color": "#2c3e50",
    },
}

# 手工定义的 llama.cpp 关键调用关系
# key: caller_func -> list of callee_funcs
KNOWN_CALLS = {
    # Go/CGO 边界层
    "_cgoexp_8aa400f2462b_llamarunner_llama_Execute": [
        "llama_decode",
        "llama_batch_add",
        "common_sampler_sample",
    ],
    "_cgo_8aa400f2462b_Cfunc_llama_decode": [
        "llama_decode",
    ],
    "_cgo_8aa400f2462b_Cfunc_llama_sampler_sample": [
        "llama_sampler_sample",
        "common_sampler_sample",
    ],
    "_cgo_8aa400f2462b_Cfunc_common_sampler_csample": [
        "common_sampler_csample",
        "llama_sampler_sample",
    ],
    "_cgo_8aa400f2462b_Cfunc_llama_batch_init": [
        "llama_batch_init",
    ],
    "_cgo_8aa400f2462b_Cfunc_llama_batch_add": [
        "llama_batch_add",
        "common_batch_add",
    ],

    # Llama API 层
    "llama_decode": [
        "ggml_backend_sched_graph_compute_async",
        "llama_synchronize",
        "ggml_backend_sched_synchronize",
    ],
    "llama_batch_add": [
        "llama_batch_add",
        "common_batch_add",
    ],
    "llama_sampler_sample": [
        "common_sampler_sample",
        "llama_sampler_sample",
        "_Z21common_sampler_sample",
    ],
    "common_sampler_sample": [
        "_Z21common_sampler_sample",
    ],

    # 调度层
    "ggml_backend_sched_graph_compute_async": [
        "ggml_backend_graph_compute_async",
        "ggml_backend_sched_synchronize",
        "ggml_backend_sched_reset",
    ],
    "ggml_backend_sched_new": [
        "ggml_backend_sched_alloc_graph",
        "ggml_backend_sched_reserve",
    ],
    "ggml_backend_sched_alloc_graph": [
        "ggml_backend_sched_set_tensor_backend",
        "ggml_graph_new",
    ],
    "ggml_backend_sched_synchronize": [
        "ggml_backend_synchronize",
    ],
    "ggml_backend_graph_compute_async": [
        "ggml_backend_cpu_buffer_type",
        "ggml_backend_graph_compute",
    ],

    # 后端层
    "ggml_backend_synchronize": [
        "ggml_backend_cpu_buffer_type",
    ],
    "ggml_backend_cpu_init": [
        "ggml_backend_cpu_buffer_type",
    ],

    # Sampler 链
    "_Z21common_sampler_sample": [
        "llama_sampler_sample",
        "common_sampler_print",
    ],
    "llama_sampler_init": [
        "llama_sampler_chain_init",
        "common_sampler_init",
    ],
    "llama_sampler_accept": [
        "common_sampler_accept",
    ],

    # 词表层
    "llama_tokenize": [
        "llama_vocab_impl_tokenize",
    ],
    "llama_token_to_piece": [
        "llama_vocab_impl_token_to_piece",
        "common_token_to_piece",
    ],
    "llama_model_load_from_file": [
        "llama_load_model_from_file",
        "llama_model_loader_init_mappings",
        "llama_model_loader_load_tensors",
        "ggml_init",
        "ggml_backend_init_best",
        "ggml_backend_sched_new",
    ],
    "llama_load_model_from_file": [
        "ggml_backend_sched_new",
        "ggml_backend_sched_alloc_graph",
        "ggml_backend_sched_synchronize",
    ],

    # 内存层
    "ggml_backend_buffer_alloc": [
        "ggml_backend_cpu_buffer_type",
        "ggml_aligned_malloc",
    ],
    "ggml_aligned_malloc": [
        "mmap",
    ],
}


def classify_func(func: str) -> str:
    """根据函数名划分层。"""
    func_lower = func.lower()

    if "_cgo_" in func_lower or "_cgoexp_" in func_lower:
        return "go_cgo_bridge"
    if func.startswith("llama_") and any(k in func_lower for k in ["decode", "batch", "sampler", "model", "context", "token"]):
        if "batch" in func_lower or "sampler" in func_lower or "token" in func_lower:
            return "batch_sampler"
        if "model" in func_lower or "context" in func_lower or "decode" in func_lower:
            return "llama_api"
    if "sched" in func_lower or "graph_compute" in func_lower or "graph_plan" in func_lower:
        return "sched_compute"
    if "backend" in func_lower and not "sched" in func_lower:
        return "ggml_backend"
    if func.startswith("ggml_") and not any(k in func_lower for k in ["backend", "sched"]):
        return "ggml_ops"
    if "vocab" in func_lower or "tokenize" in func_lower or "detokenize" in func_lower or "piece" in func_lower:
        return "vocab"
    if "mmap" in func_lower or "munmap" in func_lower or "malloc" in func_lower or "buffer" in func_lower:
        return "memory"
    if func.startswith("llama_") or func.startswith("common_"):
        return "llama_api"

    return "ggml_ops"


def extract_symbols(binary_path: str):
    """从二进制提取符号。"""
    result = subprocess.run(
        ["nm", "-C", "--defined-only", binary_path],
        capture_output=True, text=True, errors="replace"
    )
    symbols = []
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        addr, typ, name = parts[0], parts[1], " ".join(parts[2:])
        if typ not in ("T", "t"):
            continue
        if any(k in name.lower() for k in ["llama", "ggml", "common", "cgo", "vocab"]):
            symbols.append({
                "addr": addr,
                "name": name,
                "type": typ,
                "layer": classify_func(name),
            })
    return symbols


def build_call_graph(symbols):
    """从符号和已知调用关系构建调用图。"""
    # 函数名 → 节点
    nodes = {}
    for sym in symbols:
        name = sym["name"]
        layer = sym["layer"]
        if name not in nodes:
            nodes[name] = {
                "name": name,
                "layer": layer,
                "addr": sym["addr"],
                "description": LAYERS.get(layer, {}).get("description", ""),
            }

    # 边：caller → callee set
    edges_out = defaultdict(set)  # caller -> set of callees
    edges_in = defaultdict(set)   # callee -> set of callers

    for caller, callees in KNOWN_CALLS.items():
        for callee in callees:
            edges_out[caller].add(callee)
            edges_in[callee].add(caller)
            # 确保节点存在
            if callee not in nodes:
                nodes[callee] = {
                    "name": callee,
                    "layer": classify_func(callee),
                    "addr": "",
                    "description": LAYERS.get(classify_func(callee), {}).get("description", ""),
                }

    # 合并成边列表
    edge_list = []
    seen = set()
    for caller, callees in edges_out.items():
        for callee in callees:
            key = (caller, callee)
            if key not in seen:
                seen.add(key)
                edge_list.append({
                    "from": caller,
                    "to": callee,
                    "type": "static",
                    "confidence": "inferred",
                })

    return {
        "version": "1.0",
        "binary": "ollama-debug",
        "total_symbols": len(symbols),
        "layers": LAYERS,
        "nodes": nodes,
        "edges": edge_list,
    }


def main():
    parser = argparse.ArgumentParser(description="从二进制提取 llama.cpp 符号并构建静态调用图")
    parser.add_argument("binary", nargs="?", default="/home/typejetfire/graduation_thesis/ollama-debug",
                        help="ollama-debug 二进制路径")
    parser.add_argument("-o", "--output", default="call_graph_static.json",
                        help="输出 JSON 路径")
    args = parser.parse_args()

    print(f"提取符号: {args.binary}")
    symbols = extract_symbols(args.binary)
    print(f"  找到 {len(symbols)} 个相关符号")

    graph = build_call_graph(symbols)
    print(f"  调用图: {len(graph['nodes'])} 节点, {len(graph['edges'])} 条静态边")

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(graph, f, indent=2, ensure_ascii=False)

    print(f"写入: {args.output}")

    # 统计每层节点数
    layer_counts = defaultdict(int)
    for node in graph["nodes"].values():
        layer_counts[node["layer"]] += 1
    print("\n各层节点数：")
    for layer, count in sorted(layer_counts.items(), key=lambda x: -x[1]):
        desc = LAYERS.get(layer, {}).get("description", "")
        print(f"  {layer:<20} {count:>3}  {desc}")


if __name__ == "__main__":
    main()
