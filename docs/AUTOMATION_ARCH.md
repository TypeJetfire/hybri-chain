# 自动化与脚本化架构：如何用一套框架分析三个软件

> 本文档解决核心工程问题：如何设计一个可复用的分析框架，使得分析完 Ollama 后，
> 用最少的工作量（甚至不改代码）就能分析 PyTorch 和 vLLM。

---

## 1. 核心设计思想：插件化架构

### 1.1 问题定义

如果我们为每个软件写独立的分析脚本：

```
问题:
  - Ollama 分析脚本: 3000 行 Go + Python
  - PyTorch 分析脚本: 3000 行 Python
  - vLLM 分析脚本: 3000 行 Python
  ↓
  维护三套独立代码库，工作量 × 3
  换软件时需要重写大部分逻辑
```

### 1.2 解决方案：抽象层 + 插件架构

```
┌──────────────────────────────────────────────────┐
│              Analysis Framework (核心框架)         │
│                                                   │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐  │
│  │ Static      │ │ Dynamic     │ │ Stitching   │  │
│  │ Analyzer    │ │ Tracer      │ │ Engine      │  │
│  │ (通用)       │ │ (通用)       │ │ (通用)      │  │
│  └──────┬──────┘ └──────┬──────┘ └──────┬──────┘  │
│         │               │               │          │
│         └───────────────┴───────────────┘          │
│                         │                          │
│                    Plugin Layer                    │
│         ┌────────────────┼────────────────┐        │
│         ▼                ▼                ▼        │
│   ┌───────────┐   ┌───────────┐   ┌───────────┐  │
│   │ Ollama    │   │ PyTorch   │   │ vLLM      │  │
│   │ Plugin    │   │ Plugin    │   │ Plugin    │  │
│   └───────────┘   └───────────┘   └───────────┘  │
└──────────────────────────────────────────────────┘
```

**核心原则**: 框架不感知具体软件，插件定义"如何分析特定软件"。

### 1.3 插件接口定义

每个软件插件需要实现以下接口：

```python
class SoftwarePlugin(Protocol):
    """每个软件插件必须实现的接口"""

    # ===== 静态分析配置 =====
    name: str                    # 软件名称，如 "ollama"
    language_stack: list[str]   # 语言栈，如 ["go", "cgo", "cpp"]

    # 入口点配置：告诉框架从哪里开始分析
    entry_points: list[EntryPoint]

    # 特征模式：用于识别文件读取相关的 API 调用
    api_patterns: dict[str, list[str]]

    # CGO/PyBind 边界配置
    binding_config: BindingConfig

    # ===== 动态追踪配置 =====
    # 追踪时的启动命令和参数
    run_command: str
    run_args: list[str]
    env_vars: dict[str, str]

    # 追踪的 PID 过滤条件
    pid_filter: str

    # ===== 输出配置 =====
    output_format: str           # "json" | "mermaid" | "dot"
    output_dir: Path
```

---

## 2. 插件实现：Ollama Plugin

### 2.1 插件配置

```python
# plugins/ollama.py

class OllamaPlugin(SoftwarePlugin):
    name = "ollama"
    language_stack = ["go", "cgo", "cpp"]

    entry_points = [
        EntryPoint(
            path="server/api/generate.go",
            function="Generate",
            api_type="REST",
            description="生成请求入口 (POST /api/generate)"
        ),
        EntryPoint(
            path="server/api/chat.go",
            function="Chat",
            api_type="REST",
            description="对话请求入口 (POST /api/chat)"
        ),
        EntryPoint(
            path="server/api/pull.go",
            function="PullModel",
            api_type="REST",
            description="模型拉取入口 (POST /api/pull)"
        ),
        EntryPoint(
            path="server/images.go",
            function="GetModel",
            api_type="INTERNAL",
            description="模型元数据获取（最核心的读取入口）"
        ),
    ]

    api_patterns = {
        "go": [
            "os.Open", "os.OpenFile", "os.ReadFile",
            "os.Stat", "os.ReadDir",
            "C.llama_model_load_from_file",
            "C.gguf_init_from_file",
        ],
        "cgo": [
            "llama_model_load_from_file",
            "gguf_init_from_file",
            "llama_file_open",
            "mmap",
        ],
        "cpp": [
            "fopen", "fread", "fseek",
            "llama_file::open",
            "llama_mmap::impl",
            "std::ifstream::open",
        ]
    }

    binding_config = BindingConfig(
        cgo_file="llama/llama.go",
        cgo_header="llama.cpp/include/llama.h",
        cpp_source_dir="llama.cpp/src",
        boundary_marker="C.",  # Go 中调用 C 函数的标记
    )

    run_command = "ollama"
    run_args = ["run", "llama2", "hello"]
    pid_filter = "ollama"
```

