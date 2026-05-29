# TrivialTier Policy Generator

ABAC Policy Engine for generating WireGuard configs and nftables policies from node attributes and security policies.

## Features

- **ABAC Policy Engine**: Evaluates Attribute-Based Access Control policies with support for:
  - Subject/Object constraints with `all` (AND), `any` (OR), `none` (NOT) logic
  - Nested attribute paths (e.g., `system.os`, `network.zone`)
  - Multiple operators: `==`, `!=`, `>`, `>=`, `<`, `<=`, `in`, `not in`
  - Environment variable constraints
  - L4 enforcement rules (TCP/UDP ports, ICMP)

- **WireGuard Configuration Generation**: 
  - Automatic peer configuration based on access matrix
  - Bidirectional connection support
  - Private key integration

- **nftables Policy Generation**:
  - Firewall rules based on L4 enforcement
  - Automatic table flushing to avoid conflicts
  - Default deny with explicit allow rules

## Usage

### Quick Start

```bash
# Complete pipeline: ABAC evaluation -> WireGuard & nftables generation
python3 main.py nodes.yml policies.yml -o output

# With private keys
python3 main.py nodes.yml policies.yml -o output --private-keys private_keys.json
```

### Step by Step

```bash
# Step 1: Evaluate policies and generate access matrix
python3 abac_engine.py nodes.yml policies.yml input.json

# Step 2: Generate WireGuard and nftables configs
python3 generator.py input.json output [private_keys.json]
```

## Input Format

### Nodes File (YAML/JSON)

```yaml
nodes:
  - id: "node_a"
    identity: "public_key_A"
    ipv4: "10.0.0.1"
    endpoint: "1.2.3.4:51820"
    attributes:
      system:
        os: "linux"
        patch_level: 20251201
      identity:
        role: "developer"
      network:
        zone: "trusted"
```

### Policies File (YAML/JSON)

```yaml
policies:
  - id: "policy-001"
    action: ALLOW
    subject:
      all:
        - attribute: "system.os"
          operator: "=="
          value: "linux"
        - attribute: "system.patch_level"
          operator: ">="
          value: 20251101
    object:
      any:
        - attribute: "identity.role"
          operator: "=="
          value: "storage"
    environment:
      - variable: "global.threat_level"
        operator: "<"
        value: 3
    enforcement:
      layer4:
        rules:
          - { proto: "tcp", dport: 22, action: "ACCEPT" }
          - { proto: "icmp", action: "ACCEPT" }
```

## Output

The tool generates:

- `input.json`: Access matrix resolved from ABAC policies
- `*.conf`: WireGuard configuration files for each node
- `*.nft`: nftables policy files for each node

## Examples

See `tests/test_nodes.yml` and `tests/policies.yml` for example configurations.

## Demo: Configuration Generation Only (No WireGuard Required)

**方案 A：纯配置展示** - 适合展示策略引擎工作原理，**无需安装 WireGuard**

本工具只需要 Python 环境即可生成配置文件，不需要安装 WireGuard 或 nftables。

### Quick Demo

```bash
# 运行完整演示脚本（展示输入、处理、输出）
./demo_config_only.sh
```

演示脚本会展示：
1. **输入**：节点属性和安全策略
2. **处理**：ABAC 策略评估过程
3. **输出**：生成的 WireGuard 和 nftables 配置
4. **对比**：允许的连接 vs 拒绝的连接

### What You Need

- ✅ Python 3.x（已安装）
- ✅ 本项目的 Python 脚本
- ❌ **不需要** WireGuard（仅生成配置，不启动服务）
- ❌ **不需要** nftables（仅生成规则文件，不应用规则）

### When Do You Need WireGuard?

只有在**实际部署**到主机上时才需要安装 WireGuard：

```bash
# 在实际主机上部署时：
sudo apt install wireguard
sudo cp output/node_a.conf /etc/wireguard/wg0.conf
sudo wg-quick up wg0
sudo nft -f output/node_a.nft
```

对于**配置展示和演示**，完全不需要安装 WireGuard！

