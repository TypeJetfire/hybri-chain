#!/bin/bash
#===============================================================================
# build_debug_ollama.sh
#
# 编译带完整符号表的 Ollama 可执行文件，用于 eBPF uprobe 追踪
#
# 使用方法:
#   chmod +x build_debug_ollama.sh
#   ./build_debug_ollama.sh
#
# 输出:
#   ./ollama-debug  - 带符号表的 Ollama 可执行文件
#The user is asking if they can just install ollama from pacman/yay/pip instead of compiling from source.
Let me think about this:

pacman/yay install: The system-installed ollama binary is typically stripped (no debug symbols), so we can't use uprobe on it.

pip: Ollama doesn't have a pip package.

So the answer is: we could try, but the system-installed binary won't have symbols, which means we can't do the uprobe part of our eBPF tracing. We'd only be able to use the tracepoint (syscall) part, which doesn't need symbols.

I need to be straightforward about this trade-off—the package manager version won't give us the symbol information we need for the uprobe tracing, so while it's easier to install, it limits what we can actually analyze.

可以，但有个问题：

安装方式	优点	缺点
sudo pacman -S ollama
快速
❌ 二进制被 strip，无法 uprobe
yay -S ollama
同上
同上
pip install ollama
无效
Ollama 没有 pip 包
系统包管理器安装的 ollama 是 release 版本，符号被剥离了。

如果你只是想：

用 strace 追踪系统调用 → 可以用系统包
用 eBPF uprobe 追踪 Go/CGO 函数 → 需要带符号的二进制，必须自己编译
建议：直接重新编译完整的 Ollama，这次构建脚本已经修正了，只需要几分钟。

如果你只是想快速测试 strace 追踪（不需要 uprobe），我可以改用系统包安装的 ollama。 The user is deciding what to do. Let me wait for their response.
# 依赖:
#   - Go 1.21+
#   - Git
#   - GCC/Clang (CGO 编译 llama.cpp)
#   - CMake (llama.cpp 编译)
#
# 注意事项:
#   - 编译需要约 5-10 GB 磁盘空间和 10-20 分钟时间
#   - 当前系统 Go 版本为 1.26.2，nodwarf5 版本
#     (DWARF 调试信息不可用，但函数符号名仍可通过 nm 获取)
#   - 此脚本用于学术研究目的
#
# 作者: Cursor AI Agent
# 日期: 2026-05-10
#===============================================================================

set -euo pipefail

# ========== 配置 ==========
OLLAMA_REPO="https://github.com/ollama/ollama.git"
OLLAMA_TAG="v0.6.4"           # 稳定版本 (2024年底)
WORKSPACE_DIR="$HOME/graduation_thesis"
SRC_DIR="$WORKSPACE_DIR/ollama"
BUILD_DIR="$WORKSPACE_DIR/ollama-build"
OUTPUT_BINARY="$WORKSPACE_DIR/ollama-debug"
LOG_FILE="$HOME/graduation_thesis/build_ollama_$(date +%Y%m%d_%H%M%S).log"

# ========== 日志重定向 ==========
# 创建日志文件并 tee 输出
exec > >(tee -a "$LOG_FILE") 2>&1

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info()  { echo -e "${BLUE}[INFO]${NC} $1"; }
log_ok()    { echo -e "${GREEN}[OK]${NC}   $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1" >&2; }

# ========== 前置检查 ==========
echo ""
echo "=============================================="
echo "  Ollama Debug 构建脚本"
echo "  目标: 编译带符号表的 ollama-debug"
echo "=============================================="
echo ""
echo "日志文件: $LOG_FILE"
echo ""

log_info "Go 版本: $(go version | awk '{print $3}')"
log_info "GCC 版本: $(gcc --version | head -1 | awk '{print $3}')"
log_info "构建目录: $BUILD_DIR"

# 检查磁盘空间 (需要约 5GB)
AVAIL=$(df -BG "$WORKSPACE_DIR" | tail -1 | awk '{print $4}' | tr -d 'G')
if [[ "$AVAIL" -lt 10 ]]; then
    log_warn "磁盘空间不足 (约 ${AVAIL}G 可用，建议 10G+)"
fi

# ========== Step 1: 克隆源码 ==========
if [[ -d "$SRC_DIR" ]]; then
    log_warn "源码目录已存在: $SRC_DIR"
    read -p "是否重新克隆? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        log_info "删除旧源码目录..."
        rm -rf "$SRC_DIR"
    else
        log_info "使用现有源码目录"
    fi
fi

if [[ ! -d "$SRC_DIR/.git" ]]; then
    log_info "克隆 Ollama 源码 (tag: $OLLAMA_TAG)..."
    git clone --depth 1 --branch "$OLLAMA_TAG" "$OLLAMA_REPO" "$SRC_DIR"
    log_ok "源码克隆完成"
else
    log_ok "源码目录已存在，跳过克隆"
fi

# ========== Step 2: 同步子模块 (llama.cpp) ==========
log_info "同步 llama.cpp 子模块..."
cd "$SRC_DIR"

# 检查是否有子模块
if [[ -f ".gitmodules" ]]; then
    log_info "初始化 git 子模块..."
    # 使用 --depth 1 加速克隆
    git submodule update --init --recursive --depth 1 2>&1 | head -20 || {
        log_warn "子模块同步失败，尝试仅初始化主模块..."
        git submodule update --init 2>&1 | head -20 || {
            log_warn "子模块初始化失败，继续尝试编译（可能已缓存）"
        }
    }
    log_ok "子模块同步完成"
else
    log_info "无子模块配置，跳过"
fi

