#!/bin/bash
#===============================================================================
# run_trace.sh
# eBPF 追踪启动脚本
#
# 使用方法:
#   chmod +x run_trace.sh
#   sudo ./run_trace.sh            # Runner 时间线追踪模式
#   sudo ./run_trace.sh --flamegraph   # 火焰图调用栈模式
#   sudo ./run_trace.sh --unified      # 统一追踪（uprobe + syscall, JSONL）
#
# Runner 模式工作流程:
#   1. 启动 ollama-debug (daemon, 后台)
#   2. 预热 runner（发一个请求让它保持活跃）
#   3. 获取活的 runner PID
#   4. 用 bpftrace 追踪 runner（不是 daemon）
#   5. 在追踪状态下发真实推理请求（终端2执行 curl）
#   6. 等待 Ctrl+C 停止
#   7. 停止 ollama-debug
#
# 火焰图模式工作流程:
#   1. 确保 ollama-debug daemon 在运行（用户自己启动，或本脚本启动）
#   2. bpftrace 全局 uprobes 追踪 llama.cpp 调用栈
#   3. 用户发推理请求
#   4. Ctrl+C 停止
#   5. 用 FlameGraph 工具生成 SVG 火焰图
#
# 统一追踪模式工作流程:
#   1. 启动 ollama-debug daemon
#   2. bpftrace 同时追踪 uprobe（llama.cpp函数）+ syscall（系统调用）
#   3. 输出 JSONL 格式，Python 后处理生成调用树 + 折叠栈
#   4. Ctrl+C 停止
#   5. python3 trace_unify.py trace_unified.jsonl --both
#
# 架构说明:
#   daemon (PID X) ─── fork ───→ runner (PID Y) ───→ llama.cpp
#        ↑ 不追踪                        ↑ 追踪这个
#   HTTP 响应不受 bpftrace overhead 影响
#
# 输出:
#   trace_output.log      - Runner 模式追踪日志
#   flamegraph_input.txt  - 火焰图模式原始数据
#   trace_unified.jsonl   - 统一追踪 JSONL 数据
#
# 生成火焰图:
#   python3 trace2fold.py flamegraph_input.txt llama_folded.txt
#   ~/FlameGraph/flamegraph.pl llama_folded.txt > llama_flame.svg
#
# 后处理统一追踪:
#   python3 trace_unify.py trace_unified.jsonl --both
#===============================================================================

set -euo pipefail

# 自动推导项目根目录（脚本位于 hybri-chain/scripts/）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HYBRI_CHAIN_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

OLLAMA_DEBUG="${HYBRI_CHAIN_ROOT}/../ollama-debug"
TRACE_SCRIPT="${HYBRI_CHAIN_ROOT}/scripts/bpftrace/trace_ollama_runner.bt"
TRACE_SCRIPT_FLAME="${HYBRI_CHAIN_ROOT}/scripts/bpftrace/trace_flamegraph.bt"
TRACE_OUTPUT="${HYBRI_CHAIN_ROOT}/trace_output.log"
FLAME_OUTPUT="${HYBRI_CHAIN_ROOT}/flamegraph_input.txt"
OLLAMA_DEBUG_LOG="${HYBRI_CHAIN_ROOT}/ollama-debug.log"

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info()  { echo -e "${BLUE}[INFO]${NC} $1"; }
log_ok()    { echo -e "${GREEN}[OK]${NC}   $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1" >&2; }

# ========== 参数解析 ==========
MODE="${1:-runner}"

if [[ "$MODE" == "--flamegraph" ]] || [[ "$MODE" == "-f" ]]; then
    TRACE_SCRIPT="$TRACE_SCRIPT_FLAME"
    TRACE_OUTPUT="$FLAME_OUTPUT"
    MODE_DESC="火焰图模式（调用栈）"
elif [[ "$MODE" == "--unified" ]] || [[ "$MODE" == "-u" ]]; then
    TRACE_SCRIPT="${HYBRI_CHAIN_ROOT}/scripts/bpftrace/trace_unified.bt"
    TRACE_OUTPUT="${HYBRI_CHAIN_ROOT}/trace_unified.jsonl"
    MODE_DESC="统一追踪模式（uprobe + syscall，JSONL）"
elif [[ "$MODE" != "runner" ]]; then
    log_error "未知模式: $MODE"
    log_info "用法: $0 [runner|--flamegraph|-f]"
    exit 1
