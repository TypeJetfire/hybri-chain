#!/usr/bin/env python3
"""
build_sequential.py — 为静态调用图添加层序号，并生成拓扑排序的调用序列。

用法：
    python3 build_sequential.py --cg-json INPUT -o OUTPUT_DIR
    python3 build_sequential.py --exp-id EXP_ID

接受参数：
    --cg-json   : 静态调用图 JSON（默认从 config 读取）
    --output-dir: 输出目录（可选）
    --exp-id    : 实验 ID，自动推断路径
    -q           : 减少输出
"""

import json
import csv
import os
import argparse
from collections import defaultdict, deque
from pathlib import Path

# 实验 ID → 目录名的映射（保持与 run_pipeline.py 和 run_all_experiments.sh 一致）
_EXP_DIR_MAP = {
    'exp1': 'exp1_tinyllama_dynamic',
    'exp2': 'exp2_tinyllama_static',
    'exp3': 'exp3_qwen_dynamic',
    'exp4': 'exp4_qwen_static',
}
_PROJ = str(Path(__file__).resolve().parent.parent.parent)

LAYER_ORDER = [
    'go_cgo_bridge', 'llama_api', 'batch_sampler',
    'sched_compute', 'ggml_backend', 'ggml_ops', 'vocab', 'memory',
]

LAYER_DESCRIPTIONS = {
    'go_cgo_bridge': 'Go → CGO 边界桥接函数',
    'llama_api':      'Llama API 层（顶层推理接口）',
    'batch_sampler':  '批处理与采样',
    'sched_compute':  'GGML 调度与计算层',
    'ggml_backend':  'GGML 后端内存与调度',
    'ggml_ops':      'GGML 张量运算',
    'vocab':         '词表与分词/Detokenize',
    'memory':        '内存分配与 mmap/munmap',
}

LAYER_INFO = {
    'L1': 'go_cgo_bridge — Go -> CGO 边界桥接函数',
    'L2': 'llama_api — Llama API 层',
    'L3': 'batch_sampler — 批处理与采样',
    'L4': 'sched_compute — GGML 调度与计算',
    'L5': 'ggml_backend — GGML 后端内存',
    'L6': 'ggml_ops — GGML 张量运算',
    'L7': 'vocab — 词表与分词',
    'L8': 'memory — mmap/munmap 系统调用',
    'SYSCALL': 'Linux 内核系统调用（最终层）',
}


