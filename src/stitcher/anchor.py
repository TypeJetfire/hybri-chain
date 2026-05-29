"""
anchor.py — 锚点识别：动态轨迹事件 ↔ 静态调用图节点匹配。

核心思路：
  在动态追踪事件的函数名（或栈帧）与静态调用图节点之间建立"命中"关系。
  命中事件称为"锚点"，它们是缝合算法的关键连接点。
"""

import re
from typing import Dict, Set, List, Tuple, Optional
from dataclasses import dataclass


@dataclass
class Anchor:
    """一个锚点：动态事件在静态图中的命中信息。"""
    func: str           # 动态事件中的函数名
    matched_node: str  # 静态图中匹配的节点名（可能规范化后不同）
    layer: str         # 节点所在层
    anchor_type: str   # "exact" | "cgo_wrap" | "mangled" | "partial"


class AnchorMatcher:
    """
    将动态事件中的函数名与静态调用图节点进行匹配。

    匹配策略（优先级递减）：
    1. 精确匹配（区分大小写）
    2. CGO Wrapper 等价映射（_cgo_Cfunc_X → X）
    3. 去除 CGO 哈希前缀后匹配（_cgoexp_8hex_funcname → funcname）
    4. demangle C++ 名称后匹配（_Z21funcname → funcname）
    5. 栈帧匹配：检查动态事件的调用栈中是否有静态节点
    """

    # CGO Wrapper 到真实函数的等价映射（动态捕获的函数名 → 静态图节点）
    # 动态 bpftrace uprobe 捕获的是 CGO wrapper，但这些函数等价于 llama.cpp 原生函数
    CGO_EQUIV = {
        "_cgo_8aa400f2462b_Cfunc_llama_decode":              "llama_decode",
        "_cgo_8aa400f2462b_Cfunc_llama_batch_init":          "llama_batch_init",
        "_cgo_8aa400f2462b_Cfunc_llama_batch_add":           "llama_batch_add",
        "_cgo_8aa400f2462b_Cfunc_llama_sampler_sample":       "llama_sampler_sample",
        "_cgo_8aa400f2462b_Cfunc_common_sampler_csample":     "common_sampler_csample",
        "_cgo_8aa400f2462b_Cfunc_common_sampler_caccept":     "common_sampler_caccept",
        "_cgo_8aa400f2462b_Cfunc_llama_model_load_from_file": "llama_model_load_from_file",
        "_cgo_8aa400f2462b_Cfunc_llama_tokenize":             "llama_tokenize",
        "_cgo_8aa400f2462b_Cfunc_llama_token_to_piece":       "llama_token_to_piece",
    }

    def __init__(self, call_graph):
        self.cg = call_graph
        # 精确匹配索引
        self.exact_index: Set[str] = set(call_graph.nodes.keys())
        # 正则：_cgoexp_HASH_funcname 或 _cgo_HASH_funcname
        self.cgo_pattern = re.compile(r'^(_cgoexp?_[0-9a-f]+_)(.+)$')
        # 正则：C++ mangled name
        self.cpp_pattern = re.compile(r'^(_Z\d+.+)$')

        # 规范化函数名缓存
        self._normalize_cache: Dict[str, str] = {}

    def normalize(self, name: str) -> str:
        """
        将各种格式的函数名规范化为统一形式，便于比较。
        输入: "_cgoexp_8aa400f2462b_llamarunner_llama_Execute"
        输出: "llamarunner_llama_Execute"
        """
        if name in self._normalize_cache:
            return self._normalize_cache[name]

        result = name

        # 去除 CGO 前缀
        m = self.cgo_pattern.match(name)
        if m:
            result = m.group(2)
            # 再 demangle
            result = self._demangle(result)

        # demangle C++ 名称
        result = self._demangle(result)

        self._normalize_cache[name] = result
        return result

    def _demangle(self, name: str) -> str:
        """简单 C++ name demangling（处理常见 llama.cpp 符号）。"""
        if name.startswith("_Z"):
            # 尝试用 c++filt（系统工具）
            import subprocess
            try:
                p = subprocess.run(["c++filt", name], capture_output=True, text=True, timeout=1)
                if p.returncode == 0:
                    return p.stdout.strip()
            except Exception:
                pass
        return name

    def match(self, func_name: str) -> Optional[Anchor]:
        """
        尝试将一个动态事件函数名匹配到静态调用图节点。
        返回 Anchor 或 None。
        """
        # 策略0：CGO Wrapper 等价映射
        if func_name in self.CGO_EQUIV:
            real = self.CGO_EQUIV[func_name]
            if real in self.exact_index:
                return Anchor(
                    func=func_name,
                    matched_node=real,
                    layer=self.cg.get_layer(real),
                    anchor_type="cgo_equiv",
                )

        # 策略1：精确匹配
        if func_name in self.exact_index:
            return Anchor(
                func=func_name,
                matched_node=func_name,
                layer=self.cg.get_layer(func_name),
                anchor_type="exact",
            )

        # 策略2：CGO 前缀 + demangle 后匹配
        norm = self.normalize(func_name)
        if norm != func_name and norm in self.exact_index:
            return Anchor(
                func=func_name,
                matched_node=norm,
                layer=self.cg.get_layer(norm),
                anchor_type="cgo_wrap",
            )

        # 策略3：去除 CGO 内部的 Cfunc_ 前缀再匹配
        norm_stripped = norm
        if norm_stripped.startswith("Cfunc_"):
            norm_stripped = norm_stripped[6:]
        if norm_stripped in self.exact_index:
            return Anchor(
                func=func_name,
                matched_node=norm_stripped,
                layer=self.cg.get_layer(norm_stripped),
                anchor_type="cgo_wrap",
            )

        # 策略4：在节点名中搜索 func_name 的子串（宽松匹配）
        for node_name in self.exact_index:
            if func_name in node_name or node_name in func_name:
                if len(func_name) >= 4 and len(node_name) >= 4:
                    return Anchor(
                        func=func_name,
                        matched_node=node_name,
                        layer=self.cg.get_layer(node_name),
                        anchor_type="partial",
                    )

        return None

    def match_stack(self, stack: List[str]) -> List[Anchor]:
        """
        将动态事件的完整调用栈与静态图匹配。
        从栈顶（leaf）到栈底（root）逐帧匹配。
        """
        anchors = []
        for frame in stack:
            # 提取函数名（去掉 +偏移 量）
            clean = frame.split("+")[0].strip()
            anchor = self.match(clean)
            if anchor:
                anchors.append(anchor)
        return anchors

    def build_anchor_index(self, events) -> Dict[str, List]:
        """
        遍历所有动态事件，建立锚点索引。
        返回: { matched_node: [event1, event2, ...] }
        """
        index = {}
        for ev in events:
            if ev.type != "uprobe":
                continue
            frames = ev.stack if isinstance(ev.stack, list) else []
            anchors = self.match_stack(frames)
            for anchor in anchors:
                node = anchor.matched_node
                if node not in index:
                    index[node] = []
                index[node].append(ev)
        return index
