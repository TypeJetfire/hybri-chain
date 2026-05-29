#!/usr/bin/env python3
"""
merge_syscall_sequence.py — 将 strace 和 bpftrace 数据合并为完整系统调用序列。

用法：
    python3 merge_syscall_sequence.py --exp-id EXP_ID
    python3 merge_syscall_sequence.py \\
        --strace STRACE_TXT \\
        --bpftrace BPFTRACE_JSONL \\
        --cg-json CALL_GRAPH_JSON \\
        --output-dir OUTPUT_DIR

输入：
    - strace.txt            : strace 原始日志
    - bpftrace.jsonl        : bpftrace 原始输出（可选）
    - call_graph_static.json : 静态调用图（来自 extract_symbols.py）

输出：
    - syscall_sequence.json   : 完整结构化数据
    - syscall_sequence.txt    : 可读文本版本
"""

import json
import re
import os
import sys
import argparse
from collections import defaultdict

# ========== 全局关键词配置 ==========
from pathlib import Path

# 项目根目录（向上三级：tools → src → hybri-chain）
_PROJ = str(Path(__file__).resolve().parent.parent.parent)
# ollama-debug 二进制在父目录（不在 hybri-chain 内，保持绝对路径）
OLLAMA_BINARY = '/home/typejetfire/graduation_thesis/ollama-debug'
OLLAMA_TRACES = '/home/typejetfire/graduation_thesis/ollama_traces'
TRACE_JSONL = f'{_PROJ}/trace_unified.jsonl'

_EXP_DIR_MAP = {
    'exp1': 'exp1_tinyllama_dynamic',
    'exp2': 'exp2_tinyllama_static',
    'exp3': 'exp3_qwen_dynamic',
    'exp4': 'exp4_qwen_static',
}

INTERESTING_SYSCALLS = {
    'openat', 'read', 'write', 'send', 'sendto', 'recv', 'recvfrom',
    'mmap', 'munmap', 'clone3', 'clone', 'futex', 'close',
}
IGNORE_SYSCALLS = {
    'brk', 'mprotect', 'madvise', 'munmap',
    'clock_gettime', 'gettimeofday',
    'rt_sigaction', 'rt_sigprocmask', 'sigaltstack',
    'ugetrlimit', 'access', 'pipe', 'pipe2',
    'epoll_ctl', 'epoll_wait', 'eventfd2',
    'prlimit64', 'sysinfo', 'getuid', 'geteuid',
    'newfstatat', 'fstat', 'getdents64',
    'getrandom', 'capget', 'capset', 'uname',
    'sched_getaffinity', 'nanosleep', 'wait4',
}
OLLAMA_KEYWORDS = [
    '.ollama', 'ollama', 'blob', '.gguf',
    'server.json', 'registry', 'model',
    'llama', 'ggml', 'qwen', 'sha256', 'tinyllama',
]
LAYER_ORDER = [
    'go_cgo_bridge', 'llama_api', 'batch_sampler',
    'sched_compute', 'ggml_backend', 'ggml_ops', 'vocab', 'memory',
]


