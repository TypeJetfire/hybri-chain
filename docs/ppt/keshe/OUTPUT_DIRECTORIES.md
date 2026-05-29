# 输出目录说明

本项目中有多个输出目录，它们分别对应不同的测试场景和生成阶段：

## 目录概览

### 1. `output/` - 简单测试用例输出

**用途**：使用简单的测试数据（`nodes.json` 和 `policies.json`）生成的配置

**内容**：
- `node_a.conf` / `node_a.nft` - 节点 A 的 WireGuard 和 nftables 配置
- `node_b.conf` / `node_b.nft` - 节点 B 的 WireGuard 和 nftables 配置

**特点**：
- 只有 2 个节点（node_a, node_b）
- 简单的测试场景
- 不包含 `input.json`（可能只运行了 `generator.py`）

**生成方式**：
```bash
# 可能的使用方式
python3 generator.py example_input.json output/
```

---

### 2. `output_from_abac/` - 从 ABAC 引擎生成的配置

**用途**：使用 ABAC 引擎评估策略后，生成的 WireGuard 和 nftables 配置

**内容**：
- `laptop_li.conf` / `laptop_li.nft`
- `nas_core.conf` / `nas_core.nft`
- `scu-lab-server.conf` / `scu-lab-server.nft`

**特点**：
- 3 个节点（laptop_li, nas_core, scu-lab-server）
- 使用 `tests/test_nodes.yml` 和 `tests/policies.yml` 作为输入
- **不包含 `input.json`**（可能只运行了第二步 `generator.py`）

**生成方式**：
```bash
# 方式 1：分步执行
python3 abac_engine.py tests/test_nodes.yml tests/policies.yml input.json
python3 generator.py input.json output_from_abac/

# 方式 2：使用 main.py 但指定不同的输出目录
python3 main.py tests/test_nodes.yml tests/policies.yml -o output_from_abac
```

---

### 3. `output_complete/` - 完整流程输出

**用途**：使用完整流程（ABAC 评估 + 配置生成）生成的完整输出

**内容**：
- `input.json` - **包含访问矩阵**（ABAC 评估结果）
- `laptop_li.conf` / `laptop_li.nft`
- `nas_core.conf` / `nas_core.nft`
- `scu-lab-server.conf` / `scu-lab-server.nft`

**特点**：
- 3 个节点（laptop_li, nas_core, scu-lab-server）
- **包含 `input.json`**（访问矩阵）
- 完整的配置生成流程

**生成方式**：
```bash
# 使用 main.py 完整流程
python3 main.py tests/test_nodes.yml tests/policies.yml -o output_complete
```

---

### 4. `final_output/` - 最终输出

**用途**：最终版本的配置输出

**内容**：
- `input.json` - 访问矩阵
- `laptop_li.conf` / `laptop_li.nft`
- `nas_core.conf` / `nas_core.nft`
- `scu-lab-server.conf` / `scu-lab-server.nft`

**特点**：
- 与 `output_complete/` 内容相同
- 可能是最终确认的版本
- 包含完整的配置和访问矩阵

**生成方式**：
```bash
# 与 output_complete 相同
python3 main.py tests/test_nodes.yml tests/policies.yml -o final_output
```

---

## 对比总结

| 目录 | 节点数量 | 包含 input.json | 用途 |
|------|---------|----------------|------|
| `output/` | 2 (node_a, node_b) | ❌ | 简单测试 |
| `output_from_abac/` | 3 (laptop_li, nas_core, scu-lab-server) | ❌ | ABAC 评估后的配置（可能只运行了第二步） |
| `output_complete/` | 3 (laptop_li, nas_core, scu-lab-server) | ✅ | 完整流程输出 |
| `final_output/` | 3 (laptop_li, nas_core, scu-lab-server) | ✅ | 最终版本 |

## 推荐使用

- **开发测试**：使用 `output/` 或 `output_from_abac/`
- **完整验证**：使用 `output_complete/` 或 `final_output/`
- **生产部署**：使用 `final_output/`（最终确认版本）

## 文件说明

### `input.json` 的作用

`input.json` 是 ABAC 引擎生成的中间文件，包含：
- 节点网络信息（IP、公钥、端点）
- **访问矩阵**（access_matrix）：哪些节点可以连接，允许哪些端口

如果没有 `input.json`，说明可能：
1. 只运行了 `generator.py`（第二步）
2. 或者 `input.json` 在其他位置

### 配置文件说明

- `*.conf` - WireGuard 配置文件，用于建立 VPN 连接
- `*.nft` - nftables 防火墙规则，用于 L4 层访问控制

