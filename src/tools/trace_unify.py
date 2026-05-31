#!/usr/bin/env python3
"""
trace_unify.py — 解析 bpftrace 输出文件，生成调用树和折叠栈。

用法：
    python3 trace_unify.py INPUT -o OUTPUT_DIR
    python3 trace_unify.py INPUT --tree --summary --flame

接受参数：
    --input, 位置参数   : bpftrace 原始输出文件路径
    --output-dir, -o   : 输出目录（可选）
    --tree             : 打印调用树
    --summary          : 打印统计摘要
    --flame            : 生成折叠栈
    --all              : 全部输出（默认）
"""

import json
import sys
import argparse
import os
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Event:
    ts_ns: int
    tid: int
    type: str          # 'uprobe' | 'syscall' | 'traceid'
    func: str
    duration_us: int
    stack: list = field(default_factory=list)
    comm: str = ''
    extra: dict = field(default_factory=dict)
    trace_id: str = ''  # HybriChain: cross-process trace ID from X-Request-ID


def parse_jsonl(path: str):
    """解析 bpftrace 输出文件。"""
    events = []
    cur_type = None
    cur_func = ''
    cur_ts_ns = 0
    cur_tid = 0
    cur_dur = 0
    cur_stack = []
    cur_trace_id = ''   # HybriChain: active trace_id for the current tid
    extra = {}
    active_trace_id = {}  # tid(int) -> trace_id(str), updated by @TRACEID@ events

    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        for raw in f:
            line = raw.rstrip('\n')
            stripped = line.strip()

            if (not stripped or stripped.startswith('Tracing') or
                stripped.startswith('Stop') or stripped.startswith('--- ') or
                stripped.startswith('Attaching')):
                continue

            if stripped.startswith('@TRACEID@ '):
                # @TRACEID@ daemon_entry|runner_entry ts_ns pid traceID
                # Update the active trace_id for this pid (tid). All subsequent
                # uprobe/syscall events with the same tid belong to this trace.
                parts = stripped.split(maxsplit=4)
                if len(parts) >= 5:
                    tid_key = int(parts[3])
                    active_trace_id[tid_key] = parts[4]
                    events.append(Event(
                        ts_ns=int(parts[2]),
                        tid=tid_key,
                        type='traceid',
                        func=parts[1],
                        duration_us=0,
                        trace_id=parts[4],
                    ))

            elif stripped.startswith('@UPROBE@ '):
                parts = stripped.split()
                cur_type = 'uprobe'
                cur_func = parts[1]
                cur_ts_ns = int(parts[2])
                cur_tid = int(parts[3])
                cur_dur = int(parts[4]) if len(parts) > 4 else 0
                cur_stack = []
                cur_trace_id = active_trace_id.get(cur_tid, '')
                extra = {}

            elif stripped.startswith('@SYSCALL@ '):
                parts = stripped.split()
                cur_type = 'syscall'
                cur_func = parts[1]
                cur_ts_ns = int(parts[2])
                cur_tid = int(parts[3])
                cur_dur = 0
                cur_stack = []
                extra = {}
                for p in reversed(parts[4:]):
                    if p.startswith('dur='):
                        cur_dur = int(p[4:])
                        break
                for p in parts[4:]:
                    if '=' in p:
                        k, v = p.split('=', 1)
                        try:
                            extra[k] = int(v)
                        except ValueError:
                            extra[k] = v

            elif stripped == '@END@':
                if cur_type == 'uprobe':
                    clean_frames = [f.strip() for f in cur_stack
                                   if f.strip() and not f.strip().startswith('0x')]
                    events.append(Event(
                        ts_ns=cur_ts_ns, tid=cur_tid, type='uprobe',
                        func=cur_func, duration_us=cur_dur,
                        stack=clean_frames, extra=extra,
                        trace_id=cur_trace_id,
                    ))
                elif cur_type == 'syscall':
                    events.append(Event(
                        ts_ns=cur_ts_ns, tid=cur_tid, type='syscall',
                        func=cur_func, duration_us=cur_dur,
                        stack=[], extra=extra,
                        trace_id=cur_trace_id,
                    ))
                cur_type = None

            elif cur_type == 'uprobe' and stripped:
                cur_stack.append(stripped)

    events.sort(key=lambda e: e.ts_ns)
    return events