### 2.2 插件激活

```python
# main.py

from plugins import PluginRegistry

def main():
    # 注册所有插件
    registry = PluginRegistry()
    registry.register("ollama", OllamaPlugin())
    registry.register("pytorch", PyTorchPlugin())
    registry.register("vllm", VLLMPlugin())

    # 分析指定的软件
    target = sys.argv[1]  # e.g., "ollama"
    plugin = registry.get(target)

    # 运行分析
    framework = AnalysisFramework(plugin)
    framework.analyze()
```

---

## 3. 插件实现：PyTorch Plugin（复用设计）

### 3.1 增量配置（相比 Ollama Plugin）

```python
# plugins/pytorch.py

class PyTorchPlugin(SoftwarePlugin):
    name = "pytorch"
    language_stack = ["python", "cpp", "cuda"]

    entry_points = [
        EntryPoint(
            path="torch/serialization.py",
            function="load",
            api_type="PYTHON_API",
            description="torch.load() 模型加载入口"
        ),
        EntryPoint(
            path="torch/utils/data/dataloader.py",
            function="DataLoader",
            api_type="PYTHON_API",
            description="DataLoader 数据加载器"
        ),
        EntryPoint(
            path="torch/_utils.py",
            function="from_blob",
            api_type="PYTHON_API",
            description="张量从内存创建（CPU/GPU 转换点）"
        ),
    ]

    api_patterns = {
        "python": [
            "torch.load", "torch.save",
            "torch.from_numpy", "torch.tensor",
            "open",  # 标准文件 I/O
            "pickle.load", "pickle.Unpickler",
            "DataLoader",
        ],
        "cpp": [
            "at::from_blob",
            "at::Tensor",
            "torch::pickle::load",
            "Storage::from_file",
        ],
    }

    # ★ 复用 Ollama Plugin 的通用逻辑
    # 只需要覆盖不同的部分：
    binding_config = BindingConfig(
        # PyTorch 使用 PyBind11，不是 CGO
        binding_type="pybind11",
        binding_file="torch/csrc/autograd/python_tensor.h",
        cpp_source_dir="torch/csrc",
        boundary_marker="PyObject*",  # PyBind11 的边界标记
    )

    run_command = "python"
    run_args = ["test_load.py"]  # 自定义测试脚本
    pid_filter = "python"
```

### 3.2 关键复用点

```
Ollama Plugin         PyTorch Plugin
     │                      │
     │  继承相同的基类        │
     ▼                      ▼
┌────────────────┐   ┌────────────────┐
│ SoftwarePlugin│   │ SoftwarePlugin│
│ (完全相同)     │   │ (完全相同)     │
└───────┬────────┘   └───────┬────────┘
        │                    │
        ▼                    ▼
  ┌──────────┐         ┌──────────┐
  │ entry_   │         │ entry_   │  ← 不同: 入口函数不同
  │ points   │         │ points   │
  └──────────┘         └──────────┘
        │                    │
        ▼                    ▼
  ┌──────────┐         ┌──────────┐
  │ api_     │         │ api_     │  ← 不同: API 模式不同
  │ patterns │         │ patterns │
  └──────────┘         └──────────┘
        │                    │
        ▼                    ▼
  ┌──────────────────────────────┐
  │  静态分析器 (Static Analyzer) │  ← 完全相同: 通用
  │  动态追踪器 (Dynamic Tracer)  │  ← 完全相同: 通用
  │  缝合引擎   (Stitching Eng.) │  ← 完全相同: 通用
  │  可视化器   (Visualizer)     │  ← 完全相同: 通用
  └──────────────────────────────┘
```

---