else
    MODE_DESC="Runner 追踪模式（时间线）"
fi

# ========== 前置检查 ==========
echo ""
echo "=============================================="
echo "  Ollama eBPF 追踪脚本"
echo "  模式: $MODE_DESC"
echo "=============================================="
echo ""

if [[ $EUID -ne 0 ]]; then
    log_error "此脚本需要 root 权限运行"
    log_info "请使用: sudo $0"
    exit 1
fi

if ! command -v bpftrace &> /dev/null; then
    log_error "bpftrace 未安装"
    exit 1
fi
log_info "bpftrace 版本: $(bpftrace --version 2>&1 | head -1)"

if [[ ! -f "$OLLAMA_DEBUG" ]]; then
    log_error "ollama-debug 不存在: $OLLAMA_DEBUG"
    log_info "请先运行: ./build_debug_ollama.sh"
    exit 1
fi
log_ok "ollama-debug 存在: $OLLAMA_DEBUG"

if [[ ! -f "$TRACE_SCRIPT" ]]; then
    log_error "追踪脚本不存在: $TRACE_SCRIPT"
    exit 1
fi
log_ok "追踪脚本存在: $TRACE_SCRIPT"

BPF_DISABLED=$(cat /proc/sys/kernel/unprivileged_bpf_disabled 2>/dev/null || echo "2")
if [[ "$BPF_DISABLED" == "2" ]]; then
    log_error "eBPF 已永久禁用 (unprivileged_bpf_disabled=2)"
    exit 1
fi
log_ok "eBPF 权限检查通过"

# ========== 启动 ollama-debug (daemon) ==========
# 火焰图模式也需要 daemon 在运行才能追踪
log_info "清理旧 ollama 进程..."
pkill -9 -f "ollama-debug" 2>/dev/null || true
pkill -9 -f "ollama serve" 2>/dev/null || true
sleep 1

log_info "启动 ollama-debug daemon (后台)..."
cd "$HYBRI_CHAIN_ROOT"

OLLAMA_MODELS=/home/typejetfire/.ollama/models \
OLLAMA_HOST=127.0.0.1:11434 \
    "$OLLAMA_DEBUG" serve > "$OLLAMA_DEBUG_LOG" 2>&1 &
DAEMON_PID=$!
echo "daemon PID: $DAEMON_PID"

sleep 3

if ! kill -0 "$DAEMON_PID" 2>/dev/null; then
    log_error "daemon 启动失败"
    log_info "查看日志: cat $OLLAMA_DEBUG_LOG"
    exit 1
fi
log_ok "daemon 启动成功 (PID: $DAEMON_PID)"

# ========== 预热 runner ==========
log_info "预热 runner（发一个请求让模型加载）..."
WARMUP_RESP=$(curl -s -m 10 http://127.0.0.1:11434/api/generate \
    -d '{"model":"qwen:0.5b","prompt":"hi","stream":false}' 2>&1 || true)
if [[ "$WARMUP_RESP" == *"error"* ]] || [[ -z "$WARMUP_RESP" ]]; then
    log_warn "预热请求失败，请确认模型存在: $WARMUP_RESP"
else
    log_ok "预热完成，runner 应该已加载模型"
fi

sleep 2

# ========== 获取活的 runner PID ==========
RUNNER_PID=""
WAIT_COUNT=0
MAX_WAIT=30

while [[ -z "$RUNNER_PID" ]] && (( WAIT_COUNT < MAX_WAIT )); do
    CANDIDATE=$(pgrep -f "ollama.*runner" 2>/dev/null | head -1 || true)

    if [[ -n "$CANDIDATE" && "$CANDIDATE" != "$DAEMON_PID" ]]; then
        RUNNER_PID="$CANDIDATE"
        break
    fi

    ((WAIT_COUNT++))
    sleep 1
done

if [[ -z "$RUNNER_PID" ]]; then
    log_error "等待超时（${MAX_WAIT}s），未找到 runner 子进程"
    log_info "查看 daemon 日志: cat $OLLAMA_DEBUG_LOG"
    kill -9 "$DAEMON_PID" 2>/dev/null || true
    exit 1
fi

log_ok "runner 子进程已就绪 (PID: $RUNNER_PID)"

