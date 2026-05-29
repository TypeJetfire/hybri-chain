# 工作量设计：如何用 10,000 行代码构建一个"看起来很强"的毕设

> 本文档解决一个现实问题：如何在毕设中体现足够的工作量，
> 让答辩评委觉得"这个学生做了很多事"，同时代码本身是合理的、有技术含量的。

---

## 1. 工作量的衡量标准

### 1.1 答辩评委如何看待"工作量"

在毕业论文答辩中，"工作量"通常体现在以下几个方面：

| 维度 | 评委关注点 | 体现方式 |
|------|-----------|---------|
| **代码量** | 写了多少行代码 | 总代码行数 + 模块数 |
| **技术深度** | 用了多复杂的技术 | eBPF、内核编程、跨语言分析 |
| **覆盖广度** | 分析了多少软件/场景 | 3 个开源软件、多种调用路径 |
| **系统性** | 是否有体系化的方法论 | 框架设计、插件架构 |
| **可视化** | 成果是否直观可展示 | 调用树可视化、Web 界面 |
| **可验证性** | 结论是否有实验支撑 | 实测数据、对比实验 |

### 1.2 什么样的代码不算"多余"

以下类型的代码是被认可的"有效工作量"：

- ✅ **工具体**：为解决特定问题写的工具脚本
- ✅ **实验代码**：跑实验用的数据处理、结果分析脚本
- ✅ **基础设施**：框架核心、插件系统
- ✅ **可视化**：Web 界面、调用树渲染

以下类型的代码会被认为"水"：

- ❌ **重复代码**：三个插件之间没有抽象，直接复制粘贴
- ❌ **注释填充**：大量无意义的注释（如 `// 这是打开文件的函数`）
- ❌ **过度的空行和格式化**：为了凑行数添加无意义的空行
- ❌ **包装过度的框架**：用一个 100 行的类包装一个 10 行的函数

---

## 2. 五大模块的代码量分配

### 2.1 总览

```
总目标: 10,000 行
         │
         ├── Collector (静态符号采集器)     ~2,500 行
         ├── Tracer (eBPF 动态追踪器)       ~3,000 行
         ├── Stitcher (路径缝合引擎)         ~2,500 行
         ├── Analyzer (差异检测与风险评估)    ~2,000 行
         └── Visualizer (Web 可视化界面)     ~2,000 行
                                                        ─── 溢出到 12,000 行
```

### 2.2 模块详细分解

---

## 模块 1: Collector — 多语言静态符号采集器 (~2,500 行)

### 目标

实现一个能自动分析 Go、C++、Python 源码的工具，构建跨语言的函数调用图。

### 代码量分解

```
Collector/
├── __init__.py                          20 行
│
├── base.py                             250 行
│   ├── class LanguageAnalyzer (基类)    150 行
│   ├── class CallGraphNode              50 行
│   └── class CallGraphEdge              50 行
│
├── go_analyzer.py                      600 行
│   ├── class GoAnalyzer (继承 LanguageAnalyzer)   200 行
│   ├── class GoASTParser (Go AST 解析)           150 行
│   ├── class GoSymbolExtractor (符号提取)         100 行
│   ├── class CGOBoundaryDetector (CGO 边界识别)   150 行
│
├── cpp_analyzer.py                     700 行
│   ├── class CppAnalyzer (继承 LanguageAnalyzer)  150 行
│   ├── class ClangBinding (Clang AST 绑定)        200 行
│   ├── class CPPFileParser (文件解析)              150 行
│   ├── class SymbolTableReader (符号表读取)        100 行
│   └── class MMAPP athDetector (mmap 路径识别)    100 行
│
├── python_analyzer.py                  500 行
│   ├── class PythonAnalyzer (继承 LanguageAnalyzer)  100 行
│   ├── class PyBindDetector (PyBind11 边界识别)      150 行
│   ├── class PicklePatternScanner (pickle 模式)     150 行
│   └── class DataLoaderAnalyzer (DataLoader 分析)    100 行
│
├── cross_language_mapper.py            350 行
│   ├── class CrossLangMapper (跨语言映射)           200 行
│   └── class BindingTableGenerator (绑定表生成)     150 行
│
└── utils.py                            80 行

小计: 2,500 行
```

