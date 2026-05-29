# 项目阶段划分：从现在到答辩的完整时间线

> 本文档将整个毕业设计分解为 6 个明确的阶段，每个阶段有清晰的交付物和验收标准。

---

## 总体时间线

```
今天 (2026.05.10)
    │
    ▼ Phase 0: 规划与设计 ─────────────────────────── [Week 1-2]
    │
    ▼ Phase 1: 框架搭建 ────────────────────────────── [Week 3-4]
    │
    ▼ Phase 2: Ollama 分析（方法论验证）─────────────── [Week 5-8]
    │
    ▼ Phase 3: PyTorch 分析（规模扩展）──────────────── [Week 9-11]
    │
    ▼ Phase 4: vLLM 分析（综合验证）─────────────────── [Week 12-14]
    │
    ▼ Phase 5: 集成、可视化与测试 ────────────────────── [Week 15-17]
    │
    ▼ Phase 6: 论文撰写 ────────────────────────────── [Week 18-24]
    │
    ▼ 答辩 (2026.05 中旬)
```

---

## Phase 0: 规划与设计（当前阶段）

**时间**: Week 1-2（5月10日 - 5月24日）

### 目标

完成项目的顶层规划，确定技术方案，锁定目标软件版本。

### 交付物

| 交付物 | 状态 | 说明 |
|--------|------|------|
| `PROJECT_PLAN.md` | ✅ 完成 | 顶层规划 |
| `SOFTWARE_SELECTION.md` | ✅ 完成 | 软件选型分析 |
| `METHODOLOGY.md` | ✅ 完成 | 分析方法论 |
| `AUTOMATION_ARCH.md` | ✅ 完成 | 自动化架构 |
| `WORKLOAD_DESIGN.md` | ✅ 完成 | 工作量设计 |
| `PHASES.md`（本文） | ✅ 完成 | 阶段划分 |

### 验收标准

- [x] 确定分析哪三个软件（Ollama, PyTorch, vLLM）
- [x] 确定分析范围（文件读取，不含网络传输）
- [x] 确定技术路线（静态分析 + eBPF 动态追踪）
- [x] 确定代码量目标（12,000 行）

### 本阶段产出

> 你正在阅读的这套文档，就是 Phase 0 的全部产出。

---

## Phase 1: 框架搭建（基础设施）

**时间**: Week 3-4（5月25日 - 6月7日）

### 目标

搭建分析框架的骨架，包括目录结构、基础类、插件系统。

### 任务分解

```
Phase 1.1: 目录结构设计 (Week 3)
  ├── 创建项目目录结构
  ├── 编写 requirements.txt
  └── 配置 Git 仓库

Phase 1.2: 基础类设计 (Week 3-4)
  ├── 实现 CallGraphNode, CallGraphEdge 数据模型
  ├── 实现 SoftwarePlugin 基类
  ├── 实现 PluginRegistry 插件注册器
  └── 实现基础输出格式 (JSON/Mermaid)

Phase 1.3: 开发环境验证 (Week 4)
  ├── 安装 eBPF 工具链 (bpftrace, BCC)
  ├── 安装 Go 1.21+
  ├── 安装 clang/LLVM
  └── 验证 strace/eBPF 可用
```

### 交付物

```
analysis_framework/
├── collector/         # 静态符号采集器（骨架）
│   ├── __init__.py
│   ├── base.py
│   ├── go_analyzer.py
│   ├── cpp_analyzer.py
│   └── python_analyzer.py
│
├── tracer/            # 动态追踪器（骨架）
│   ├── __init__.py
│   ├── bpf/
│   └── runner.py
│
├── stitcher/           # 路径缝合引擎（骨架）
│   ├── __init__.py
│   ├── models.py
│   └── stitcher.py
│
├── analyzer/          # 差异检测（骨架）
│   ├── __init__.py
│   ├── tagger.py
│   └── diff_engine.py
│
├── visualizer/        # 可视化（骨架）
│   ├── __init__.py
│   └── app.py
│
├── plugins/          # 插件目录
│   ├── __init__.py
│   ├── base.py
│   └── registry.py
│
├── tests/            # 测试目录
├── scripts/          # 脚本目录
├── docs/             # 文档目录（你正在看的这些 .md 文件）
└── requirements.txt
```

