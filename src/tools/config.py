#!/usr/bin/env python3
"""
config.py — 所有实验共享的配置参数。

4 个实验的设计：
  exp1: tinyllama + 动态追踪（strace + bpftrace）
  exp2: tinyllama + 静态分析（仅 extract_symbols，无动态追踪）
  exp3: qwen:0.5b  + 动态追踪
  exp4: qwen:0.5b  + 静态分析

数据目录结构：
  experiments/
    exp1_tinyllama_dynamic/
      raw/
        strace.txt          ← sudo strace 输出
        bpftrace.jsonl      ← sudo bpftrace 输出
      parsed/
        trace_events.json    ← trace_unify.py 输出
        flame_folded.txt    ← 折叠栈
      stitched/
        syscall_sequence.json
        syscall_sequence.txt
      sequenced/
        nodes_sequential.json
        call_sequence.json
    exp2_tinyllama_static/
      (只有静态调用图)
      call_graph_static.json
      nodes_sequential.json
      call_sequence.json
    exp3_qwen_dynamic/
      ...
    exp4_qwen_static/
      ...
"""

import os
from pathlib import Path

# ========== 全局路径 ==========
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
TOOLCHAIN_DIR = PROJECT_ROOT / 'src' / 'tools'
EXPERIMENTS_DIR = PROJECT_ROOT / 'experiments'
OLLAMA_BINARY = Path('/home/typejetfire/graduation_thesis/ollama-debug')
CG_STATIC_JSON = PROJECT_ROOT / 'src' / 'stitcher' / 'call_graph_static.json'

# ========== 实验定义 ==========
# 每个实验: (名称, 模型名, 是否动态追踪)
EXPERIMENTS = [
    {
        'id': 'exp1',
        'name': 'exp1_tinyllama_dynamic',
        'model': 'tinyllama:latest',
        'dynamic': True,
        'prompt': 'hello',
    },
    {
        'id': 'exp2',
        'name': 'exp2_tinyllama_static',
        'model': 'tinyllama:latest',
        'dynamic': False,
        'prompt': None,
    },
    {
        'id': 'exp3',
        'name': 'exp3_qwen_dynamic',
        'model': 'qwen:0.5b',
        'dynamic': True,
        'prompt': 'hello',
    },
    {
        'id': 'exp4',
        'name': 'exp4_qwen_static',
        'model': 'qwen:0.5b',
        'dynamic': False,
        'prompt': None,
    },
]


def exp_dir(exp_id: str) -> Path:
    """返回实验的根目录。"""
    for e in EXPERIMENTS:
        if e['id'] == exp_id:
            return EXPERIMENTS_DIR / e['name']
    raise ValueError(f'Unknown experiment: {exp_id}')


def ensure_dirs(exp_id: str) -> dict:
    """创建实验目录结构，返回各子目录路径。"""
    base = exp_dir(exp_id)
    dirs = {
        'base': base,
        'raw': base / 'raw',
        'parsed': base / 'parsed',
        'stitched': base / 'stitched',
        'sequenced': base / 'sequenced',
        'static': base / 'static',  # 仅静态实验用
    }
    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)
    return dirs


