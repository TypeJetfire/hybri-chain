#!/usr/bin/env python3
"""
run_pipeline.py — 编排所有非 sudo 的分析步骤。

用法：
    # 自动运行所有 4 个实验（静态部分）
    python3 run_pipeline.py --all

    # 运行指定实验
    python3 run_pipeline.py --exp-id exp1
    python3 run_pipeline.py --exp-id exp2
    python3 run_pipeline.py --exp-id exp3
    python3 run_pipeline.py --exp-id exp4

步骤（每个实验）：
    1. extract_symbols.py    — 静态符号提取（生成 call_graph_static.json）
    2. build_sequential.py   — 层序号标注（生成 nodes_sequential.json 等）
    3. trace_unify.py       — bpftrace 解析（生成 trace_events.json + llama_folded.txt）
    4. merge_syscall_sequence.py — 系统调用缝合（生成 syscall_sequence.json）

输出结构：
    experiments/
      exp1_tinyllama_dynamic/
        static/           ← extract_symbols 输出
        parsed/           ← trace_unify 输出
        sequenced/        ← build_sequential 输出
        stitched/         ← merge_syscall_sequence 输出
"""

import subprocess
import sys
import os
import argparse
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
TOOLCHAIN = PROJECT_ROOT / 'src' / 'tools'
EXPERIMENTS = PROJECT_ROOT / 'experiments'
OLLAMA_BINARY = Path('/home/typejetfire/graduation_thesis/ollama-debug')

# 实验定义
EXPERIMENTS_DEF = [
    {'id': 'exp1', 'name': 'exp1_tinyllama_dynamic', 'model': 'tinyllama:latest', 'dynamic': True},
    {'id': 'exp2', 'name': 'exp2_tinyllama_static', 'model': 'tinyllama:latest', 'dynamic': False},
    {'id': 'exp3', 'name': 'exp3_qwen_dynamic', 'model': 'qwen:0.5b', 'dynamic': True},
    {'id': 'exp4', 'name': 'exp4_qwen_static', 'model': 'qwen:0.5b', 'dynamic': False},
]


def get_exp_dir(exp_id: str) -> Path:
    for e in EXPERIMENTS_DEF:
        if e['id'] == exp_id:
            return EXPERIMENTS / e['name']
    raise ValueError(f'Unknown exp_id: {exp_id}')


def step_extract(exp_id: str, dry_run=False):
    """步骤1：静态符号提取。"""
    exp_dir = get_exp_dir(exp_id)
    static_dir = exp_dir / 'static'
    static_dir.mkdir(parents=True, exist_ok=True)
    output_json = static_dir / 'call_graph_static.json'

    if dry_run:
        print(f'  [DRY RUN] extract_symbols -o {static_dir}')
        return

    print(f'  extract_symbols -o {static_dir}')
    result = subprocess.run(
        [sys.executable, str(TOOLCHAIN / 'extract_symbols.py'),
         '--binary', str(OLLAMA_BINARY),
         '--output', str(static_dir),
         '-q'],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f'  [ERROR] extract_symbols failed:', file=sys.stderr)
        print(result.stderr, file=sys.stderr)
    return result.returncode == 0


def step_build_seq(exp_id: str, dry_run=False):
    """步骤2：层序号标注。"""
    exp_dir = get_exp_dir(exp_id)
    cg_json = exp_dir / 'static' / 'call_graph_static.json'
    seq_dir = exp_dir / 'sequenced'
    seq_dir.mkdir(parents=True, exist_ok=True)

    if not cg_json.exists():
        print(f'  [SKIP] call_graph_static.json not found at {cg_json}')
        return False

    if dry_run:
        print(f'  [DRY RUN] build_sequential --cg-json {cg_json} -o {seq_dir}')
        return

    print(f'  build_sequential -o {seq_dir}')
    result = subprocess.run(
        [sys.executable, str(TOOLCHAIN / 'build_sequential.py'),
         '--cg-json', str(cg_json),
         '--output-dir', str(seq_dir),
         '-q'],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f'  [ERROR] build_sequential failed:', file=sys.stderr)
        print(result.stderr, file=sys.stderr)
    return result.returncode == 0


def step_trace_unify(exp_id: str, dry_run=False):
    """步骤3：bpftrace 解析。"""
    exp_dir = get_exp_dir(exp_id)
    raw_dir = exp_dir / 'raw'
    parsed_dir = exp_dir / 'parsed'
    parsed_dir.mkdir(parents=True, exist_ok=True)

    bpftrace_file = raw_dir / 'bpftrace.jsonl'
    if not bpftrace_file.exists():
        print(f'  [SKIP] bpftrace.jsonl not found at {bpftrace_file}')
        return False

    if dry_run:
        print(f'  [DRY RUN] trace_unify {bpftrace_file} -o {parsed_dir}')
        return

    print(f'  trace_unify -o {parsed_dir}')
    result = subprocess.run(
        [sys.executable, str(TOOLCHAIN / 'trace_unify.py'),
         str(bpftrace_file),
         '--output-dir', str(parsed_dir),
         '--summary', '--flame'],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f'  [ERROR] trace_unify failed:', file=sys.stderr)
        print(result.stderr, file=sys.stderr)
    return result.returncode == 0


