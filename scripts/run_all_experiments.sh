#!/usr/bin/env bash
# =============================================================================
# run_all_experiments.sh — 运行全部 4 个实验的完整脚本
# =============================================================================
# 本脚本由两部分组成：
#   PART 1（需要 sudo）：数据采集（run_trace.sh）
#   PART 2（普通权限）：数据分析（run_pipeline.py）
#
# 用法：
#   bash run_all_experiments.sh           # 交互模式
#   bash run_all_experiments.sh --sudo    # 仅执行 sudo 部分
#   bash run_all_experiments.sh --pipeline # 仅执行普通权限部分
#   bash run_all_experiments.sh --all      # 完整执行
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TOOLCHAIN="$PROJECT_ROOT/toolchain"

echo "============================================================"
echo "Ollama 推理框架 API 调用链分析 — 4 实验批量运行"
echo "============================================================"
echo "项目目录: $PROJECT_ROOT"
echo ""

# =============================================================================
# PART 1: 数据采集（需要 sudo）
# =============================================================================
run_sudo_part() {
    echo "============================================================"
    echo "[PART 1] 数据采集（需要 sudo）"
    echo "============================================================"
    echo ""
    echo "需要 sudo 权限的命令列表："
    echo "  1. sudo bash run_trace.sh exp1 tinyllama:latest hello"
    echo "  2. sudo bash run_trace.sh exp3 qwen:0.5b hello"
    echo ""
    read -p "是否现在执行 PART 1？[y/N] " ans
    if [[ "$ans" != "y" && "$ans" != "Y" ]]; then
        echo "跳过 PART 1，请稍后手动执行上面的命令。"
    else
        echo ""
        echo ">>> [1/2] exp1: tinyllama + 动态追踪"
        echo ">>> 请输入 sudo 密码..."
        sudo bash "$TOOLCHAIN/run_trace.sh" exp1 tinyllama:latest hello 30
        echo ""

        echo ">>> [2/2] exp3: qwen:0.5b + 动态追踪"
        echo ">>> 请输入 sudo 密码..."
        sudo bash "$TOOLCHAIN/run_trace.sh" exp3 qwen:0.5b hello 30
    fi
}

# =============================================================================
# PART 2: 数据分析（普通权限）
# =============================================================================
run_pipeline_part() {
    echo ""
    echo "============================================================"
    echo "[PART 2] 数据分析（普通权限）"
    echo "============================================================"

    cd "$TOOLCHAIN"

    echo ""
    echo ">>> 步骤 1: 运行静态符号提取（4 个实验）"
    echo "    exp1_tinyllama_dynamic..."
    sudo -n true 2>/dev/null && \
        sudo -u "$SUDO_USER" python3 extract_symbols.py \
            --binary "$PROJECT_ROOT/ollama-debug" \
            -o "$PROJECT_ROOT/experiments/exp1_tinyllama_dynamic/static/" -q || \
        python3 extract_symbols.py \
            --binary "$PROJECT_ROOT/ollama-debug" \
            -o "$PROJECT_ROOT/experiments/exp1_tinyllama_dynamic/static/" -q
    echo "    exp2_tinyllama_static..."
    python3 extract_symbols.py \
        --binary "$PROJECT_ROOT/ollama-debug" \
        -o "$PROJECT_ROOT/experiments/exp2_tinyllama_static/static/" -q
    echo "    exp3_qwen_dynamic..."
    python3 extract_symbols.py \
        --binary "$PROJECT_ROOT/ollama-debug" \
        -o "$PROJECT_ROOT/experiments/exp3_qwen_dynamic/static/" -q
    echo "    exp4_qwen_static..."
    python3 extract_symbols.py \
        --binary "$PROJECT_ROOT/ollama-debug" \
        -o "$PROJECT_ROOT/experiments/exp4_qwen_static/static/" -q

    echo ""
    echo ">>> 步骤 2: 层序号标注 + bpftrace 解析 + 系统调用缝合"
    for exp_id in exp1 exp2 exp3 exp4; do
        echo ""
        echo "    === 实验 $exp_id ==="
        echo "    [2/3] build_sequential..."
        python3 build_sequential.py --exp-id "$exp_id" -q
        echo "    [3/4] trace_unify..."  # 如果有 bpftrace 数据
        python3 trace_unify.py --exp-id "$exp_id" --summary --flame 2>/dev/null || true
        echo "    [4/4] merge_syscall_sequence..."
        python3 merge_syscall_sequence.py --exp-id "$exp_id" -q
    done

    echo ""
    echo ">>> 步骤 3: 生成汇总报告"
    python3 run_pipeline.py --summary
}

# =============================================================================
# 主入口
# =============================================================================
MODE="${1:-}"

case "$MODE" in
    --sudo)
        run_sudo_part
        ;;
    --pipeline)
        run_pipeline_part
        ;;
    --all)
        run_sudo_part
        run_pipeline_part
        ;;
    --dry-run)
        echo "[DRY RUN] 计划执行："
        echo "  PART 1 (sudo):"
        echo "    sudo bash run_trace.sh exp1 tinyllama:latest hello"
        echo "    sudo bash run_trace.sh exp3 qwen:0.5b hello"
        echo "  PART 2 (普通):"
        echo "    python3 run_pipeline.py --all"
        ;;
    "")
        echo "用法："
        echo "  bash run_all_experiments.sh           # 交互模式（先 sudo 再 pipeline）"
        echo "  bash run_all_experiments.sh --sudo    # 仅执行 PART 1（sudo 数据采集）"
        echo "  bash run_all_experiments.sh --pipeline # 仅执行 PART 2（数据分析）"
        echo "  bash run_all_experiments.sh --all     # 完整执行"
        echo "  bash run_all_experiments.sh --dry-run # 预览"
        echo ""
        echo "目录结构："
        echo "  experiments/"
        echo "    exp1_tinyllama_dynamic/  (tinyllama + strace + bpftrace)"
        echo "    exp2_tinyllama_static/   (tinyllama + 仅静态分析)"
        echo "    exp3_qwen_dynamic/      (qwen:0.5b + strace + bpftrace)"
        echo "    exp4_qwen_static/       (qwen:0.5b + 仅静态分析)"
        echo ""
        echo "每个实验目录结构："
        echo "  <exp>/"
        echo "    raw/                     ← sudo run_trace.sh 输出"
        echo "      strace.txt"
        echo "      bpftrace.jsonl"
        echo "    static/                  ← extract_symbols.py 输出"
        echo "      call_graph_static.json"
        echo "    parsed/                  ← trace_unify.py 输出（动态实验）"
        echo "      trace_events.json"
        echo "      llama_folded.txt"
        echo "    sequenced/               ← build_sequential.py 输出"
        echo "      nodes_sequential.json"
        echo "      call_sequence.json"
        echo "      nodes.csv"
        echo "      edges.csv"
        echo "    stitched/                ← merge_syscall_sequence.py 输出"
        echo "      syscall_sequence.json"
        echo "      syscall_sequence.txt"
        ;;
    *)
        echo "[ERROR] 未知参数: $MODE"
        exit 1
        ;;
esac
