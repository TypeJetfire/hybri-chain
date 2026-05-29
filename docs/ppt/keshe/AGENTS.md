# TrivialTier Policy Generator

## Input

```
{
  "version": "1.0",
  "description": "SD-WAN Access Matrix Resolved IR",
  "nodes": {
    "node_a": {
      "internal_ip": "10.0.0.1",
      "public_key": "7b5R...v1W0=",
      "listen_port": 51820,
      "endpoint": "1.2.3.4:51820"
    },
    "node_b": {
      "internal_ip": "10.0.0.2",
      "public_key": "9xY2...p8Z1=",
      "listen_port": 51820,
      "endpoint": "5.6.7.8:51820"
    }
  },
  "access_matrix": [
    {
      "source": "node_a",
      "destination": "node_b",
      "connectivity": true,
      "l4_rules": [
        { "proto": "tcp", "ports": [22, 80, 443], "action": "accept" },
        { "proto": "udp", "ports": [53], "action": "accept" },
        { "proto": "icmp", "action": "accept" }
      ]
    },
    {
      "source": "node_b",
      "destination": "node_a",
      "connectivity": false,
      "l4_rules": [
      ]
    }
  ]
}
```

According to the security plicies ( ACL ) generate the WireGuard configs.

Output: WireGuard configs & nftables polices for each nodes.