### 验收标准

- [ ] 所有模块的 `__init__.py` 存在，导入无误
- [ ] `PluginRegistry` 能正确注册和加载插件
- [ ] `python -m framework --help` 能正常输出帮助信息
- [ ] eBPF/bpftrace 在当前环境可用（`bpftrace --version`）
- [ ] strace 能追踪 Ollama 的系统调用

---

## Phase 2: Ollama 分析（方法论验证）

**时间**: Week 5-8（6月8日 - 7月5日）

### 目标

对 Ollama 进行完整的静态+动态分析，验证方法论的可行性。

> 这是整个项目的**核心阶段**，Ollama 分析通过后，后续 PyTorch 和 vLLM 就是"增量开发"。

### 任务分解

```
Phase 2.1: Ollama 源码静态分析 (Week 5)
  ├── 识别所有文件读取入口点（GetModel, GetBlobsPath 等）
  ├── 构建 Go 层调用图
  ├── 识别 CGO 边界
  └── 生成 Go 层的调用树 (L1 → L2 → L3)

Phase 2.2: llama.cpp 静态分析 (Week 6)
  ├── 分析 llama_model_load_from_file 的 C++ 实现
  ├── 追踪 llama_file::open() 和 llama_mmap::impl()
  ├── 构建 llama.cpp 的调用图 (L3 → L4)
  └── 生成 C++ 层的调用树

Phase 2.3: eBPF 动态追踪 (Week 6-7)
  ├── 编写 kprobe 脚本追踪 open/read/mmap 系统调用
  ├── 编写 uprobe 脚本追踪 Go 函数入口
  ├── 运行 Ollama，捕获实际执行路径
  └── 收集动态追踪日志

Phase 2.4: 路径缝合与验证 (Week 7-8)
  ├── 实现缝合算法（FD 关联 + 时间窗口）
  ├── 生成完整的 Ollama 调用树（L1 → L5）
  ├── 对比静态和动态结果，发现差异
  └── 手动验证关键路径的正确性

Phase 2.5: 结果整理 (Week 8)
  ├── 生成 Mermaid 格式的调用树
  ├── 生成 JSON 格式的结构化数据
  └── 编写 Ollama 分析报告
```

### 交付物

```
output/ollama/
├── static/
│   ├── go_call_graph.json
│   ├── cpp_call_graph.json
│   └── cgo_boundary_map.json
│
├── dynamic/
│   ├── syscall_trace.json
│   ├── uprobe_trace.json
│   └── correlated_trace.json
│
├── stitched/
│   ├── call_trees.json          # 缝合后的调用树
│   ├── diff_report.json         # 静态/动态差异报告
│   └── risk_labels.json         # 风险标签
│
└── reports/
    ├── ollama_call_tree.md      # Mermaid 格式
    ├── ollama_analysis.md       # 分析报告
    └── verification.md          # 验证记录
```

### 验收标准

- [ ] 至少生成 5 棵主要的调用树
- [ ] 每棵树的深度 ≥ 5 层（L1 应用层到 L5 系统调用）
- [ ] CGO 边界节点正确标注
- [ ] 动态追踪覆盖至少 80% 的静态调用路径
- [ ] 手动验证至少 3 条关键路径的正确性

---

## Phase 3: PyTorch 分析（规模扩展）

**时间**: Week 9-11（7月6日 - 7月26日）

### 目标

将分析框架扩展到 PyTorch，处理 Python↔C++ 的边界。

### 任务分解