def parse_syscall_args(syscall, args_raw):
    args = {}
    if syscall == 'clone3':
        flags_m = re.search(r'flags=(CLONE_\w+(?:\|CLONE_\w+)*)', args_raw)
        if flags_m: args['flags'] = flags_m.group(1)
        child_tid_m = re.search(r'child_tid=([\da-fx]+)', args_raw)
        if child_tid_m: args['child_tid'] = child_tid_m.group(1)
    elif syscall == 'mmap':
        addr_m = re.search(r'(0x[\da-f]+|NULL)', args_raw)
        if addr_m: args['addr'] = addr_m.group(1)
        len_m = re.search(r',\s*(\d+)', args_raw)
        if len_m: args['len'] = int(len_m.group(1))
        if 'PROT_READ' in args_raw: args['prot'] = 'READ'
        if 'PROT_WRITE' in args_raw: args['prot'] = (args.get('prot', '') + '+WRITE').strip('+')
        if 'MAP_ANONYMOUS' in args_raw: args['anon'] = True
        if 'MAP_PRIVATE' in args_raw: args['flags'] = 'PRIVATE'
        if 'MAP_FIXED' in args_raw: args['flags'] = (args.get('flags', '') + '+FIXED').strip('+')
        fd_m = re.search(r'fd=(-?\d+)', args_raw)
        if fd_m: args['fd'] = int(fd_m.group(1))
    elif syscall in ('read', 'write', 'send', 'sendto', 'recv', 'recvfrom'):
        fd_m = re.search(r'^(\d+)', args_raw)
        if fd_m: args['fd'] = int(fd_m.group(1))
    elif syscall == 'openat':
        path_m = re.search(r'"([^"]+)"', args_raw)
        if path_m: args['pathname'] = path_m.group(1)
        if 'O_DIRECTORY' in args_raw: args['is_dir'] = True
    return args


def describe_and_risk(ev):
    syscall = ev['syscall']
    args = ev['args']
    raw = ev['raw']
    path = args.get('pathname', '')
    risk = 'LOW'
    desc = syscall

    if syscall == 'clone3':
        flags = args.get('flags', '')
        child = args.get('child_tid', '')
        if 'CLONE_THREAD' in flags and 'CLONE_VM' in flags:
            desc = f'clone3 创建线程 child={child}'
        else:
            desc = f'clone3 fork 进程 child={child}'
            risk = 'MEDIUM'
    elif syscall == 'mmap':
        size = args.get('len', 0)
        size_mb = size / (1024 * 1024) if size else 0
        if size_mb >= 500:
            risk = 'HIGH'
            desc = f'mmap KV Cache 预分配 {size_mb:.0f}MB'
        elif size_mb >= 100:
            risk = 'HIGH'
            desc = f'mmap 大块内存 {size_mb:.0f}MB'
        elif size_mb >= 1:
            desc = f'mmap 内存映射 {size_mb:.1f}MB'
        else:
            desc = f'mmap {size//1024}KB'
    elif syscall == 'openat':
        bn = os.path.basename(path) if path else path
        if 'blob' in path or '.gguf' in path:
            risk = 'HIGH'
            desc = f'openat 打开模型文件: {bn}'
        elif '.ollama' in path or 'registry' in path:
            risk = 'MEDIUM'
            desc = f'openat Ollama配置: {bn}'
        elif bn:
            desc = f'openat: {bn}'
        else:
            desc = 'openat'
    elif syscall in ('read', 'write'):
        fd = args.get('fd', '-')
        desc = f'{syscall}(fd={fd})'
    elif syscall in ('sendto', 'send'):
        if '127.0.0.1' in raw or 'localhost' in raw:
            desc = f'{syscall}(内部HTTP，runner-daemon)'
            risk = 'LOW'
        else:
            desc = f'{syscall}(网络发送!)'
            risk = 'HIGH'
    elif syscall == 'futex':
        desc = 'futex 同步等待'
    elif syscall == 'close':
        desc = f'close(fd={args.get("fd","?")})'
    return desc, risk


def assign_stage(ev):
    syscall = ev['syscall']
    args = ev['args']
    raw = ev['raw']
    path = args.get('pathname', '')
    size = args.get('len', 0)

    if syscall == 'clone3':
        return 'stage_fork'
    elif syscall == 'mmap' and size >= 8 * 1024 * 1024:
        return 'stage_model_load'
    elif syscall == 'openat':
        if any(k in path for k in ['blob', '.gguf', 'registry', '.ollama', 'llama', 'ggml']):
            return 'stage_model_load'
        return 'stage_init'
    elif syscall in ('read', 'write', 'sendto', 'send'):
        if '/tmp/' in path or '/tmp/' in raw:
            return 'stage_model_load'
        elif '.ollama' in path:
            return 'stage_model_load'
        elif syscall in ('sendto', 'send') and ('127.0.0.1' in raw or 'localhost' in raw):
            return 'stage_network'
        return 'stage_inference'
    elif syscall == 'futex':
        return 'stage_inference'
    return 'stage_init'