def step_merge(exp_id: str, dry_run=False):
    """步骤4：系统调用缝合。"""
    exp_dir = get_exp_dir(exp_id)
    stitched_dir = exp_dir / 'stitched'
    stitched_dir.mkdir(parents=True, exist_ok=True)

    if dry_run:
        print(f'  [DRY RUN] merge_syscall_sequence --exp-id {exp_id}')
        return

    print(f'  merge_syscall_sequence --exp-id {exp_id}')
    result = subprocess.run(
        [sys.executable, str(TOOLCHAIN / 'merge_syscall_sequence.py'),
         '--exp-id', exp_id,
         '-q'],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f'  [ERROR] merge_syscall_sequence failed:', file=sys.stderr)
        print(result.stderr, file=sys.stderr)
    return result.returncode == 0


def run_experiment(exp_id: str, dry_run=False, steps='1234'):
    """运行单个实验的 pipeline。"""
    print(f'\n========== 实验 {exp_id} ==========')

    for e in EXPERIMENTS_DEF:
        if e['id'] == exp_id:
            print(f'  模型: {e["model"]}')
            print(f'  动态追踪: {"是" if e["dynamic"] else "否"}')
            break

    ok = True
    if '1' in steps:
        ok &= step_extract(exp_id, dry_run) is not False
    if '2' in steps:
        ok &= step_build_seq(exp_id, dry_run) is not False
    if '3' in steps:
        ok &= step_trace_unify(exp_id, dry_run) is not False
    if '4' in steps:
        ok &= step_merge(exp_id, dry_run) is not False

    status = '完成' if ok else '部分完成（缺少原始数据）'
    print(f'  状态: {status}')
    return ok


def print_experiment_summary(exp_id: str):
    """打印实验结果摘要。"""
    exp_dir = get_exp_dir(exp_id)

    for e in EXPERIMENTS_DEF:
        if e['id'] == exp_id:
            print(f'\n========== 实验 {exp_id}: {e["name"]} ==========')
            break

    stitched_json = exp_dir / 'stitched' / 'syscall_sequence.json'
    if stitched_json.exists():
        with open(stitched_json) as f:
            data = json.load(f)
        s = data.get('summary', {})
        print(f'  strace 关键事件: {s.get("strace_key", 0)} 条')
        print(f'  bpftrace 事件: {s.get("bpftrace_total", 0)} 条')
        sc = s.get('syscall_counts', {})
        if sc:
            for k, v in sorted(sc.items(), key=lambda x: -x[1]):
                print(f'    {k}: {v}')
        risk = s.get('risk_counts', {})
        print(f'  风险分布: {risk}')
    else:
        print(f'  [未生成] {stitched_json}')

    seq_json = exp_dir / 'sequenced' / 'call_sequence.json'
    if seq_json.exists():
        with open(seq_json) as f:
            data = json.load(f)
        ls = data.get('layer_summary', {})
        print(f'  各层节点:')
        for layer, info in ls.items():
            print(f'    {info.get("layer_seq_prefix","?")} {layer}: {info.get("node_count",0)} 个节点')
    else:
        print(f'  [未生成] {seq_json}')


def main():
    parser = argparse.ArgumentParser(description='分析 pipeline 编排器（普通权限）')
    parser.add_argument('--all', action='store_true', help='运行所有 4 个实验')
    parser.add_argument('--exp-id', help='指定实验 ID（exp1~exp4）')
    parser.add_argument('--dry-run', action='store_true', help='仅打印将要执行的命令')
    parser.add_argument('--steps', default='1234', help='运行哪些步骤（默认 1234）')
    parser.add_argument('--summary', action='store_true', help='仅打印摘要')
    args = parser.parse_args()

    if args.summary:
        for e in EXPERIMENTS_DEF:
            print_experiment_summary(e['id'])
        return

    if args.all:
        for e in EXPERIMENTS_DEF:
            run_experiment(e['id'], dry_run=args.dry_run, steps=args.steps)
        return

    if args.exp_id:
        run_experiment(args.exp_id, dry_run=args.dry_run, steps=args.steps)
        return

    # 默认：打印帮助
    parser.print_help()
    print('\n用法示例：')
    print('  python3 run_pipeline.py --all           # 运行全部 4 个实验')
    print('  python3 run_pipeline.py --exp-id exp1 # 仅 exp1')
    print('  python3 run_pipeline.py --dry-run    # 预览（不执行）')
    print('  python3 run_pipeline.py --summary      # 仅打印已有结果摘要')


if __name__ == '__main__':
    main()