### 技术含量（评委看点）

- **Go AST 解析**：直接操作 Go 语言的抽象语法树，理解 Go 的并发模型（goroutine）
- **Clang Tooling**：使用工业级 C++ 编译器前端进行代码分析
- **跨语言符号映射**：解决 Go↔CGO↔C++ 的符号对应问题

### 为什么不算多余

这是整个项目的**数据采集层**，没有这个模块就无法进行后续的缝合和可视化。代码是直接服务于分析目标的。

---

## 模块 2: Tracer — eBPF 内核态动态追踪器 (~3,000 行)

### 目标

用 eBPF 技术编写内核态探针，追踪 Ollama/PyTorch/vLLM 运行时从用户态到内核的系统调用序列。

### 代码量分解

```
Tracer/
├── __init__.py                          20 行
│
├── bpf/
│   ├── syscall_trace.bpf.c              400 行  (内核态追踪脚本)
│   ├── uprobe_trace.bpf.c               300 行  (用户态探针脚本)
│   └── vfs_monitor.bpf.c                250 行  (VFS 层监控)
│
├── runner.py                            400 行
│   ├── class BPFProgram (BPF 程序管理)   150 行
│   ├── class KprobeManager (kprobe 管理)  150 行
│   └── class ProcessFilter (进程过滤)    100 行
│
├── userspace/
│   ├── tracer_core.py                   300 行
│   │   ├── class BpftraceRunner          100 行
│   │   ├── class StraceBridge            100 行
│   │   └── class PerfCollector           100 行
│   │
│   ├── syscall_parser.py                250 行
│   │   ├── class SyscallDecoder          150 行
│   │   └── class FDTracker (文件描述符追踪) 100 行
│   │
│   └── correlator.py                    300 行
│       ├── class TimeWindowCorrelator    150 行
│       └── class StackTraceAligner      150 行
│
├── ebpf/
│   ├── loader.py                        200 行
│   │   ├── class BPFProgramLoader        100 行
│   │   └── class BPFMapReader            100 行
│   │
│   └── compiler.py                      180 行
│       └── class BPFCompiler             180 行
│
└── report.py                            100 行

小计: 3,000 行
```

### 技术含量（评委看点）

- **eBPF 内核编程**：Linux 4.x+ 引入的高级追踪技术，能在不修改内核代码的情况下追踪任意内核函数
- **kprobe/uprobe 双层追踪**：同时在用户态和内核态插桩
- **零拷贝数据传输**：BPF Map 的高效数据传递

### 为什么不算多余

eBPF 是当前 Linux 系统性能分析和安全审计的**前沿技术**，在网安领域有极高的认可度。写 eBPF 程序本身就是一个技术门槛。

### 评委可能的提问

- eBPF 的安全机制是什么？（验证阶段、加载阶段、运行阶段）
- 为什么选择 eBPF 而不是 strace？
- BPF Map 是如何工作的？

---

## 模块 3: Stitcher — 静态动态路径缝合引擎 (~2,500 行)

### 目标

将静态分析得到的"理论调用图"和动态追踪得到的"实际执行序列"进行匹配和缝合，生成完整的调用树。

### 代码量分解