def is_ollama_related(ev):
    syscall = ev['syscall']
    if syscall in {'mmap', 'clone3', 'futex', 'sendto', 'send', 'recv', 'recvfrom'}:
        return True
    raw = ev.get('raw', '') + str(ev.get('args', {}))
    return any(kw in raw.lower() for kw in OLLAMA_KEYWORDS)


def parse_strace_line(line):
    """解析单行 strace，使用括号计数处理嵌套结构。"""
    line = line.strip()
    if not line or line.startswith('---'):
        return None

    m = re.match(r'(\d+)\s+([\d:.]+)\s+(\w+)\(', line)
    if not m:
        return None

    pid = int(m.group(1))
    ts = m.group(2)
    syscall = m.group(3)
    rest = line[m.end()-1:]

    if syscall in IGNORE_SYSCALLS:
        return None
    if syscall not in INTERESTING_SYSCALLS:
        return None

    depth = 0
    for i, ch in enumerate(rest):
        if ch == '(' or ch == '{':
            depth += 1
        elif ch == ')' or ch == '}':
            depth -= 1
            if depth == 0:
                args_raw = rest[1:i]
                ret = rest[i+1:].strip()
                args = parse_syscall_args(syscall, args_raw)
                return {
                    'pid': pid, 'ts': ts, 'syscall': syscall,
                    'args': args, 'ret': ret, 'raw': line,
                }
    return None


def parse_bpftrace(content):
    """解析 bpftrace JSONL 输出。"""
    pattern = re.compile(r'@SYSCALL@\s+(\w+)\s+(\d+)\s+(\d+)\s+(.*?)(?=\n@END@)', re.DOTALL)
    events = []
    for m in pattern.finditer(content):
        syscall = m.group(1)
        if syscall in IGNORE_SYSCALLS:
            continue
        ts_ns = int(m.group(2))
        pid = int(m.group(3))
        args_str = m.group(4).strip()
        args = {}
        for arg_pair in args_str.split():
            if '=' in arg_pair:
                k, v = arg_pair.split('=', 1)
                try:
                    args[k] = int(v)
                except ValueError:
                    args[k] = v
        events.append({'ts_ns': ts_ns, 'pid': pid, 'syscall': syscall, 'args': args})
    return events


def parse_uprobe_events(bpftrace_path):
    """从 bpftrace.jsonl 中提取 @UPROBE@ 事件及统计。"""
    uprobe_counts = defaultdict(int)
    uprobe_total_us = defaultdict(int)
    uprobe_avg_us = {}
    uprobe_max_us = {}

    if not os.path.exists(bpftrace_path):
        return {}

    with open(bpftrace_path, 'r', encoding='utf-8', errors='replace') as f:
        for line in f:
            if '@UPROBE@' not in line:
                continue
            parts = line.strip().split()
            if len(parts) < 5:
                continue
            func = parts[1]
            dur_us = int(parts[4])
            uprobe_counts[func] += 1
            uprobe_total_us[func] += dur_us

    for func in uprobe_counts:
        uprobe_avg_us[func] = round(uprobe_total_us[func] / uprobe_counts[func], 2)
        uprobe_max_us[func] = uprobe_total_us[func]  # placeholder, tracked per-event below

    # re-read for max
    uprobe_max = defaultdict(int)
    with open(bpftrace_path, 'r', encoding='utf-8', errors='replace') as f:
        for line in f:
            if '@UPROBE@' not in line:
                continue
            parts = line.strip().split()
            if len(parts) < 5:
                continue
            func = parts[1]
            dur_us = int(parts[4])
            if dur_us > uprobe_max[func]:
                uprobe_max[func] = dur_us

    return {
        'uprobe_counts': dict(uprobe_counts),
        'uprobe_total_us': dict(uprobe_total_us),
        'uprobe_avg_us': uprobe_avg_us,
        'uprobe_max_us': dict(uprobe_max),
    }