def build_call_tree(events, gap_ms=50):
    """按 TID 分组，时间间隔 > gap_ms 则新开一个请求。"""
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
            if last_ts is not None and (ev.ts_ns - last_ts) > gap_ms * 1_000_000:
                if current:
                    requests.append(current)
                current = []
            current.append(ev)
            last_ts = ev.ts_ns
        if current:
            requests.append(current)

        for req in requests:
            trees.append({
                'tid': tid,
                'comm': req[0].comm,
                'events': req,
                'total_us': req[-1].ts_ns - req[0].ts_ns,
            })
    return trees


def parse_stack(stack_val):
    if isinstance(stack_val, list):
        return [f.strip() for f in stack_val if f.strip()]
    if isinstance(stack_val, str):
        if '|' in stack_val:
            return [f.strip() for f in stack_val.split('|') if f.strip()]
        return [f.strip() for f in stack_val.split('\n') if f.strip()]
    return []


def print_summary(events, out=sys.stdout):
    uprobe_evs = [e for e in events if e.type == 'uprobe']
    syscall_evs = [e for e in events if e.type == 'syscall']

    print('=' * 80, file=out)
    print('追踪统计摘要', file=out)
    print('=' * 80, file=out)
    print(f'\n总事件数: {len(events)}', file=out)
    print(f'  uprobe 事件: {len(uprobe_evs)}', file=out)
    print(f'  syscall 事件: {len(syscall_evs)}', file=out)

    if uprobe_evs:
        print('\n[Llama.cpp 函数调用统计]', file=out)
        by_func = defaultdict(lambda: {'count': 0, 'total_us': 0, 'max_us': 0, 'min_us': 10**9})
        for ev in uprobe_evs:
            by_func[ev.func]['count'] += 1
            by_func[ev.func]['total_us'] += ev.duration_us
            by_func[ev.func]['max_us'] = max(by_func[ev.func]['max_us'], ev.duration_us)
            by_func[ev.func]['min_us'] = min(by_func[ev.func]['min_us'], ev.duration_us)

        print(f"  {'函数':<55} {'次数':>6}  {'总耗时(μs)':>12}  {'平均(μs)':>10}  {'最大(μs)':>10}", file=out)
        print('  ' + '-' * 100, file=out)
        for func, stat in sorted(by_func.items(), key=lambda x: -x[1]['total_us']):
            avg = stat['total_us'] // max(stat['count'], 1)
            print(f"  {func:<55} {stat['count']:>6}  {stat['total_us']:>12}  {avg:>10}  {stat['max_us']:>10}", file=out)

    if syscall_evs:
        print('\n[系统调用统计]', file=out)
        by_func = defaultdict(lambda: {'count': 0, 'total_us': 0, 'max_us': 0})
        for ev in syscall_evs:
            by_func[ev.func]['count'] += 1
            by_func[ev.func]['total_us'] += ev.duration_us
            by_func[ev.func]['max_us'] = max(by_func[ev.func]['max_us'], ev.duration_us)

        print(f"  {'syscall':<25} {'次数':>6}  {'总耗时(μs)':>12}  {'平均(μs)':>10}  {'最大(μs)':>10}", file=out)
        print('  ' + '-' * 65, file=out)
        for func, stat in sorted(by_func.items(), key=lambda x: -x[1]['total_us']):
            avg = stat['total_us'] // max(stat['count'], 1)
            print(f"  {func:<25} {stat['count']:>6}  {stat['total_us']:>12}  {avg:>10}  {stat['max_us']:>10}", file=out)

    if events:
        start = events[0].ts_ns
        end = events[-1].ts_ns
        print(f'\n追踪时间范围: {(end-start)/1e9:.2f}s', file=out)
        print(f'采样速率: {len(events)/((end-start)/1e9):.1f} events/s', file=out)


