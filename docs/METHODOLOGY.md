# 分析方法论：静态符号提取与动态行为追踪

> 本文档详细定义静态分析和动态追踪的具体方法、工具链和技术细节。
> 是整个项目技术路线的核心文档。

---

## 1. 静态分析：构建异构调用图

### 1.1 总体思路

静态分析的目的是**不运行程序**，从源码层面构建"理论上的"函数调用关系图。核心挑战是**跨语言边界的符号映射**。

```
Go 源码 ──[Go AST]──> Go 符号表 ─┐
                                 ├─> 统一调用图 (JSON)
CGO 绑定 ──[文本解析]──> 绑定表 ──┤
C++ 源码 ──[Clang AST]──> C++ 符号表 ─┘
```

### 1.2 Layer 1: Go 层符号提取

#### 工具链

| 工具 | 用途 | 命令示例 |
|------|------|---------|
| `go/ast` 标准库 | AST 解析 | `go run ./cmd/astparse ...` |
| `go list -json` | 包依赖分析 | `go list -json ./...` |
| `go tool objdump` | 符号表导出 | `go tool objdump ollama` |
| `golang.org/x/tools/go/ast` | 增强 AST 分析 | API 调用识别 |
| `staticcheck` | 静态代码分析 | `staticcheck ./...` |

#### 提取步骤

**Step 1: 识别文件读取入口点**

在 Go 代码中，与文件读取相关的 API 模式包括：

```go
// 模式 1: os 包
os.Open(name)
os.OpenFile(name, flag, perm)
os.ReadFile(name)
os.Stat(name)
os.ReadDir(name)

// 模式 2: io 包
io.ReadAll(r)
io.ReadFull(r, buf)
io.Copy(dst, src)

// 模式 3: bufio 包
bufio.NewReader(f)
bufio.NewScanner(f)

// 模式 4: os/exec (可能读取外部程序)
exec.Command(cmd)

// 模式 5: net/http (网络 I/O)
http.Get(url)
http.Post(url, bodyType, body)
```

**Step 2: 追踪函数调用链**

对每个入口点，向上回溯其调用者，形成调用树：

```
分析函数: server/images.go:GetModel()

1. 定位函数定义: func GetModel(...)
2. 解析函数体 AST:
   - 找出所有函数调用: callExpr := x *ast.CallExpr
   - 对每个调用，解析其函数名和参数
3. 递归处理被调用的函数:
   - 调用 os.Open   → 标记为"系统库调用"，停止
   - 调用 GetBlobsPath() → 递归分析
   - 调用 json.Unmarshal() → 标记为"序列化调用"，停止
4. 构建调用树
```

**Step 3: 识别 CGO 边界**

CGO 调用的识别模式：

```go
// 识别模式 1: 直接 C. 函数调用
import "C"
func LoadModel(path string) {
    cPath := C.CString(path)
    defer C.free(unsafe.Pointer(cPath))
    C.llama_model_load_from_file(cPath)  // ← 边界标记
}

// 识别模式 2: 通过桥接包调用
import "github.com/ollama/ollama/llama"
func LoadModel(path string) {
    llama.LoadModel(path)  // ← 需要追踪到 llama 包内的 CGO 调用
}
```

### 1.3 Layer 2: CGO 绑定解析

#### 问题定义

Go 编译器在编译时生成 CGO 桥接代码，但我们需要**反向**从 Go 代码中识别出它调用的 C 函数，以及这些 C 函数对应的 C++ 实现。

#### 解析方法

**方法 A: 解析 CGO 注释（C 文件映射法）**

Ollama 的 `llama/llama.go` 中包含：

```go
// #cgo CFLAGS: -I${SRCDIR}/../llama.cpp
// #include "llama.h"
import "C"

func LoadModel(path *C.char) {
    C.llama_model_load_from_file(path)
}
```

我们需要：

1. 解析 `#include "llama.h"` → 确定 C 头文件路径
2. 读取 `llama.h` → 找到 `llama_model_load_from_file()` 的声明
3. 读取 `llama.cpp` → 找到该函数定义

**方法 B: 符号表交叉引用**

```
Go 二进制符号表:
  github.com/ollama/ollama/llama.LoadModelFromFile
    └─> _cgoexp.8314055aaf60.llama_LoadModelFrom_file
      └─> crosscall2 (CGO trampoline)
        └─> llama_model_load_from_file (C symbol)

通过 nm -g ollama_binary | grep llama_model_load_from_file
找到 C 符号地址，再交叉引用 llama.cpp 源码
```

#### 输出格式

