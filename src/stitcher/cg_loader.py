"""
cg_loader.py — 加载静态调用图 JSON，提供节点/边查询接口。
"""

import json
from dataclasses import dataclass, field
from typing import Dict, Set, List


@dataclass
class CGNode:
    name: str
    layer: str
    addr: str = ""
    description: str = ""


@dataclass
class CGEdge:
    from_node: str
    to_node: str
    type: str = "static"       # "static" | "dynamic"
    confidence: str = "inferred" # "confirmed" | "inferred" | "partial" | "conflicting"


class CallGraph:
    def __init__(self, path: str = "call_graph_static.json"):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.version = data.get("version", "1.0")
        self.binary = data.get("binary", "unknown")
        self.layers = data.get("layers", {})

        self.nodes: Dict[str, CGNode] = {}
        for name, info in data.get("nodes", {}).items():
            self.nodes[name] = CGNode(
                name=name,
                layer=info.get("layer", "unknown"),
                addr=info.get("addr", ""),
                description=info.get("description", ""),
            )

        self.edges_out: Dict[str, Set[str]] = {}  # caller -> set of callees
        self.edges_in: Dict[str, Set[str]] = {}   # callee -> set of callers
        self.edges: List[CGEdge] = []

        for e in data.get("edges", []):
            edge = CGEdge(
                from_node=e["from"],
                to_node=e["to"],
                type=e.get("type", "static"),
                confidence=e.get("confidence", "inferred"),
            )
            self.edges.append(edge)

            if edge.from_node not in self.edges_out:
                self.edges_out[edge.from_node] = set()
            self.edges_out[edge.from_node].add(edge.to_node)

            if edge.to_node not in self.edges_in:
                self.edges_in[edge.to_node] = set()
            self.edges_in[edge.to_node].add(edge.from_node)

    def get_callees(self, func: str) -> Set[str]:
        """获取函数的所有直接调用者（从静态图中）。"""
        return self.edges_out.get(func, set())

    def get_callers(self, func: str) -> Set[str]:
        """获取函数的所有直接调用者。"""
        return self.edges_in.get(func, set())

    def get_layer(self, func: str) -> str:
        """获取函数所在层。"""
        if func in self.nodes:
            return self.nodes[func].layer
        return "unknown"

    def functions_in_layer(self, layer: str) -> Set[str]:
        """获取指定层的所有函数。"""
        return {name for name, node in self.nodes.items() if node.layer == layer}

    def summary(self):
        layer_counts = {}
        for node in self.nodes.values():
            layer_counts[node.layer] = layer_counts.get(node.layer, 0) + 1
        print(f"CallGraph: {len(self.nodes)} nodes, {len(self.edges)} edges")
        for layer, count in sorted(layer_counts.items(), key=lambda x: -x[1]):
            print(f"  {layer:<25} {count:>5}")