## 4. 插件实现：vLLM Plugin（复用设计）

```python
# plugins/vllm.py

class VLLMPlugin(SoftwarePlugin):
    name = "vllm"
    language_stack = ["python", "cpp", "cuda", "nccl"]

    entry_points = [
        EntryPoint(
            path="vllm/entrypoints/llm.py",
            function="LLM.__init__",
            api_type="PYTHON_API",
            description="vLLM 推理引擎初始化"
        ),
        EntryPoint(
            path="vllm/worker/model_runner.py",
            function="execute_model",
            api_type="PYTHON_API",
            description="模型执行入口（推理时的 I/O 集中在这里）"
        ),
        EntryPoint(
            path="vllm/distributed/parallel_manager.py",
            function="all_reduce",
            api_type="PYTHON_API",
            description="Tensor Parallelism 通信（GPU 间 NCCL 传输）"
        ),
    ]

    api_patterns = {
        "python": [
            "torch.load",
            "transformers.AutoModel.from_pretrained",
            "PagedAttention.forward",
            "block_manager.allocate",
            "nccl.all_reduce",  # 分布式通信
            "open", "os.path.exists",
        ],
        "cpp": [
            "paged_attention_kernel",
            "reshape_and_cache",
            "GPUAllocator::allocate",
        ],
        "cuda": [
            "cudaMemcpy",
            "cuMemcpy",
            "cudaMalloc",
        ],
    }

    binding_config = BindingConfig(
        binding_type="pybind11",       # Python ↔ C++
        binding_type_2="cuda",          # C++ ↔ CUDA
        binding_file="vllm/model_executor/weight_loader.h",
        cpp_source_dir="vllm/csrc",
        boundary_marker="pybind11::",
    )

    run_command = "python"
    run_args = ["test_vllm.py"]
    pid_filter = "python"
```

---

## 5. 脚本化执行流程

### 5.1 一键分析脚本

```bash
#!/bin/bash
# scripts/analyze.sh

SOFTWARE=$1
PHASE=${2:-"all"}  # all | static | dynamic | stitch

# 步骤 1: 静态分析
if [ "$PHASE" == "all" ] || [ "$PHASE" == "static" ]; then
    echo "[1/3] Running static analysis for $SOFTWARE..."
    python -m framework.static_analyzer \
        --plugin $SOFTWARE \
        --output output/$SOFTWARE/static_results.json
fi

# 步骤 2: 动态追踪
if [ "$PHASE" == "all" ] || [ "$PHASE" == "dynamic" ]; then
    echo "[2/3] Running dynamic tracing for $SOFTWARE..."
    python -m framework.dynamic_tracer \
        --plugin $SOFTWARE \
        --pid-filter "$SOFTWARE" \
        --output output/$SOFTWARE/dynamic_trace.json
fi

# 步骤 3: 路径缝合
if [ "$PHASE" == "all" ] || [ "$PHASE" == "stitch" ]; then
    echo "[3/3] Stitching static and dynamic results..."
    python -m framework.stitcher \
        --plugin $SOFTWARE \
        --static output/$SOFTWARE/static_results.json \
        --dynamic output/$SOFTWARE/dynamic_trace.json \
        --output output/$SOFTWARE/call_trees.json
fi

# 步骤 4: 生成可视化
echo "[+] Generating call tree visualization..."
python -m framework.visualizer \
    --input output/$SOFTWARE/call_trees.json \
    --format mermaid \
    --output output/$SOFTWARE/call_trees.md

echo "[+] Done! Results saved to output/$SOFTWARE/"
```

### 5.2 使用方式

```bash
# 分析 Ollama
./scripts/analyze.sh ollama all

# 只做静态分析（快速迭代）
./scripts/analyze.sh pytorch static

# 只做动态追踪（调试时用）
./scripts/analyze.sh vllm dynamic

# 换软件分析（零代码改动）
./scripts/analyze.sh pytorch all
./scripts/analyze.sh vllm all
```

### 5.3 CI/CD 集成（可选）