```
Phase 3.1: PyTorch 插件开发 (Week 9)
  ├── 创建 plugins/pytorch.py
  ├── 定义 entry_points（torch.load, DataLoader 等）
  ├── 定义 api_patterns（Python 和 C++）
  └── 配置 PyBind11 边界

Phase 3.2: PyTorch 静态分析 (Week 9-10)
  ├── 分析 torch.serialization.py 的 Python 调用链
  ├── 分析 ATen C++ 核心的调用图
  ├── 追踪 pickle 反序列化路径
  └── 构建 PyTorch 特有的 DataLoader 分析

Phase 3.3: PyTorch 动态追踪 (Week 10)
  ├── 编写测试用例 (torch.load, DataLoader)
  ├── 追踪 pickle.Unpickler 的行为
  ├── 追踪张量从 NumPy 到 Tensor 的转换路径
  └── 验证 CUDA 路径（如果环境支持 GPU）

Phase 3.4: 缝合与验证 (Week 11)
  ├── 应用缝合算法到 PyTorch 结果
  ├── 生成 PyTorch 调用树
  ├── 对比 Ollama 和 PyTorch 的差异
  └── 整理分析报告
```

### 交付物

```
output/pytorch/
├── static/           (同上结构)
├── dynamic/          (同上结构)
├── stitched/         (同上结构)
└── reports/          (同上结构)
```

### 验收标准

- [ ] 覆盖 torch.load 和 DataLoader 两条主要路径
- [ ] 正确处理 PyBind11 边界
- [ ] 展示 pickle 反序列化的特殊性
- [ ] 生成与 Ollama 对比的分析报告

---

## Phase 4: vLLM 分析（综合验证）

**时间**: Week 12-14（7月27日 - 8月16日）

### 目标

将分析框架扩展到 vLLM，处理最高难度的 CUDA/NCCL 边界。

### 任务分解

```
Phase 4.1: vLLM 插件开发 (Week 12)
  ├── 创建 plugins/vllm.py
  ├── 定义 entry_points（LLM.__init__, execute_model）
  ├── 定义 api_patterns（Python, C++, CUDA）
  └── 配置 NCCL 边界

Phase 4.2: vLLM 静态分析 (Week 12-13)
  ├── 分析 LLM 初始化路径
  ├── 分析 PagedAttention 的 C++ 实现
  ├── 分析 KV Cache 管理的内存操作
  └── 追踪 SSD offloading 路径（如果适用）

Phase 4.3: vLLM 动态追踪 (Week 13)
  ├── 追踪推理时的模型权重加载
  ├── 追踪 KV Cache 的内存分配
  └── 追踪 PagedAttention kernel 调用（CUDA）

Phase 4.4: 缝合与验证 (Week 14)
  ├── 应用缝合算法到 vLLM 结果
  ├── 生成 vLLM 调用树
  ├── 对比三个软件的共同模式和差异
  └── 整理分析报告
```

### 交付物

```
output/vllm/
├── static/           (同上结构)
├── dynamic/          (同上结构)
├── stitched/         (同上结构)
└── reports/          (同上结构)
```

### 验收标准

- [ ] 覆盖 LLM 初始化和推理两条主要路径
- [ ] 正确处理 CUDA kernel 调用边界
- [ ] 展示 KV Cache 的内存管理特殊性
- [ ] 生成三个软件的对比分析报告

---

## Phase 5: 集成、可视化与测试

**时间**: Week 15-17（8月17日 - 9月6日）

### 目标

将所有模块集成到一个统一的框架中，开发 Web 可视化界面，进行全面测试。

### 任务分解

```
Phase 5.1: 框架集成 (Week 15)
  ├── 统一所有模块的接口
  ├── 实现一键分析脚本 (scripts/analyze.sh)
  ├── 实现多软件对比分析功能
  └── 统一输出格式

Phase 5.2: Web 可视化开发 (Week 15-16)
  ├── 开发 Streamlit 应用
  ├── 实现调用树 D3.js 可视化
  ├── 实现多软件对比页面
  └── 实现风险报告页面

Phase 5.3: 测试与验证 (Week 16-17)
  ├── 编写单元测试（覆盖率 ≥ 80%）
  ├── 编写集成测试
  ├── 回归测试（确保三个软件都能正常运行）
  └── 性能测试（eBPF 开销评估）

Phase 5.4: 文档整理 (Week 17)
  ├── 编写用户手册
  ├── 编写开发者文档
  └── 整理项目 README
```