def build_layer_seq(cg_json_path):
    """构建层序号映射。"""
    try:
        with open(cg_json_path, 'r', encoding='utf-8') as f:
            cg_data = json.load(f)
    except Exception:
        return {}, {}

    nodes_raw = cg_data.get('nodes', {})
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

    return node_to_seq, cg_data


def run(strace_path=None, bpftrace_path=None, cg_json_path=None,
        output_dir=None, exp_id=None, quiet=False):
    """主执行函数。"""

    # 确定路径
    if exp_id:
        exp_dir = _EXP_DIR_MAP.get(exp_id, exp_id)
        base = f'{_PROJ}/experiments/{exp_dir}'
        if strace_path is None:
            # strace_run.txt 追踪推理过程（ollama run），strace.txt 追踪 daemon
            strace_path = f'{base}/raw/strace_run.txt'
        if bpftrace_path is None:
            bpftrace_path = f'{base}/raw/bpftrace.jsonl'
        if cg_json_path is None:
            cg_json_path = f'{base}/static/call_graph_static.json'
        if output_dir is None:
            output_dir = f'{base}/stitched'
    else:
        strace_path = strace_path or f'{OLLAMA_TRACES}/strace_daemon_full.txt'
        bpftrace_path = bpftrace_path or f'{_PROJ}/trace_unified.jsonl'
        cg_json_path = cg_json_path or f'{_PROJ}/src/stitcher/call_graph_static.json'
        output_dir = output_dir or f'{_PROJ}/src/tools'

    os.makedirs(output_dir, exist_ok=True)

    # 构建层序号映射
    node_to_seq, cg_data = build_layer_seq(cg_json_path)

    # ========== 解析 bpftrace ==========
    bpftrace_events = []
    bpftrace_by_type = defaultdict(int)
    if bpftrace_path and os.path.exists(bpftrace_path):
        with open(bpftrace_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        bpftrace_events = parse_bpftrace(content)
        for e in bpftrace_events:
            bpftrace_by_type[e['syscall']] += 1
        if not quiet:
            print(f'bpftrace 事件: {len(bpftrace_events)} 条')
    else:
        if not quiet:
            print(f'[WARN] bpftrace 文件不存在: {bpftrace_path}')

    # ========== 解析 uprobe 事件（Llama.cpp 函数级追踪）==========
    uprobe_stats = parse_uprobe_events(bpftrace_path)
    if uprobe_stats.get('uprobe_counts') and not quiet:
        for fn, cnt in sorted(uprobe_stats['uprobe_counts'].items()):
            total_ms = uprobe_stats['uprobe_total_us'][fn] / 1000
            avg_us = uprobe_stats['uprobe_avg_us'][fn]
            print(f'  UPROBE {fn}: {cnt}次, 总耗时{total_ms:.1f}ms, 均{avg_us:.0f}μs, 最大{uprobe_stats["uprobe_max_us"][fn]:.0f}μs')

    # ========== 解析 strace ==========
    key_events = []
    seq_counter = 0

    if strace_path and os.path.exists(strace_path):
        with open(strace_path, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()

        for raw_line in lines:
            if '<unfinished' in raw_line or '<... resumed>' in raw_line:
                continue
            ev = parse_strace_line(raw_line)
            if not ev:
                continue
            if not is_ollama_related(ev):
                continue

            seq_counter += 1
            desc, risk = describe_and_risk(ev)
            stage = assign_stage(ev)
            key_events.append({
                'seq': seq_counter,
                'ts': ev['ts'],
                'pid': ev['pid'],
                'syscall': ev['syscall'],
                'args': ev['args'],
                'ret': ev['ret'],
                'stage': stage,
                'description': desc,
                'risk': risk,
            })

        if not quiet:
            print(f'strace 关键事件: {len(key_events)} 条')
    else:
        if not quiet:
            print(f'[WARN] strace 文件不存在: {strace_path}')

    # ========== 统计 ==========
    syscall_counts = defaultdict(int)
    stage_counts = defaultdict(int)
    risk_counts = defaultdict(int)
    for ev in key_events:
        syscall_counts[ev['syscall']] += 1
        stage_counts[ev['stage']] += 1
        risk_counts[ev['risk']] += 1

    stage_labels = {
        'stage_init': '进程初始化',
        'stage_fork': '进程fork',
        'stage_model_load': '模型加载',
        'stage_inference': '推理执行',
        'stage_network': '网络通信',
    }

    # ========== 输出 JSON ==========
    output = {
        'summary': {
            'bpftrace_total': len(bpftrace_events),
            'strace_key': len(key_events),
            'bpftrace_by_type': dict(bpftrace_by_type),
            'syscall_counts': dict(syscall_counts),
            'stage_counts': {stage_labels.get(k, k): v for k, v in stage_counts.items()},
            'risk_counts': dict(risk_counts),
            **uprobe_stats,
        },
        'sequence': key_events,
    }

    json_path = os.path.join(output_dir, 'syscall_sequence.json')
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # ========== 输出 TXT ==========
    risk_icon = {'LOW': '  ', 'MEDIUM': '⚠', 'HIGH': '🔴'}
    txt_path = os.path.join(output_dir, 'syscall_sequence.txt')

    with open(txt_path, 'w', encoding='utf-8') as f:
        f.write('=' * 100 + '\n')
        f.write('Ollama 系统调用完整序列\n')
        f.write('=' * 100 + '\n\n')
        f.write(f'【数据来源】\n')
        f.write(f'  strace: {strace_path}\n')
        f.write(f'  bpftrace: {bpftrace_path}\n')
        f.write(f'  静态调用图: {cg_json_path}\n\n')
        f.write(f'  bpftrace 事件总数: {len(bpftrace_events)}\n')
        f.write(f'  strace 关键事件: {len(key_events)}\n\n')

        if bpftrace_by_type:
            f.write('【bpftrace 系统调用统计】\n')
            for sc, cnt in sorted(bpftrace_by_type.items(), key=lambda x: -x[1]):
                f.write(f'  {sc}: {cnt} 次\n')
            f.write('\n')

        f.write('=' * 100 + '\n')
        f.write(f'{"#":<5} {"阶段":<14} {"syscall":<18} {"PID":<8} {"描述":<52} {"风险"}\n')
        f.write('-' * 110 + '\n')
        for ev in key_events:
            stage_l = stage_labels.get(ev['stage'], ev['stage'])
            icon = risk_icon.get(ev['risk'], '?')
            desc = ev['description'][:50]
            f.write(f"{ev['seq']:<5} {stage_l:<14} {ev['syscall']:<18} {ev['pid']:<8} {desc:<52} {icon} {ev['risk']}\n")
        f.write('=' * 100 + '\n')
        f.write(f'共 {len(key_events)} 条关键系统调用\n')

    if not quiet:
        print(f'输出 JSON: {json_path}')
        print(f'输出 TXT:  {txt_path}')

    return output


def main():
    parser = argparse.ArgumentParser(description='系统调用序列合并工具')
    parser.add_argument('--exp-id', help='实验 ID（exp1~exp4），自动推断路径')
    parser.add_argument('--strace', help='strace 输出文件路径')
    parser.add_argument('--bpftrace', help='bpftrace 输出文件路径')
    parser.add_argument('--cg-json', help='静态调用图 JSON 路径')
    parser.add_argument('-o', '--output-dir', help='输出目录')
    parser.add_argument('-q', '--quiet', action='store_true', help='减少输出')
    args = parser.parse_args()

    run(
        exp_id=args.exp_id,
        strace_path=args.strace,
        bpftrace_path=args.bpftrace,
        cg_json_path=args.cg_json,
        output_dir=args.output_dir,
        quiet=args.quiet,
    )


if __name__ == '__main__':
    main()