```yaml
# .github/workflows/analyze.yml
name: API Call Chain Analysis

on:
  push:
    branches: [main]
  schedule:
    - cron: '0 2 * * 0'  # 每周日凌晨 2 点自动运行

jobs:
  analyze:
    runs-on: ubuntu-24.04
    strategy:
      matrix:
        software: [ollama, pytorch, vllm]

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: |
          pip install framework
          pip install -r requirements.txt

      - name: Run analysis
        run: ./scripts/analyze.sh ${{ matrix.software }} all

      - name: Upload artifacts
        uses: actions/upload-artifact@v4
        with:
          name: results-${{ matrix.software }}
          path: output/${{ matrix.software }}/
```

---

## 6. 复用性量化评估

### 6.1 代码复用率

| 模块 | 行数 | 被复用次数 | 复用率 |
|------|------|-----------|--------|
| StaticAnalyzer (Go/Python/C++ AST 解析) | 1,200 | 3 | 100% |
| CGOBindingParser (跨语言边界解析) | 600 | 3 | 100% |
| DynamicTracer (eBPF 脚本生成) | 800 | 3 | 100% |
| Stitcher (路径缝合算法) | 1,200 | 3 | 100% |
| Visualizer (调用树渲染) | 600 | 3 | 100% |
| **框架核心（通用）** | **4,400** | **3** | **100%** |
| Ollama Plugin | 500 | 1 | 33% |
| PyTorch Plugin | 400 | 1 | 33% |
| vLLM Plugin | 600 | 1 | 33% |
| **插件（专用）** | **1,500** | **平均 1** | **33%** |

**结论**: 框架核心代码（4,400 行）被 3 个软件复用，复用率 100%，避免了 4,400 × 3 = 13,200 行的重复开发。

### 6.2 新增一个软件的工作量

```
新增一个软件 X 的工作量:

1. 创建插件文件 plugins/x.py:
   - 定义 entry_points (约 30 行配置)
   - 定义 api_patterns (约 30 行配置)
   - 定义 binding_config (约 20 行配置)
   - 定义 run_command (约 10 行配置)
   
   小计: ~100 行配置代码（无需写逻辑！）

2. 创建测试用例:
   - 测试脚本 test_x.py (约 50 行)
   
3. 注册插件:
   - 在 registry.py 中添加一行注册代码
   
总工作量: ~200 行新增代码
```

---

## 7. 测试策略

### 7.1 测试用例设计

每个软件需要设计多个测试用例，覆盖不同的执行路径：

```
Ollama 测试用例:
  ├─ TC1: ollama run llama2 "hello"         (基础推理)
  ├─ TC2: ollama run llama2 "写代码"        (中文推理)
  ├─ TC3: POST /api/chat (API 调用)        (REST API 路径)
  ├─ TC4: ollama pull llama3               (模型下载)
  └─ TC5: ollama show llama2               (模型信息展示)

PyTorch 测试用例:
  ├─ TC1: torch.load("model.pt")           (基础加载)
  ├─ TC2: DataLoader(CustomDataset)        (数据加载器)
  ├─ TC3: torch.from_numpy(ndarray)         (NumPy 转换)
  └─ TC4: model = torchvision.models.*()   (预训练模型)

vLLM 测试用例:
  ├─ TC1: LLM(model="llama2")              (基础初始化)
  ├─ TC2: llm.generate(prompts)            (推理执行)
  ├─ TC3: 多 GPU Tensor Parallelism         (分布式推理)
  └─ TC4: 长文本生成 (触发 KV Cache 换页)   (内存管理路径)
```

### 7.2 回归测试

每次代码更新后，自动运行所有测试用例，确保框架对所有三个软件的分析结果一致性：

```python
# tests/test_regression.py

def test_all_plugins():
    """确保框架对所有软件都能正常运行"""
    registry = PluginRegistry()
    for plugin_name in ["ollama", "pytorch", "vllm"]:
        plugin = registry.get(plugin_name)
        framework = AnalysisFramework(plugin)

        # 静态分析
        static_result = framework.run_static()
        assert static_result is not None
        assert len(static_result.call_graph) > 0

        # 动态追踪（如果环境支持）
        if can_trace():
            dynamic_result = framework.run_dynamic()
            assert dynamic_result is not None
            assert len(dynamic_result.trace) > 0

            # 缝合
            stitched = framework.run_stitch()
            assert len(stitched.trees) > 0
```
