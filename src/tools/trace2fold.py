#!/usr/bin/env python3
"""
trace2fold.py - 将 bpftrace ustack() 输出转换为火焰图折叠栈格式

支持两种 bpftrace 输出格式：
  1. 行缓冲模式 (-B line): 每帧一行，多行堆叠
  2. 单行模式 (默认): 整条栈在一行内

行缓冲格式示例:
    llama_decode;
            _cgo_xxx_Cfunc_llama_decode+66
            runtime.cgocall+127
            github.com/ollama/ollama/llama._Cfunc_llama_decode.abi0+73
            ...
    25074

使用方法:
  python3 trace2fold.py flamegraph_input.txt > llama_folded.txt

然后用 Brendan Gregg 的 FlameGraph 生成 SVG:
  ./FlameGraph/flamegraph.pl llama_folded.txt > llama_flame.svg
"""

import sys
import re
import argparse


def parse_multiline_entry(lines, start_idx):
    """
    解析行缓冲模式（-B line）的多行条目。
    返回: (stack_lines, count, next_idx)
    """
    if start_idx >= len(lines):
        return None, None, start_idx

    header = lines[start_idx].strip()
    if not header or header.startswith('#'):
        return None, None, start_idx + 1

    stack_frames = []

    # 收集缩进的栈帧行（以空格或tab开头）
    i = start_idx + 1
    while i < len(lines):
        line = lines[i]
        if line.startswith(' ') or line.startswith('\t'):
            stack_frames.append(line.strip())
            i += 1
        else:
            # 非缩进行：可能是下一个条目头，或数字（count）
            break

    # 找 count：下一个非空、非缩进的行
    count = 1
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        # 尝试解析为数字
        try:
            count = int(float(line))
        except ValueError:
            # 不是数字，说明是下一个条目头
            break
        i += 1
        break

    return stack_frames, count, i


def parse_single_line_entry(line):
    """解析单行模式的条目。"""
    line = line.strip()
    if not line or line.startswith('#') or line.startswith('---'):
        return None

    parts = line.rsplit(None, 1)
    if len(parts) != 2:
        return None

    stack_str = parts[0].strip()
    try:
        count = int(float(parts[1]))
    except ValueError:
        count = 1

    if not stack_str:
        return None

    funcs = []
    for part in stack_str.split(';'):
        part = part.strip()
        if not part:
            continue
        # 格式可能是 "0x12345678 function_name" 或 "function_name"
        tokens = part.split()
        if len(tokens) >= 2:
            func = tokens[-1]
        else:
            func = part
        func = func.strip()
        if func and not func.startswith('0x'):
            funcs.append(func)

    if not funcs:
        return None

    folded = ";".join(funcs)
    return (folded, count)


def process_multiline(lines):
    """处理行缓冲模式（-B line）：多行条目。"""
    results = {}
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line or line.startswith('#') or line.startswith('Tracing') or line.startswith('Stop'):
            i += 1
            continue

        # 判断是否是条目头（不以空格开头，以分号结尾）
        if not line.startswith(' ') and not line.startswith('\t') and line.endswith(';'):
            stack_frames, count, next_i = parse_multiline_entry(lines, i)
            if stack_frames is not None:
                funcs = []
                for frame in reversed(stack_frames):
                    # 去掉地址偏移，只保留函数名
                    frame = frame.strip()
                    if not frame:
                        continue
                    tokens = frame.split()
                    if len(tokens) >= 2:
                        func = tokens[-1]
                    else:
                        func = frame
                    func = re.sub(r'\+[0-9]+$', '', func)  # 去掉 +偏移
                    if func and not func.startswith('0x'):
                        funcs.append(func)

                if funcs:
                    header_func = line.rstrip(';')
                    full_stack = ";".join([header_func] + funcs)
                    results[full_stack] = results.get(full_stack, 0) + count

                i = next_i
                continue

        i += 1

    return results


def process_single_line(lines):
    """处理单行模式：整条栈在一行内。"""
    results = {}
    for line in lines:
        parsed = parse_single_line_entry(line)
        if parsed:
            folded, count = parsed
            results[folded] = results.get(folded, 0) + count
    return results


def detect_mode(lines):
    """检测是单行模式还是多行模式。"""
    multiline_count = 0
    single_line_count = 0

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue
        # 行缓冲模式：条目头不以空格开头，以分号结尾
        if not stripped.startswith(' ') and not stripped.startswith('\t') and stripped.endswith(';'):
            multiline_count += 1
        # 单行模式：整个条目在一行内，有分号分隔
        elif ';' in stripped:
            single_line_count += 1

    return "multiline" if multiline_count > single_line_count else "single"


def convert(input_file, output_file=None):
    """转换 bpftrace 输出为折叠栈格式。"""
    with open(input_file, 'r') as f:
        lines = f.readlines()

    mode = detect_mode(lines)
    print(f"检测到格式: {'多行模式 (-B line)' if mode == 'multiline' else '单行模式'}", file=sys.stderr)

    if mode == "multiline":
        results = process_multiline(lines)
    else:
        results = process_single_line(lines)

    out = open(output_file, 'w') if output_file else sys.stdout
    try:
        for stack, count in sorted(results.items()):
            out.write(f"{stack} {count}\n")
    finally:
        if output_file:
            out.close()

    total = sum(results.values())
    unique = len(results)
    print(f"转换完成: {unique} 个唯一栈, {total} 次总调用", file=sys.stderr)
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="将 bpftrace ustack() 输出转换为火焰图折叠栈格式"
    )
    parser.add_argument("input_file", help="bpftrace 输出文件")
    parser.add_argument("output_file", nargs="?", help="输出文件（可选，默认 stdout）")
    args = parser.parse_args()

    convert(args.input_file, args.output_file)