def run(cg_json_path=None, output_dir=None, exp_id=None, quiet=False):
    """主执行函数。"""

    # 确定路径
    if exp_id:
        exp_dir = _EXP_DIR_MAP.get(exp_id, exp_id)
        base = f'{_PROJ}/experiments/{exp_dir}'
        if cg_json_path is None:
            cg_json_path = f'{base}/static/call_graph_static.json'
        if output_dir is None:
            output_dir = f'{base}/sequenced'
    else:
        cg_json_path = cg_json_path or f'{_PROJ}/src/stitcher/call_graph_static.json'
        output_dir = output_dir or f'{_PROJ}/src/tools'

    if cg_json_path is None:
        cg_json_path = f'{_PROJ}/src/stitcher/call_graph_static.json'

    os.makedirs(output_dir, exist_ok=True)

    with open(cg_json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    nodes_raw = data.get('nodes', {})
    edges_raw = data.get('edges', [])

    if not quiet:
        print(f'原始节点: {len(nodes_raw)}, 原始边: {len(edges_raw)}')

    # ========== Step 1: 为节点分配层序号 ==========
    layer_prefix = {LAYER_ORDER[i]: f'L{i+1}' for i in range(len(LAYER_ORDER))}
    layer_nodes = defaultdict(list)
    for node_id, attrs in nodes_raw.items():
        layer_nodes[attrs.get('layer', 'unknown')].append((node_id, attrs))

    node_to_seq = {}
    for layer_name in LAYER_ORDER:
        node_list = layer_nodes.get(layer_name, [])
        prefix = layer_prefix.get(layer_name, f'L{len(LAYER_ORDER)}')
        for i, (node_id, _) in enumerate(sorted(node_list), start=1):
            node_to_seq[node_id] = f'{prefix}_{i:03d}'

    # ========== Step 2: 为边加上序号 ==========
    edges_sequential = []
    for edge in edges_raw:
        from_seq = node_to_seq.get(edge['from'], edge['from'])
        to_seq = node_to_seq.get(edge['to'], edge['to'])
        edges_sequential.append({
            'from': edge['from'],
            'to': edge['to'],
            'from_seq': from_seq,
            'to_seq': to_seq,
            'type': edge.get('type', 'static'),
            'confidence': edge.get('confidence', 'inferred'),
        })

    # ========== Step 3: 拓扑排序生成调用序列 ==========
    graph = defaultdict(list)
    in_degree = defaultdict(int)
    all_nodes = set()

    for edge in edges_sequential:
        caller, callee = edge['from'], edge['to']
        all_nodes.add(caller)
        all_nodes.add(callee)
        graph[caller].append(callee)
        in_degree[callee] += 1
    for node in all_nodes:
        in_degree.setdefault(node, 0)

    # Kahn 算法
    queue = deque([n for n in all_nodes if in_degree[n] == 0])
    topo_order = []
    while queue:
        node = queue.popleft()
        topo_order.append(node)
        for neighbor in graph[node]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    # 调用序列（按拓扑序 + 层序号排列）
    call_sequence = []
    for i, node_id in enumerate(topo_order, 1):
        seq = node_to_seq.get(node_id, node_id)
        layer = nodes_raw.get(node_id, {}).get('layer', 'unknown')
        call_sequence.append({
            'seq': i,
            'node_id': node_id,
            'layer_seq': seq,
            'layer': layer,
            'layer_desc': LAYER_DESCRIPTIONS.get(layer, ''),
        })

    # ========== Step 4: 生成层摘要 ==========
    layer_summary = {}
    for layer_name in LAYER_ORDER:
        nodes_in_layer = [n for n in call_sequence if n['layer'] == layer_name]
        layer_summary[layer_name] = {
            'layer_seq_prefix': layer_prefix.get(layer_name, f'L{len(LAYER_ORDER)}'),
            'node_count': len(nodes_in_layer),
            'description': LAYER_DESCRIPTIONS.get(layer_name, ''),
            'sample_nodes': [n['node_id'] for n in nodes_in_layer[:5]],
        }

    if not quiet:
        print('\n各层节点数：')
        for layer_name in LAYER_ORDER:
            info = layer_summary.get(layer_name, {})
            desc = info.get('description', '')
            cnt = info.get('node_count', 0)
            prefix = info.get('layer_seq_prefix', '')
            print(f'  {prefix} {layer_name:<20} {cnt:>3}  {desc}')

    # ========== Step 5: 输出文件 ==========
    # 5a. nodes_sequential.json
    nodes_out = {}
    for node_id, attrs in nodes_raw.items():
        nodes_out[node_id] = {
            'original': node_id,
            'layer_seq': node_to_seq.get(node_id, node_id),
            'layer': attrs.get('layer', 'unknown'),
            'addr': attrs.get('addr', ''),
            'description': attrs.get('description', ''),
        }

    nodes_seq_data = {
        'layers': {name: {'layer_idx': i+1, 'description': LAYER_DESCRIPTIONS[name]}
                   for i, name in enumerate(LAYER_ORDER)},
        'nodes': nodes_out,
    }
    nodes_seq_path = os.path.join(output_dir, 'nodes_sequential.json')
    with open(nodes_seq_path, 'w', encoding='utf-8') as f:
        json.dump(nodes_seq_data, f, ensure_ascii=False, indent=2)

    # 5b. call_sequence.json
    seq_data = {
        'topological_order': topo_order,
        'call_sequence': call_sequence,
        'layer_summary': layer_summary,
    }
    seq_path = os.path.join(output_dir, 'call_sequence.json')
    with open(seq_path, 'w', encoding='utf-8') as f:
        json.dump(seq_data, f, ensure_ascii=False, indent=2)

    # 5c. CSV 导出（nodes.csv + edges.csv）
    nodes_csv_path = os.path.join(output_dir, 'nodes.csv')
    edges_csv_path = os.path.join(output_dir, 'edges.csv')

    with open(nodes_csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['Id', 'Label', 'Layer', 'Layer_Seq', 'Addr'])
        for node_id, attrs in nodes_raw.items():
            writer.writerow([
                node_id, node_id,
                attrs.get('layer', 'unknown'),
                node_to_seq.get(node_id, ''),
                attrs.get('addr', ''),
            ])

    with open(edges_csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['Source', 'Target', 'Type', 'Confidence', 'From_Seq', 'To_Seq'])
        for edge in edges_sequential:
            writer.writerow([
                edge['from'], edge['to'],
                edge.get('type', 'Directed'),
                edge.get('confidence', 'inferred'),
                edge['from_seq'],
                edge['to_seq'],
            ])

    # 5d. 可读文本
    txt_path = os.path.join(output_dir, 'call_sequence.txt')
    with open(txt_path, 'w', encoding='utf-8') as f:
        f.write('=' * 80 + '\n')
        f.write('静态调用图 — 拓扑排序调用序列\n')
        f.write('=' * 80 + '\n\n')
        f.write(f'总节点: {len(nodes_raw)}, 总边: {len(edges_raw)}\n\n')

        f.write('【层序号体系】\n')
        for i, name in enumerate(LAYER_ORDER, 1):
            prefix = layer_prefix.get(name, f'L{i}')
            desc = LAYER_DESCRIPTIONS.get(name, '')
            cnt = layer_summary.get(name, {}).get('node_count', 0)
            f.write(f'  {prefix} {name:<20} {cnt:>3} 个节点  {desc}\n')

        f.write(f'\n{"=" * 80}\n')
        f.write(f'{"#":<5} {"层序号":<10} {"层名":<20} {"函数名":<40}\n')
        f.write(f'{"-" * 80}\n')
        for item in call_sequence:
            f.write(f"{item['seq']:<5} {item['layer_seq']:<10} {item['layer']:<20} {item['node_id']:<40}\n")
        f.write('=' * 80 + '\n')

    if not quiet:
        print(f'\n输出: {nodes_seq_path}')
        print(f'输出: {seq_path}')
        print(f'输出: {nodes_csv_path}')
        print(f'输出: {edges_csv_path}')
        print(f'输出: {txt_path}')

    return {
        'nodes_seq_path': nodes_seq_path,
        'seq_path': seq_path,
        'nodes_csv': nodes_csv_path,
        'edges_csv': edges_csv_path,
        'txt_path': txt_path,
        'call_sequence': call_sequence,
        'layer_summary': layer_summary,
    }


def main():
    parser = argparse.ArgumentParser(description='静态调用图层序号标注与拓扑排序')
    parser.add_argument('--cg-json', help='静态调用图 JSON 路径')
    parser.add_argument('--output-dir', '-o', help='输出目录')
    parser.add_argument('--exp-id', help='实验 ID（exp1~exp4），自动推断路径')
    parser.add_argument('-q', '--quiet', action='store_true', help='减少输出')
    args = parser.parse_args()

    run(
        cg_json_path=args.cg_json,
        output_dir=args.output_dir,
        exp_id=args.exp_id,
        quiet=args.quiet,
    )


if __name__ == '__main__':
    main()