```json
{
  "cgo_boundary": {
    "id": "cb_001",
    "go_function": "github.com/ollama/ollama/llama.LoadModelFromFile",
    "go_file": "llama/llama.go:45",
    "c_function": "llama_model_load_from_file",
    "c_header": "llama.h:210",
    "cplusplus_function": "llama_model_loader::init",
    "cplusplus_file": "llama.cpp/src/llama-model-loader.cpp:849",
    "call_type": "synchronous"
  }
}
```

### 1.4 Layer 3: C++ 层符号提取

#### 工具链

| 工具 | 用途 |
|------|------|
| `clang` + `clang tooling` | C++ AST 解析（Clang 是 GCC 的替代，clangd 的基础） |
| `cflow` | 生成 C 调用图（不支持 C++） |
| `doxygen` + Graphviz | 生成函数调用关系图 |
| `pybind11-stubgen` | 从 pybind11 生成 Python stub |
| `nm` / `readelf` | ELF 符号表分析 |
| `objdump -d` | 反汇编分析 |

#### 提取步骤（针对 llama.cpp）

**Step 1: 建立符号索引**

```bash
# 对 llama.cpp 建立 ctags 索引
ctags -R --languages=c++ llama.cpp/src/

# 使用 cscope 建立符号交叉引用
cscope -Rb
```

**Step 2: 追踪 llama_model_load_from_file**

```
llama.cpp/include/llama.h:
  llama_model *llama_model_load_from_file(
      struct llama_context_params params,
      const char *path_model,
      struct llama_model_kv_override *kv_overrides)

llama.cpp/src/llama-model-loader.cpp:
  llama_model *llama_model_load_from_file(
      struct llama_context_params params,
      const char *path_model,
      ...) {
      llama_model_loader loader(path_model);  // 构造函数
      return loader.load(...);                 // 委托给 loader
  }

llama.cpp/src/llama-model-loader.cpp:
  llama_model_loader::llama_model_loader(const char * path) {
      file = llama_file_open(path, "rb");     // ★ 文件打开
  }

llama.cpp/src/llama-mmap.cpp:
  llama_file *llama_file_open(const char * path, const char * mode) {
      int fd = open(path, O_RDONLY);           // ★ 系统调用前最后一步
      ...
  }
```

**Step 3: 识别内存映射路径**

llama.cpp 根据文件大小选择读取方式：

```
llama_model_loader::init() {
    if (use_mmap) {
        // 路径 A: mmap
        mappings = std::make_unique<llama_mmap>(fd, file_size);
    } else {
        // 路径 B: 逐块 read()
        buffer = std::make_unique<uint8_t[]>(file_size);
        read(fd, buffer.get(), file_size);
    }
}
```

### 1.5 静态分析的局限性

静态分析有以下固有限制，需要动态追踪来补充：

| 限制 | 原因 | 动态补充方式 |
|------|------|------------|
| 无法确定运行时分支 | if/else、函数指针的分支在运行时决定 | eBPF 追踪实际路径 |
| 模板/泛型实例化 | C++ 模板在编译时实例化 | 读取二进制 DWARF 信息 |
| 动态加载 | dlopen/dlsym 在运行时决定 | 追踪 dlopen 系统调用 |
| 反射/eval | Python 的 `__getattr__`、eval | 追踪 Python 运行时行为 |

---

## 2. 动态追踪：捕获真实执行路径

### 2.1 总体思路

动态追踪的目的是**运行程序**，在程序执行过程中捕获真实的系统调用序列，填补静态分析的盲区。

```
Ollama 运行时
  │
  ├─> 用户态函数调用 (应用层 API)
  │     └─> ★ uprobe: 捕获用户态函数入口/出口
  │
  ├─> Go runtime / libc (库层)
  │     └─> ★ uprobe / USDT: 捕获库函数调用
  │
  └─> Linux Kernel (内核层)
        └─> ★ kprobe: 捕获系统调用入口
              └─> tracepoint:syscalls/sys_enter_*: 捕获系统调用参数
```

### 2.2 工具选择

| 工具 | 适用场景 | 优点 | 缺点 |
|------|---------|------|------|
| **strace** | 快速原型、系统调用追踪 | 零配置、即开即用 | 开销大、无法追踪用户态调用栈 |
| **ltrace** | 动态库调用追踪 | 简单易用 | 无法追踪系统调用和 Go 函数 |
| **perf** | CPU profiling + 调用栈 | 功能全面、火焰图支持 | 对 Go 的支持需要 DWARF |
| **eBPF/bpftrace** | 全链路追踪、内核态 | 低开销、任意 hook 点 | 学习曲线陡峭、语法复杂 |
| **gdb/lldb** | 调试、单点分析 | 完全控制 | 无法大规模追踪 |