def write_flame_fold(events, output_path):
    """生成折叠栈格式（供 FlameGraph 使用）。"""
    stacks = defaultdict(int)
    for ev in events:
        if ev.type != 'uprobe':
            continue
        frames = parse_stack(ev.stack)
        cleaned = []
        for f in frames:
            if f.startswith('0x'):
                continue
            f_clean = f.rsplit('+', 1)[0].strip()
            if f_clean:
                cleaned.append(f_clean)
        if cleaned:
            cleaned.reverse()
            folded = ';'.join([ev.func] + cleaned)
            stacks[folded] += ev.duration_us
        else:
            stacks[ev.func] += ev.duration_us

    with open(output_path, 'w', encoding='utf-8') as f:
        for stack, dur in sorted(stacks.items(), key=lambda x: -x[1]):
            f.write(f'{stack} 1\n')

    print(f'折叠栈写入: {output_path} ({len(stacks)} 个唯一栈)', file=sys.stderr)


def write_events_json(events, output_path):
    """将解析后的事件写入 JSON（供后续 pipeline 使用）。"""
    out = []
    for ev in events:
        out.append({
            'ts_ns': ev.ts_ns,
            'tid': ev.tid,
            'type': ev.type,
            'func': ev.func,
            'duration_us': ev.duration_us,
            'stack': ev.stack,
            'extra': ev.extra,
            'trace_id': ev.trace_id,  # HybriChain: cross-process trace ID
        })
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f'事件 JSON 写入: {output_path}', file=sys.stderr)


def print_call_tree(trees, top_n=20, out=sys.stdout):
    print('=' * 80, file=out)
    print('Ollama 统一调用树', file=out)
    print('=' * 80, file=out)
    trees.sort(key=lambda t: t['total_us'], reverse=True)

    for i, req in enumerate(trees[:top_n]):
        print(f'\n--- 请求 {i+1} | TID={req["tid"]} | 总耗时={req["total_us"]/1000:.1f}ms ---', file=out)
        uprobe_evs = [e for e in req['events'] if e.type == 'uprobe']
        syscall_evs = [e for e in req['events'] if e.type == 'syscall']

        if uprobe_evs:
            print('  [Llama.cpp 层]', file=out)
            for ev in uprobe_evs:
                print(f'    {ev.func:<55} {ev.duration_us:>8}μs', file=out)
                if ev.stack:
                    preview = ' <- '.join(str(f) for f in ev.stack[-3:])
                    print(f'      {preview}', file=out)

        if syscall_evs:
            print('  [系统调用层]', file=out)
            syscall_agg = defaultdict(lambda: {'count': 0, 'total_us': 0})
            for ev in syscall_evs:
                key = ev.func
                syscall_agg[key]['count'] += 1
                syscall_agg[key]['total_us'] += ev.duration_us
            for func, stat in sorted(syscall_agg.items(), key=lambda x: -x[1]['total_us']):
                print(f'    {func:<25} ×{stat["count"]:<3}  {stat["total_us"]:>8}μs', file=out)


def main():
    parser = argparse.ArgumentParser(description='bpftrace 追踪后处理工具')
    parser.add_argument('input', help='bpftrace 文本输出文件路径')
    parser.add_argument('-o', '--output-dir', help='输出目录（可选）')
    parser.add_argument('--tree', action='store_true', help='打印调用树')
    parser.add_argument('--summary', action='store_true', help='打印统计摘要')
    parser.add_argument('--flame', action='store_true', help='生成折叠栈')
    parser.add_argument('--all', action='store_true', help='全部输出（默认）')
    args = parser.parse_args()

    do_all = args.all or not any([args.tree, args.summary, args.flame])

    print(f'读取: {args.input}', file=sys.stderr)
    events = parse_jsonl(args.input)
    print(f'解析: {len(events)} 事件', file=sys.stderr)

    if not events:
        print('[ERROR] 没有解析到任何事件', file=sys.stderr)
        return

    out_dir = args.output_dir
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    if args.summary or do_all:
        print_summary(events)

    if args.flame or do_all:
        fold_path = os.path.join(out_dir, 'llama_folded.txt') if out_dir else 'llama_folded.txt'
        write_flame_fold(events, fold_path)
        events_path = os.path.join(out_dir, 'trace_events.json') if out_dir else 'trace_events.json'
        write_events_json(events, events_path)

    if args.tree or do_all:
        trees = build_call_tree(events)
        print_call_tree(trees)


if __name__ == '__main__':
    main()