```
Stitcher/
├── __init__.py                          20 行
│
├── models.py                           200 行
│   ├── class CallTreeNode               80 行
│   ├── class CallTree                    50 行
│   ├── class StaticEdge                  30 行
│   └── class DynamicTrace                40 行
│
├── static_graph_builder.py             350 行
│   ├── class StaticGraphBuilder         150 行
│   ├── class GraphTraversal               100 行
│   └── class NodeDeduplicator             100 行
│
├── dynamic_trace_processor.py          350 行
│   ├── class TraceParser                 150 行
│   ├── class TimeSeriesAlign             100 行
│   └── class SyscallSequenceExtractor    100 行
│
├── stitcher.py                          600 行
│   ├── class PathStitcher                200 行
│   │   ├── method: stitch_by_fd           # 通过文件描述符关联
│   │   ├── method: stitch_by_timestamp    # 通过时间窗口关联
│   │   └── method: stitch_by_symbol       # 通过符号名关联
│   │
│   ├── class BoundaryStitcher            150 行
│   │   ├── method: stitch_cgo_boundary    # 缝合 CGO 边界
│   │   └── method: stitch_pybind_boundary # 缝合 PyBind 边界
│   │
│   └── class GraphMerger                 250 行
│       ├── method: merge_static_dynamic   # 合并静态和动态图
│       ├── method: resolve_ambiguity      # 解决歧义
│       └── method: annotate_risk          # 标注风险节点
│
├── differ.py                            400 行
│   ├── class DifferenceDetector          150 行
│   │   ├── method: detect_hidden_paths   # 检测隐藏路径
│   │   ├── method: detect_lost_nodes     # 检测丢失节点
│   │   └── method: detect_path_drift      # 检测路径偏离
│   │
│   ├── class RiskAssessor               150 行
│   │   ├── method: assess_data_sensitivity
│   │   └── method: assess_boundary_risk
│   │
│   └── class ReportGenerator            100 行
│
└── validation/
    ├── validator.py                     180 行
    └── test_stitcher.py                 400 行 (单元测试 + 集成测试)

小计: 2,500 行
```

### 技术含量（评委看点）

- **图算法**：调用树本质上是一个 DAG，缝合过程涉及图匹配算法
- **时序分析**：动态追踪的核心是时间序列数据，需要进行对齐和关联
- **边界语义推理**：CGO/PyBind 边界的语义缝合是一个非平凡问题

### 为什么不算多余

这是论文的**核心算法部分**。缝合算法的设计直接决定了分析结果的准确率，是论文"方法创新"的体现。

---

## 模块 4: Analyzer — 差异检测与风险评估 (~2,000 行)

### 目标

对缝合后的调用树进行后处理，检测静态和动态分析之间的差异，评估每个节点的数据安全风险。

### 代码量分解

```
Analyzer/
├── __init__.py                          20 行
│
├── tagger.py                            350 行
│   ├── class SecurityTagger             150 行
│   │   ├── method: tag_io_operations    # 标记 I/O 操作
│   │   ├── method: tag_crypto_ops       # 标记加密操作
│   │   └── method: tag_boundary_crosses  # 标记跨边界
│   │
│   └── class RiskLabeler                200 行
│       ├── method: label_by_type        # 按操作类型标签
│       ├── method: label_by_sensitivity  # 按数据敏感度标签
│       └── method: label_by_depth       # 按调用深度标签
│
├── diff_engine.py                       400 行
│   ├── class CoverageAnalyzer           150 行
│   │   ├── method: compute_static_coverage   # 静态覆盖率
│   │   └── method: compute_dynamic_coverage  # 动态覆盖率
│   │
│   ├── class DriftDetector              150 行
│   │   ├── method: detect_branch_drift       # 检测分支偏离
│   │   └── method: detect_call_order_drift   # 检测调用顺序偏离
│   │
│   └── class AnomalyFinder              100 行
│       └── method: find_unexpected_calls     # 发现意外调用
│
├── risk_evaluator.py                    350 行
│   ├── class RiskScorer                 200 行
│   │   ├── method: score_by_data_type   # 按数据类型评分
│   │   ├── method: score_by_operation   # 按操作类型评分
│   │   └── method: compute_final_score   # 综合评分
│   │
│   └── class VulnerabilityLocator       150 行
│       ├── method: find_buffer_overflow_risks  # 缓冲区溢出风险
│       └── method: find_info_disclosure_risks  # 信息泄露风险
│
├── report/
│   ├── tree_report.py                   200 行
│   │   └── class TreeReportGenerator
│   │
│   ├── diff_report.py                   200 行
│   │   └── class DiffReportGenerator
│   │
│   └── risk_report.py                   180 行
│       └── class RiskReportGenerator
│
└── tests/
    └── test_analyzer.py                 300 行

小计: 2,000 行
```

### 技术含量（评委看点）

- **安全标签体系**：为每个调用节点设计一套安全标签（IO_FILE、CRYPTO、CGO_BOUNDARY 等）
- **风险评分模型**：综合数据敏感度、操作类型、边界跨越次数等维度评估风险
- **差异分析**：发现"静态分析有但动态追踪没有"和"动态追踪有但静态分析没有"的路径

---