**最终选择**: 以 **eBPF/bpftrace** 为主，strace 作为快速验证工具。

### 2.3 eBPF 追踪架构

#### 为什么选择 eBPF？

```
传统追踪 (strace):
  应用程序调用 read()
    └─> libc read() wrapper
      └─> syscall entry (int 0x80 / sysenter)
        └─> 内核 read() 实现
          └─> strace 在这里拦截
              ❌ 但 strace 看不到应用程序的函数名（如 GetModel）

eBPF 追踪:
  应用程序调用 GetModel()
    └─> ★ uprobe 在这里拦截（看到函数名）
    └─> GetBlobsPath()
      └─> ★ uprobe 在这里拦截
    └─> os.Open()
      └─> syscall entry
        └─> ★ kprobe 在这里拦截（看到系统调用）
```

#### 分层追踪策略

**Layer 3.1: 用户态 uprobe（应用层 API）**

```c
// bpftrace 语法（原型验证）
// 追踪 Go 函数的入口
BEGIN
{
    printf("Tracing Ollama function calls... Ctrl-C to end.\n");
}

// 追踪 Go 标准库的文件操作
uprobe:/home/user/ollama:GetModel
{
    printf("GetModel() called at %s:%d\n", ustack, pid);
}

// 追踪 Go runtime 的文件打开
uprobe:/lib/x86_64-linux-gnu/libgo-*.so:Open
{
    printf("Open() called: filename=%s\n", str(arg0));
}
```

**Layer 3.2: 内核态 kprobe（系统调用）**

```c
// bpftrace: 追踪 open/openat 系统调用
tracepoint:syscalls:sys_enter_open,
tracepoint:syscalls:sys_enter_openat
{
    // 过滤：只追踪 Ollama 进程
    if (pid == $OLLAMA_PID) {
        printf("open(filename='%s', flags=%d) by PID=%d\n",
               str(args->filename), args->flags, pid);
    }
}

// bpftrace: 追踪 read 系统调用
tracepoint:syscalls:sys_enter_read
{
    if (pid == $OLLAMA_PID) {
        printf("read(fd=%d, buf=%p, count=%d)\n",
               args->fd, args->buf, args->count);
    }
}

// bpftrace: 追踪 mmap 系统调用
tracepoint:syscalls:sys_enter_mmap
{
    if (pid == $OLLAMA_PID) {
        printf("mmap(addr=%p, length=%d, prot=%d, flags=%d, fd=%d)\n",
               args->addr, args->len, args->prot, args->flags, args->fd);
    }
}
```

**Layer 3.3: 内核态 tracepoint（VFS 层）**

```c
// 追踪 VFS read 操作（比 syscall 更底层）
// 过滤特定进程和特定文件
kprobe:vfs_read
{
    $file = (struct file *)arg1;
    $data = (char *)arg2;
    // 只追踪从模型文件的读取
    if ($file->f_path.dentry->d_name.name contains "blobs" ||
        $file->f_path.dentry->d_name.name contains ".gguf") {
        printf("VFS read: dev=%d inode=%d size=%d\n",
               $file->f_inode->i_ino,
               $file->f_path.dentry->d_inode->i_size,
               args->count);
    }
}
```

### 2.4 全栈关联：将 uprobe 和 syscall 关联

单独追踪 uprobe 或 syscall 是不够的，我们需要**将两者关联**，形成从应用层到底层的完整路径。

#### 方法：时间窗口 + 文件描述符关联

```
时间线:

[PID=1234] uprobe:GetModel()                    ← T=0.0001s
[PID=1234] uprobe:GetBlobsPath()                 ← T=0.0002s
[PID=1234] syscall:open(filename="/home/.../sha256:abc")  ← T=0.0003s
       ↓ 获得 fd=5
[PID=1234] syscall:read(fd=5, count=4096)        ← T=0.0004s
[PID=1234] syscall:read(fd=5, count=4096)        ← T=0.0005s
       ↓ 持续读取...
[PID=1234] syscall:close(fd=5)                   ← T=0.0500s
```

**关联算法**:

1. 记录 `open()` 返回的 `fd`
2. 记录 `read(fd=N)` 的每一次调用
3. 通过 `fd` 关联到具体的文件路径
4. 通过时间窗口关联 `uprobe` 函数到对应的 `syscall` 序列

### 2.5 动态追踪的局限性