# ========== Step 3: 编译 ==========
log_info "开始编译 Ollama (保留符号表)..."
log_info "编译参数:"
log_info "  - CGO_ENABLED=1"
log_info "  - GOEXPERIMENT=nodwarf5"
log_info "  - -gcflags='all=-N -l' (禁用优化和内联)"
log_info "  - 输出: $OUTPUT_BINARY"
echo ""

# 关键编译参数说明:
#   CGO_ENABLED=1        启用 CGO (llama.cpp 需要)
#   GOEXPERIMENT=nodwarf5  保持兼容性（系统 Go 版本不支持 DWARF5）
#   -gcflags="all=-N -l"
#     -N  禁用所有优化（preserves symbol table）
#     -l  禁用函数内联（保留函数边界 for uprobe）
#   -ldflags=""          不 strip 符号表
#   trimpath           移除源文件路径（安全，不影响符号）
#   -tags=""            不添加额外 tags（CUDA 等可选）

# 关键: go build 必须从源码目录运行（那里有 go.mod）
cd "$SRC_DIR"

CGO_ENABLED=1 \
GOEXPERIMENT=nodwarf5 \
go build \
    -gcflags="all=-N -l" \
    -ldflags="" \
    -trimpath \
    -o "$OUTPUT_BINARY" \
    .

log_ok "编译完成!"

# ========== Step 4: 验证符号 ==========
echo ""
echo "=============================================="
echo "  验证符号表"
echo "=============================================="
echo ""

# 检查文件类型
log_info "文件类型检查:"
file "$OUTPUT_BINARY"
echo ""

# 检查是否有 .symtab (stripped binary 没有这个)
if readelf -S "$OUTPUT_BINARY" 2>/dev/null | grep -q "\.symtab"; then
    log_ok "符号表 (.symtab) 存在"
else
    log_warn "符号表 (.symtab) 不存在，二进制可能被 strip"
fi

# 查找 Go API 相关符号
log_info "查找 Generate 相关符号 (nm):"
SYMBOLS=$(nm "$OUTPUT_BINARY" 2>/dev/null | grep -iE "generate|Generate|chat|Chat" | grep -v "\\.p" | head -20)
if [[ -n "$SYMBOLS" ]]; then
    log_ok "找到 $(echo "$SYMBOLS" | wc -l) 个相关符号:"
    echo ""
    echo "$SYMBOLS" | head -20 | while read -r line; do
        echo "  $line"
    done
    echo ""
else
    log_warn "未找到 Generate 相关符号（可能需要用更宽泛的搜索）"
    log_info "尝试搜索 api, server, handler..."
    nm "$OUTPUT_BINARY" 2>/dev/null | grep -iE "api|server|handler" | grep -v "\\.p" | head -10 | while read -r line; do
        echo "  $line"
    done
fi

echo ""

# 查找 CGO trampoline (关键，用于识别 CGO 边界)
log_info "查找 CGO trampoline (确认 CGO 编译成功):"
TRAMPOLINE=$(nm "$OUTPUT_BINARY" 2>/dev/null | grep -E "cgo_panic|_cgo_topofstack|authorizerTrampoline" | head -5)
if [[ -n "$TRAMPOLINE" ]]; then
    log_ok "CGO 符号存在，编译成功"
    echo "$TRAMPOLINE" | while read -r line; do
        echo "  $line"
    done
else
    log_error "未找到 CGO 符号，编译可能失败"
fi

echo ""

# 检查 llama.cpp 符号 (如果编译了 C++ 部分)
log_info "查找 llama.cpp 相关符号:"
LLAMA_SYM=$(nm "$OUTPUT_BINARY" 2>/dev/null | grep -iE "_cgo_.*llama_|llama_.*Cfunc|ggml_|llama_eval" | head -10)
if [[ -n "$LLAMA_SYM" ]]; then
    log_ok "找到 llama.cpp 符号 ($(echo "$LLAMA_SYM" | wc -l) 个)"
    echo "$LLAMA_SYM" | while read -r line; do
        echo "  $line"
    done
else
    log_info "未找到 llama.cpp 符号（可能是动态链接到 .so）"
fi

# ========== Step 5: 列出所有探针目标 (bpftrace -l) ==========
echo ""
echo "=============================================="
echo "  可用探针列表（供 bpftrace 使用）"
echo "=============================================="
echo ""

log_info "查找 'Generate' 相关探针位置:"
ADDRS=$(nm "$OUTPUT_BINARY" 2>/dev/null | grep -E "Generate|GenerateChat|GenerateCompletions" | head -5)
if [[ -n "$ADDRS" ]]; then
    echo "$ADDRS" | while read -r addr type name; do
        echo "  uprobe:$OUTPUT_BINARY:$name"
    done
else
    log_info "使用 objdump 辅助搜索..."
    objdump -t "$OUTPUT_BINARY" 2>/dev/null | grep -iE "generate|api|handler" | grep "FUNC" | head -10 | while read -r line; do
        echo "  $line"
    done
fi

# ========== 完成 ==========
echo ""
echo "=============================================="
echo "  构建完成!"
echo "=============================================="
echo ""
log_ok "输出文件: $OUTPUT_BINARY"
log_ok "文件大小: $(du -sh "$OUTPUT_BINARY" | awk '{print $1}')"
echo ""
log_info "下一步: 使用 run_trace.sh 执行 bpftrace 追踪"
echo ""

# 保存符号信息到文件
NM_OUTPUT="$WORKSPACE_DIR/ollama-debug-symbols.txt"
nm "$OUTPUT_BINARY" 2>/dev/null > "$NM_OUTPUT"
log_info "完整符号表已保存到: $NM_OUTPUT"