# ========== eBPF 追踪脚本内容（供 run_trace.sh 使用）==========
BPFTRACE_SCRIPT = '''
// trace_unified.bt — Ollama 统一追踪：uprobe + syscall
// 需要 sudo bpftrace -o OUTPUT.jsonl THIS_SCRIPT

BEGIN
{
    printf("Tracing Ollama uprobe + syscall...\\n");
    printf("Stop: Ctrl+C\\n");
}

// ---- llama.cpp 推理函数 uprobe ----
uprobe:/home/typejetfire/graduation_thesis/ollama-debug:llama_decode
{
    @start_llama_decode[tid] = nsecs;
}
uretprobe:/home/typejetfire/graduation_thesis/ollama-debug:llama_decode
{
    $dur = (nsecs - @start_llama_decode[tid]) / 1000;
    printf("@UPROBE@ llama_decode %lu %d %lu\\n", nsecs, tid, $dur);
    print(ustack(32));
    printf("@END@\\n");
    delete(@start_llama_decode[tid]);
}

uprobe:/home/typejetfire/graduation_thesis/ollama-debug:ggml_backend_sched_graph_compute_async
{
    @start_ggml[tid] = nsecs;
}
uretprobe:/home/typejetfire/graduation_thesis/ollama-debug:ggml_backend_sched_graph_compute_async
{
    $dur = (nsecs - @start_ggml[tid]) / 1000;
    printf("@UPROBE@ ggml_backend_sched_graph_compute_async %lu %d %lu\\n", nsecs, tid, $dur);
    print(ustack(32));
    printf("@END@\\n");
    delete(@start_ggml[tid]);
}

uprobe:/home/typejetfire/graduation_thesis/ollama-debug:llama_synchronize
{
    @start_sync[tid] = nsecs;
}
uretprobe:/home/typejetfire/graduation_thesis/ollama-debug:llama_synchronize
{
    $dur = (nsecs - @start_sync[tid]) / 1000;
    printf("@UPROBE@ llama_synchronize %lu %d %lu\\n", nsecs, tid, $dur);
    print(ustack(32));
    printf("@END@\\n");
    delete(@start_sync[tid]);
}

uprobe:/home/typejetfire/graduation_thesis/ollama-debug:common_sampler_csample
{
    @start_csample[tid] = nsecs;
}
uretprobe:/home/typejetfire/graduation_thesis/ollama-debug:common_sampler_csample
{
    $dur = (nsecs - @start_csample[tid]) / 1000;
    printf("@UPROBE@ common_sampler_csample %lu %d %lu\\n", nsecs, tid, $dur);
    print(ustack(32));
    printf("@END@\\n");
    delete(@start_csample[tid]);
}

// ---- 系统调用 tracepoint ----
tracepoint:syscalls:sys_enter_read
{
    $fd = args->fd;
    $count = args->count;
    printf("@SYSCALL@ read %lu %d fd=%d bytes=%lu\\n", nsecs, pid, $fd, $count);
    printf("@END@\\n");
}

tracepoint:syscalls:sys_enter_write
{
    $fd = args->fd;
    $count = args->count;
    printf("@SYSCALL@ write %lu %d fd=%d bytes=%lu\\n", nsecs, pid, $fd, $count);
    printf("@END@\\n");
}

tracepoint:syscalls:sys_enter_futex
{
    $uaddr = args->uaddr;
    $val = args->val;
    printf("@SYSCALL@ futex %lu %d uaddr=%lx val=%u\\n", nsecs, pid, $uaddr, $val);
    printf("@END@\\n");
}

tracepoint:syscalls:sys_exit_futex
{
    $ret = args->ret;
    printf("@FUTEX_RET@ %lu %d ret=%d\\n", nsecs, tid, $ret);
}

tracepoint:syscalls:sys_enter_mmap
{
    $addr = args->addr;
    $len = args->len;
    printf("@SYSCALL@ mmap %lu %d addr=%lx len=%lu\\n", nsecs, pid, $addr, $len);
    printf("@END@\\n");
}

tracepoint:syscalls:sys_enter_clone3
{
    printf("@SYSCALL@ clone3 %lu %d\\n", nsecs, pid);
    printf("@END@\\n");
}

tracepoint:syscalls:sys_enter_openat
{
    $dfd = args->dfd;
    $flags = args->flags;
    printf("@SYSCALL@ openat %lu %d dfd=%d flags=%x\\n", nsecs, pid, $dfd, $flags);
    printf("@END@\\n");
}
'''


# ========== CGO 等价映射表（实验共享）==========
CGO_EQUIV = {
    '_cgo_8aa400f2462b_Cfunc_llama_decode':                  'llama_decode',
    '_cgo_8aa400f2462b_Cfunc_llama_batch_add':              'llama_batch_add',
    '_cgo_8aa400f2462b_Cfunc_llama_batch_init':             'llama_batch_init',
    '_cgo_8aa400f2462b_Cfunc_llama_model_load_from_file': 'llama_model_load_from_file',
    '_cgo_8aa400f2462b_Cfunc_llama_synchronize':          'llama_synchronize',
    '_cgo_8aa400f2462b_Cfunc_llama_sampler_sample':       'llama_sampler_sample',
    '_cgo_8aa400f2462b_Cfunc_common_sampler_csample':     'common_sampler_csample',
    '_cgo_8aa400f2462b_Cfunc_llama_batch_get_one':        'llama_batch_get_one',
    '_cgo_8aa400f2462b_Cfunc_llama_token_to_str':        'llama_token_to_str',
    # 更多哈希映射可在此添加
}


def cgo_normalize(func_name: str) -> str:
    """将 CGO 哈希函数名归一化为 llama.cpp 函数名。"""
    return CGO_EQUIV.get(func_name, func_name)


# ========== 8 层分类（实验共享）==========
LAYER_ORDER = [
    'go_cgo_bridge', 'llama_api', 'batch_sampler',
    'sched_compute', 'ggml_backend', 'ggml_ops', 'vocab', 'memory',
]

LAYER_PREFIX = {LAYER_ORDER[i]: f'L{i+1}' for i in range(len(LAYER_ORDER))}

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


if __name__ == '__main__':
    print('实验配置：')
    for e in EXPERIMENTS:
        mode = '动态追踪' if e['dynamic'] else '静态分析'
        print(f"  [{e['id']}] {e['name']}: {e['model']} + {mode}")
    print(f'\n实验输出目录: {EXPERIMENTS_DIR}')
