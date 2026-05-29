#!/bin/bash
# 方案 A：纯配置展示脚本（无需安装 WireGuard）
# 展示策略引擎工作原理和配置生成逻辑

set -e

OUTPUT_DIR="demo_output"
NODES_FILE="tests/test_nodes.yml"
POLICIES_FILE="tests/policies.yml"

echo "=========================================="
echo "方案 A：纯配置展示（无需 WireGuard）"
echo "=========================================="
echo ""

# 清理旧的输出
rm -rf "$OUTPUT_DIR"
mkdir -p "$OUTPUT_DIR"

echo "【步骤 1】展示输入：节点属性"
echo "----------------------------------------"
echo "节点文件: $NODES_FILE"
echo ""
cat "$NODES_FILE" | head -30
echo "..."
echo ""

echo "【步骤 2】展示输入：安全策略"
echo "----------------------------------------"
echo "策略文件: $POLICIES_FILE"
echo ""
cat "$POLICIES_FILE"
echo ""

echo "【步骤 3】运行策略引擎生成配置"
echo "----------------------------------------"
python3 main.py "$NODES_FILE" "$POLICIES_FILE" -o "$OUTPUT_DIR"
echo ""

echo "【步骤 4】展示访问矩阵（ABAC 评估结果）"
echo "----------------------------------------"
echo "文件: $OUTPUT_DIR/input.json"
echo ""
if [ -f "$OUTPUT_DIR/input.json" ]; then
    python3 -m json.tool "$OUTPUT_DIR/input.json" 2>/dev/null || cat "$OUTPUT_DIR/input.json"
else
    echo "⚠️  访问矩阵文件不存在"
fi
echo ""

echo "【步骤 5】展示允许的连接示例"
echo "----------------------------------------"
echo "查找 connectivity: true 的连接..."
if [ -f "$OUTPUT_DIR/input.json" ]; then
    echo ""
    python3 << 'PYEOF'
import json
with open("demo_output/input.json", "r") as f:
    data = json.load(f)
    
print("允许的连接:")
for rule in data.get("access_matrix", []):
    if rule.get("connectivity", False):
        print(f"  ✅ {rule['source']} → {rule['destination']}")
        l4_rules = rule.get("l4_rules", [])
        if l4_rules:
            print("     允许的协议和端口:")
            for l4 in l4_rules:
                proto = l4.get("proto", "")
                ports = l4.get("ports", [])
                action = l4.get("action", "accept")
                if ports:
                    print(f"       - {proto.upper()} 端口: {ports} ({action})")
                else:
                    print(f"       - {proto.upper()} ({action})")
PYEOF
fi
echo ""

echo "【步骤 6】展示拒绝的连接示例"
echo "----------------------------------------"
if [ -f "$OUTPUT_DIR/input.json" ]; then
    python3 << 'PYEOF'
import json
with open("demo_output/input.json", "r") as f:
    data = json.load(f)
    
print("拒绝的连接:")
for rule in data.get("access_matrix", []):
    if not rule.get("connectivity", False):
        print(f"  ❌ {rule['source']} → {rule['destination']}")
        print("     (访问矩阵中 connectivity: false)")
PYEOF
fi
echo ""

echo "【步骤 7】展示生成的 WireGuard 配置"
echo "----------------------------------------"
for conf_file in "$OUTPUT_DIR"/*.conf; do
    if [ -f "$conf_file" ]; then
        node_name=$(basename "$conf_file" .conf)
        echo "节点: $node_name"
        echo "文件: $conf_file"
        echo ""
        cat "$conf_file"
        echo ""
        echo "---"
        echo ""
    fi
done

echo "【步骤 8】展示生成的 nftables 防火墙规则"
echo "----------------------------------------"
for nft_file in "$OUTPUT_DIR"/*.nft; do
    if [ -f "$nft_file" ]; then
        node_name=$(basename "$nft_file" .nft)
        echo "节点: $node_name"
        echo "文件: $nft_file"
        echo ""
        cat "$nft_file"
        echo ""
        echo "---"
        echo ""
    fi
done

echo "【步骤 9】对比分析：允许 vs 拒绝的连接"
echo "----------------------------------------"
if [ -f "$OUTPUT_DIR/input.json" ]; then
    python3 << 'PYEOF'
import json
import os

with open("demo_output/input.json", "r") as f:
    data = json.load(f)

nodes = data.get("nodes", {})
access_matrix = data.get("access_matrix", [])

print("连接对比分析:")
print("")

# 找出允许的连接
allowed = [r for r in access_matrix if r.get("connectivity", False)]
# 找出拒绝的连接
denied = [r for r in access_matrix if not r.get("connectivity", False)]

if allowed:
    print("✅ 允许的连接:")
    for rule in allowed:
        src = rule["source"]
        dst = rule["destination"]
        src_ip = nodes.get(src, {}).get("internal_ip", "?")
        dst_ip = nodes.get(dst, {}).get("internal_ip", "?")
        print(f"   {src} ({src_ip}) → {dst} ({dst_ip})")
        
        # 检查 WireGuard 配置
        src_conf = f"demo_output/{src}.conf"
        if os.path.exists(src_conf):
            with open(src_conf, "r") as f:
                if dst_ip in f.read():
                    print(f"     ✓ WireGuard 配置中包含到 {dst} 的 Peer")
        
        # 检查防火墙规则
        dst_nft = f"demo_output/{dst}.nft"
        if os.path.exists(dst_nft):
            with open(dst_nft, "r") as f:
                content = f.read()
                if src_ip in content:
                    print(f"     ✓ {dst} 的防火墙规则允许来自 {src_ip} 的流量")

print("")

if denied:
    print("❌ 拒绝的连接:")
    for rule in denied:
        src = rule["source"]
        dst = rule["destination"]
        src_ip = nodes.get(src, {}).get("internal_ip", "?")
        dst_ip = nodes.get(dst, {}).get("internal_ip", "?")
        print(f"   {src} ({src_ip}) → {dst} ({dst_ip})")
        
        # 检查 WireGuard 配置
        src_conf = f"demo_output/{src}.conf"
        if os.path.exists(src_conf):
            with open(src_conf, "r") as f:
                content = f.read()
                if dst_ip not in content or f"Peer: {dst}" not in content:
                    print(f"     ✗ WireGuard 配置中不包含到 {dst} 的 Peer（或没有 Endpoint）")
        
        # 检查防火墙规则
        dst_nft = f"demo_output/{dst}.nft"
        if os.path.exists(dst_nft):
            with open(dst_nft, "r") as f:
                content = f.read()
                if src_ip not in content or "accept" not in content.lower():
                    print(f"     ✗ {dst} 的防火墙规则中没有允许来自 {src_ip} 的流量（默认拒绝）")
PYEOF
fi

echo ""
echo "=========================================="
echo "演示完成！"
echo "=========================================="
echo ""
echo "📝 说明："
echo "  - 本演示只需要 Python 环境，无需安装 WireGuard"
echo "  - 生成的配置文件位于: $OUTPUT_DIR/"
echo "  - 这些配置文件可以部署到实际主机上使用"
echo "  - 实际部署时需要："
echo "    1. 安装 WireGuard: sudo apt install wireguard"
echo "    2. 复制 .conf 文件到 /etc/wireguard/"
echo "    3. 应用 nftables 规则: sudo nft -f *.nft"
echo ""