| 限制 | 原因 | 解决方案 |
|------|------|---------|
| 覆盖率问题 | 只能追踪实际触发的路径 | 设计多样化的测试用例 |
| 性能开销 | eBPF 也有少量开销 | 只对关键函数插桩 |
| 多进程 | fork/vfork 产生子进程 | 追踪 clone/clone3 系统调用 |
| Go 运行时 | goroutine 调度复杂 | 使用 Go 1.21+ 的 USDT probes |

---

## 3. 路径缝合：合并静态与动态

### 3.1 核心问题

静态分析给出"理论上"的调用图，动态追踪给出"实际运行"的调用序列。两者需要合并才能得到**既完整又准确**的调用树。

### 3.2 缝合算法设计

```
输入:
  - S: 静态调用图 (从源码分析得到)
  - D: 动态追踪日志 (从 eBPF 得到)
  - B: CGO 边界映射表

输出:
  - F: 缝合后的完整调用树

算法:
  1. 从动态追踪日志 D 中提取系统调用序列:
     D' = {syscall_1, syscall_2, ..., syscall_n}
     
  2. 对每个 syscall_i，通过 fd 关联到文件路径:
     F' = {(syscall_i, file_path_i, timestamp_i), ...}
     
  3. 在静态调用图 S 中，找到调用该文件路径的函数节点:
     N = {node | node.file_path matches file_path_i}
     
  4. 对每个 node，构建从顶层 API 到 node 的静态路径:
     P_static = [API_1, ..., node]
     
  5. 合并:
     F = P_static + syscall_i
     
  6. 对 CGO 边界节点，使用 B 进行语义补全:
     if node.type == "CGO":
       node.c_symbol = B[node.go_function].c_symbol
       node.cpp_function = B[node.go_function].cpp_function
```

### 3.3 差异检测

缝合后，我们需要检测静态和动态之间的**差异**，这些差异往往就是安全风险点：

| 差异类型 | 示例 | 风险说明 |
|---------|------|---------|
| **隐藏路径** | 静态分析未发现，但动态追踪捕获到了 | 动态链接库中隐藏的文件访问 |
| **丢失节点** | 静态分析有，但动态追踪未触发 | 条件分支未覆盖到的代码路径 |
| **路径偏离** | 静态和动态的调用顺序不一致 | 反映了运行时多态/函数指针 |
| **边界跨越** | CGO 边界处的语义丢失 | 需要重点补充 CGO 绑定信息 |

---

## 4. 数据安全标签体系

为了后续的风险评估，每个调用节点都需要打上安全标签。

### 4.1 标签分类

| 标签 | 含义 | 颜色 | 风险等级 |
|------|------|------|---------|
| `IO_FILE` | 文件读取操作 | 🔵 蓝 | 中 |
| `IO_NET` | 网络数据传输 | 🟠 橙 | 高 |
| `IO_MEM` | 内存映射/拷贝 | 🔵 蓝 | 低 |
| `CRYPTO` | 加密/解密操作 | 🟢 绿 | 低 |
| `IPC` | 进程间通信 | 🟠 橙 | 中 |
| `GPU` | GPU 内存操作 | 🔴 红 | 高 |
| `CGO_BOUNDARY` | 跨语言边界 | 🟣 紫 | 中 |
| `SYSCALL` | 系统调用入口 | ⚫ 黑 | 低 |

### 4.2 风险评级

```
风险 = f(数据敏感度, 操作类型, 边界跨越次数)

高风险场景:
  - 跨 CGO 边界的文件读取（Go → C++ → mmap）
  - 网络传输后的内存映射
  - GPU 显存中的模型权重读取
  
中风险场景:
  - 本地配置文件读取
  - 模板文件加载
  - Blob 缓存读取
  
低风险场景:
  - 确定性系统库调用（libc）
  - 编译器生成的代码
```

---

## 5. 工具链汇总

| 阶段 | 工具 | 语言 | 用途 |
|------|------|------|------|
| Go 静态分析 | `go/ast` + 自定义分析器 | Go/Python | AST 解析、CGO 边界识别 |
| C++ 静态分析 | `clang tooling` / `ctags` | Python | C++ AST、调用图生成 |
| 符号表分析 | `nm`, `readelf`, `objdump` | Shell | ELF 符号提取 |
| 内核追踪 | `eBPF/bpftrace` | C (embedded in bpftrace) | kprobe/uprobe 追踪 |
| 快速验证 | `strace` | Shell | 系统调用快速检查 |
| 调用图生成 | `Graphviz` / `D3.js` | Python/JS | 可视化渲染 |
| 全链路关联 | 自定义缝合器 (Stitcher) | Python | 静态+动态合并 |