### 交付物

- [ ] 可运行的 Web 应用（`streamlit run visualizer/app.py`）
- [ ] 单元测试覆盖率报告
- [ ] 用户手册和开发者文档
- [ ] 项目 README

### 验收标准

- [ ] 三个软件的分析都能一键运行
- [ ] Web 界面能加载和展示调用树
- [ ] 测试覆盖率 ≥ 80%
- [ ] 文档齐全

---

## Phase 6: 论文撰写

**时间**: Week 18-24（9月7日 - 11月8日）

### 目标

完成毕业论文的撰写，包括方法论、实验、结论。

### 论文结构（建议）

```
毕业论文结构:

├── 摘要 (Abstract)
│
├── 第1章 绪论
│   ├── 1.1 研究背景
│   ├── 1.2 研究目的
│   └── 1.3 论文结构
│
├── 第2章 相关技术与工具
│   ├── 2.1 跨语言调用图分析技术
│   ├── 2.2 eBPF 内核追踪技术
│   ├── 2.3 开源 AI 软件概述 (Ollama, PyTorch, vLLM)
│   └── 2.4 本章小结
│
├── 第3章 系统设计与实现
│   ├── 3.1 总体架构
│   ├── 3.2 静态符号采集模块
│   ├── 3.3 动态行为追踪模块
│   ├── 3.4 路径缝合与差异检测模块
│   ├── 3.5 可视化展示模块
│   └── 3.6 本章小结
│
├── 第4章 实验与分析
│   ├── 4.1 实验环境
│   ├── 4.2 Ollama 调用链分析
│   ├── 4.3 PyTorch 调用链分析
│   ├── 4.4 vLLM 调用链分析
│   ├── 4.5 多软件对比分析
│   └── 4.6 本章小结
│
├── 第5章 总结与展望
│   ├── 5.1 工作总结
│   └── 5.2 未来展望
│
├── 参考文献
│
└── 致谢
```

### 论文工作量分配

| 章节 | 建议字数 | 写作时间 |
|------|---------|---------|
| 摘要 | 500-800 字 | 2 天 |
| 第1章 绪论 | 3,000-4,000 字 | 3 天 |
| 第2章 相关技术 | 5,000-6,000 字 | 5 天 |
| 第3章 系统设计 | 6,000-8,000 字 | 7 天 |
| 第4章 实验分析 | 6,000-8,000 字 | 7 天 |
| 第5章 总结 | 2,000-3,000 字 | 2 天 |
| 修改润色 | — | 5 天 |

**总计**: 约 25,000-30,000 字

### 验收标准

- [ ] 初稿完成（Week 22 前）
- [ ] 导师审阅通过
- [ ] 格式审查通过
- [ ] 查重通过（建议 < 15%）

---

## 关键里程碑

| 里程碑 | 日期 | 交付物 |
|--------|------|--------|
| M1: 框架可用 | 6月7日 | Phase 1 验收通过 |
| M2: Ollama 完成 | 7月5日 | Phase 2 验收通过 |
| M3: PyTorch 完成 | 7月26日 | Phase 3 验收通过 |
| M4: vLLM 完成 | 8月16日 | Phase 4 验收通过 |
| M5: 集成完成 | 9月6日 | Phase 5 验收通过 |
| M6: 初稿完成 | 10月中旬 | Phase 6 初稿 |
| M7: 答辩通过 | 11月中旬 | 最终版 |

---

## 风险与备选方案

| 风险 | 影响 | 应对策略 |
|------|------|---------|
| eBPF 环境不支持 | 无法动态追踪 | 降级使用 strace + gdb 作为替代 |
| GPU 不可用 | 无法追踪 CUDA 路径 | 跳过 CUDA 路径，只分析 CPU 路径 |
| vLLM 安装失败 | 无法分析 vLLM | 替换为 TensorRT-LLM |
| 时间不够 | 无法完成三个软件 | 优先保证 Ollama 和 PyTorch，vLLM 简化 |
| 缝合算法准确率低 | 论文贡献点受影响 | 引入人工标注作为 ground truth |