PARENT_PID=$(grep PPid /proc/"$RUNNER_PID"/status 2>/dev/null | awk '{print $2}' || true)
if [[ "$PARENT_PID" == "$DAEMON_PID" ]]; then
    log_ok "确认 runner 是 daemon 的子进程"
else
    log_warn "runner (PID $RUNNER_PID) 的父进程是 $PARENT_PID"
fi

# ========== 清理旧日志 ==========
> "$TRACE_OUTPUT"

# ========== 运行 bpftrace ==========
echo ""
echo "=============================================="
if [[ "$MODE" == "--flamegraph" ]] || [[ "$MODE" == "-f" ]]; then
    log_info "模式: 火焰图（调用栈追踪）"
    log_info "runner PID: $RUNNER_PID"
    log_info "输出文件: $TRACE_OUTPUT"
    echo ""
    echo "  【火焰图模式使用说明】"
    echo "  1. bpftrace 正在追踪 llama.cpp 调用栈..."
    echo "  2. 切换到终端2，发推理请求:"
    echo "       curl http://127.0.0.1:11434/api/generate \\"
    echo "         -d '{\"model\": \"qwen:0.5b\", \"prompt\": \"hi\", \"stream\": false}'"
    echo "  3. 建议收集 30s 以上数据"
    echo "  4. Ctrl+C 停止后生成火焰图:"
    echo ""
    echo "  # 生成火焰图:"
    echo "  python3 trace2fold.py flamegraph_input.txt llama_folded.txt"
    echo "  ~/FlameGraph/flamegraph.pl llama_folded.txt > llama_flame.svg"
    echo ""
    echo "  # 或直接在浏览器打开 llama_flame.svg 查看"
elif [[ "$MODE" == "--unified" ]] || [[ "$MODE" == "-u" ]]; then
    log_info "模式: 统一追踪（uprobe + syscall）"
    log_info "输出文件: $TRACE_OUTPUT"
    echo ""
    echo "  【统一追踪模式使用说明】"
    echo "  1. bpftrace 同时追踪 llama.cpp 函数 + 系统调用..."
    echo "  2. 发几次推理请求（建议 3-5 次，隔几秒一次）:"
    echo "       curl http://127.0.0.1:11434/api/generate \\"
    echo "         -d '{\"model\": \"qwen:0.5b\", \"prompt\": \"hi\", \"stream\": false}'"
    echo "  3. Ctrl+C 停止"
    echo "  4. 后处理:"
    echo "       python3 trace_unify.py trace_unified.jsonl --both"
    echo "       # 生成折叠栈:"
    echo "       ~/FlameGraph/flamegraph.pl llama_folded_unified.txt \\"
    echo "         --title='Ollama Unified' > llama_flame_unified.svg"
else
    log_info "模式: Runner 时间线追踪"
    log_info "runner PID: $RUNNER_PID"
    log_info "日志文件: $TRACE_OUTPUT"
    echo ""
    log_info "现在在另一个终端发送推理请求:"
    echo "  curl http://127.0.0.1:11434/api/generate \\"
    echo "    -d '{\"model\": \"qwen:0.5b\", \"prompt\": \"Why is the sky blue?\", \"stream\": false}'"
fi
echo ""
log_info "按 Ctrl+C 停止追踪"
echo "=============================================="
echo ""

# 火焰图模式用全局 uprobes（不需要 -p）
# Runner 模式需要 -p attach 到 runner 进程
if [[ "$MODE" == "--flamegraph" ]] || [[ "$MODE" == "-f" ]]; then
    bpftrace -o "$TRACE_OUTPUT" -B line "$TRACE_SCRIPT"
elif [[ "$MODE" == "--unified" ]] || [[ "$MODE" == "-u" ]]; then
    bpftrace -o "$TRACE_OUTPUT" -B line "$TRACE_SCRIPT"
else
    bpftrace -p "$RUNNER_PID" -o "$TRACE_OUTPUT" -B line "$TRACE_SCRIPT"
fi

# ========== 清理 ==========
log_info "停止 daemon (PID: $DAEMON_PID)..."
kill -9 "$DAEMON_PID" 2>/dev/null || true

log_ok "追踪完成!"
log_info "日志已保存到: $TRACE_OUTPUT"
if [[ -f "$TRACE_OUTPUT" ]]; then
    log_info "日志行数: $(wc -l < "$TRACE_OUTPUT")"
fi