## 模块 5: Visualizer — Web 交互式可视化界面 (~2,000 行)

### 目标

将分析结果以 Web 界面的形式展示，支持交互式浏览调用树、放大缩小、点击展开节点。

### 代码量分解

```
Visualizer/
├── app.py                               300 行
│   └── Streamlit Web 应用主入口
│
├── pages/
│   ├── 1_Overview.py                    200 行  (总览页面)
│   ├── 2_Call_Tree.py                   350 行  (调用树详情页)
│   ├── 3_Comparison.py                 250 行  (多软件对比页)
│   └── 4_Risk_Report.py                 200 行  (风险报告页)
│
├── components/
│   ├── tree_renderer.py                 350 行
│   │   ├── class D3TreeRenderer         150 行  (D3.js 渲染封装)
│   │   └── class MermaidRenderer        100 行  (Mermaid 渲染)
│   │
│   └── stats_chart.py                   150 行
│       └── class StatsChart              150 行  (统计图表)
│
├── utils/
│   ├── data_loader.py                   150 行
│   │   └── class JSONDataLoader
│   │
│   └── formatters.py                    100 行
│       └── class OutputFormatter         100 行
│
├── static/
│   └── custom.css                       50 行
│
└── templates/
    └── report_template.html             150 行

小计: 2,000 行
```

### 技术含量（评委看点）

- **D3.js 树形图**：业界标准的 Web 可视化库
- **Streamlit**：快速构建数据科学 Web 应用
- **交互式探索**：支持缩放、拖拽、点击展开

### 为什么不算多余

可视化是毕设的**直接成果展示**，评委可以通过点击调用树直观看到分析结果。一张好的可视化图胜过千言万语。

---

## 3. 额外工作：实验与文档

除了代码，还有一些"软性"工作量：

### 3.1 测试用例编写

```python
# 为每个模块编写单元测试和集成测试
# 预计额外 2,000 行测试代码

tests/
├── test_collector/
│   ├── test_go_analyzer.py              300 行
│   ├── test_cpp_analyzer.py             350 行
│   └── test_python_analyzer.py          200 行
│
├── test_tracer/
│   ├── test_bpf_loader.py               200 行
│   └── test_correlator.py               300 行
│
├── test_stitcher/
│   ├── test_stitcher.py                 400 行
│   └── test_differ.py                   300 行
│
└── test_integration/
    ├── test_ollama_pipeline.py          250 行
    └── test_pytorch_pipeline.py         200 行

额外测试代码: ~2,500 行
```

### 3.2 实验数据分析脚本

```python
# 用于处理实验结果、生成图表的数据分析脚本
analysis/
├── plot_coverage.py                     200 行
├── plot_risk_distribution.py             150 行
├── compare_software.py                   250 行
└── generate_tables.py                    150 行

额外分析脚本: ~750 行
```

---

## 4. 工作量总览

| 模块 | 核心代码 | 测试代码 | 合计 |
|------|---------|---------|------|
| Collector | 2,500 | 850 | 3,350 |
| Tracer | 3,000 | 700 | 3,700 |
| Stitcher | 2,500 | 400 | 2,900 |
| Analyzer | 2,000 | 300 | 2,300 |
| Visualizer | 2,000 | 100 | 2,100 |
| 分析脚本 | 750 | — | 750 |
| **总计** | **12,750** | **2,350** | **15,100** |

**最终交付**: 约 **12,000 行**核心代码 + **3,000 行**测试和辅助代码 = **15,000 行**

这个代码量在本科毕设中属于**中上水平**，足够体现工作量，又不会显得过度工程化。

---

## 5. 如何让 AI 写的代码"扎实"而不是"水"

在与 Cursor 对话时，要求 AI 遵循以下规范：

```
质量要求:
  1. 每个函数必须有类型注解 (type hints)
  2. 每个公共类必须有 docstring
  3. 异常处理要完整 (try/except + 明确的异常类型)
  4. 单元测试覆盖率 ≥ 80%
  5. 不要写无意义的注释 (避免 "// 打开文件" 这样的注释)
  6. 优先使用设计模式 (Factory, Strategy, Observer)
  7. 遵循 PEP8 代码风格
```

这样 AI 生成的代码虽然多，但每一行都是有意义的。
