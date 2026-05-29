# Demo 环境测试报告

**日期**: 2026-05-10
**目标**: 验证 Ollama 动态追踪环境可行性

---

## 环境概况

| 组件 | 版本/状态 | 备注 |
|------|---------|------|
| Ollama | 0.22.0 (已安装) | 运行在 CPU 模式 |
| 已下载模型 | tinyllama:latest (1B, Q4_0) | 637 MB |
| 系统内存 | 15.4 GiB 总 / 9.2 GiB 可用 | 充足 |
| strace | 6.19 | ✅ 可用 |
| bpftrace | 0.25.1 | ⚠️ 受沙箱限制 |
| 内核 | Linux 7.0.2-arch1-1 | eBPF 可用 |

---

## 测试结果

### ✅ Step 1: Ollama 启动 & API
- `ollama serve` 正常启动，监听 127.0.0.1:11434
- API 端点 `/api/tags` 返回正常
- 模型元数据存储在 `~/.ollama/blobs/` 和 `~/.ollama/manifests/`

### ✅ Step 2: strace 追踪 CLI (`ollama list`)
- 成功捕获 114 行系统调用
- 发现关键行为：
  - CLI spawn **9 个线程**（PID 17220-17228）
  - 线程间通过 **SIGURG 信号**通信
  - 与 daemon 通过 **HTTP API** (127.0.0.1:11434) 通信
  - `/home/typejetfire/.ollama/server.json` **不存在**（daemon 用 blobs/manifests 存储）

### ⚠️ Step 3: 追踪模型加载阶段
- `strace -p <daemon_pid>` 失败：`PTRACE_SEIZE: 不允许的操作`
  - 原因：沙箱限制 ptrace attach 到已有进程
  - 解决：可以用 `strace <command>` 追踪子进程（因为子进程会继承）
- `bpftrace` 失败：`Missing CAP_BPF capability`
  - 原因：沙箱剥离了所有 Linux capabilities (CapEff=0)
  - 即使 `all` 权限也无法恢复

### ✅ Step 4: 可行方案验证

#### 方案 A: strace 追踪子进程（推荐）
```bash
# 追踪 Ollama spawn 的 runner 子进程
strace -f -e trace=openat,read,mmap -o trace.txt ollama run <model> <prompt>
```
- `ollama run` 会 fork+exec 一个 `/usr/bin/ollama runner` 子进程
- strace 可以追踪到这个子进程（因为是 strace 的子进程）
- 已验证可行：成功捕获 clone/mmap/openat 调用

#### 方案 B: 从源码编译带 debug symbol 的版本
- Ollama 源码在 `ollama/` 目录
- 可以添加日志/metrics 端点来观察内部行为
- 适合深度静态分析

#### 方案 C: 在用户真实终端（非沙箱）运行
- 所有 tracing 工具（strace attach、bpftrace、perf）都需要真实 root
- 建议在用户自己的终端中执行核心追踪实验
- 沙箱内只做代码分析和结果汇总

---

## 关键发现

1. **Ollama 架构**：CLI → daemon (HTTP) → runner 子进程 (LLM 推理)
2. **SIGURG 信号**：Go runtime 用于线程间调度，tracing 时会看到大量此信号
3. **模型存储**：`~/.ollama/blobs/` 下以 SHA256 hash 命名，manifests 目录存元数据
4. **CGO 调用边界**：Ollama 通过 CGO 调用 `llama.cpp` 编译的 C 库

---

## 环境限制 & 建议

| 限制 | 影响 | 建议 |
|------|------|------|
| 沙箱无 ptrace attach | 无法追踪已有 daemon | 用 `strace <command>` 追踪新进程 |
| 沙箱无 CAP_BPF | bpftrace/perf 不工作 | 在真实终端运行，或改用 strace |
| CPU 推理慢 | tinyllama 单词生成约 1-2 秒 | 实测可接受 |
| 无 GPU | 无法测试 CUDA 路径 | 有 GPU 时再测一遍 |

---

## 下一步

1. **在用户终端运行**核心追踪命令（需要真实 root）：
   ```bash
   sudo bpftrace /path/to/trace.bt -c "ollama run tinyllama:latest hello"
   ```
2. **Phase 1**: 搭建静态分析框架，生成 CGO 边界调用图
3. **Phase 2**: 结合动态追踪数据，标注关键路径

---

## 沙箱工具可用性汇总

| 工具 | 新进程追踪 (`strace <cmd>`) | 附加追踪 (`strace -p`) | eBPF/bpftrace |
|------|------|------|------|
| 沙箱内 | ✅ | ❌ | ❌ |
| 真实终端 | ✅ | ✅ | ✅ |
