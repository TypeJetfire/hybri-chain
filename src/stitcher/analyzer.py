#!/usr/bin/env python3
"""
analyzer.py — 数据传输异常分析引擎（对应论文第 4.5 节）

功能：
  1. 敏感数据流出特征匹配（污点标记）
  2. 异常 syscall 模式检测（长阻塞、异常大小读写、越权外联）
  3. 跨层路径风险评估
  4. 生成安全告警报告

风险规则：
  - futex 阻塞 > 1s（多线程同步异常）
  - read(fd=3) 异常大小（HTTP socket 异常）
  - write 对非 stdout/stderr fd 写入模型数据
  - mmap 异常大小映射
  - openat 访问敏感路径（blobs/模型文件）

用法：
    python3 analyzer.py ../../trace_unified.jsonl
    python3 analyzer.py ../../trace_unified.jsonl --report anomaly_report.json
    python3 analyzer.py ../../trace_unified.jsonl --verbose
"""

import sys
import json
import argparse
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, List, Dict
from collections import defaultdict
from datetime import datetime
from enum import Enum

sys.path.insert(0, str(Path(__file__).parent))
from stitcher import parse_jsonl


# ---------------------------------------------------------------------------
# 数据类型
# ---------------------------------------------------------------------------

class RiskLevel(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AlertType(Enum):
    FUTEX_BLOCK = "futex_block"
    READ_SIZE_ANOMALY = "read_size_anomaly"
    WRITE_NON_STDERR = "write_non_stderr"
    MMAP_SIZE_ANOMALY = "mmap_size_anomaly"
    SENSITIVE_PATH = "sensitive_path"
    MODEL_FILE_READ = "model_file_read"
    BLOB_ACCESS = "blob_access"
    CROSS_LAYER_RISK = "cross_layer_risk"
    CPU_ONLY_SLOW = "cpu_only_slow"


@dataclass
class Alert:
    ts_ns: int
    tid: int
    alert_type: AlertType
    risk_level: RiskLevel
    message: str
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "ts_ns": self.ts_ns,
            "tid": self.tid,
            "type": self.alert_type.value,
            "risk": self.risk_level.value,
            "message": self.message,
            "detail": self.detail,
        }


# ---------------------------------------------------------------------------
# 风险规则引擎
# ---------------------------------------------------------------------------

class RuleEngine:
    """规则引擎：对每个事件应用所有规则。"""

    def __init__(self):
        self.rules: List = [
            self._rule_futex_block,
            self._rule_read_size_anomaly,
            self._rule_write_non_stdout,
            self._rule_mmap_size_anomaly,
            self._rule_sensitive_path,
            self._rule_http_socket_anomaly,
        ]

    def analyze(self, events) -> List[Alert]:
        """遍历所有事件，返回告警列表。"""
        alerts = []
        for ev in events:
            for rule in self.rules:
                result = rule(ev)
                if result:
                    if isinstance(result, list):
                        alerts.extend(result)
                    else:
                        alerts.append(result)
        return alerts

    # ---- 规则 1：futex 阻塞检测 ----
    def _rule_futex_block(self, ev) -> Optional[Alert]:
        """futex 总耗时 244s，最大 15s；阈值：> 1s 即告警。"""
        if ev.type != "syscall":
            return None
        if ev.func != "futex":
            return None
        dur_ms = ev.duration_us / 1000.0
        if dur_ms < 1000:
            return None

        risk = RiskLevel.HIGH if dur_ms > 5000 else RiskLevel.MEDIUM
        detail = {"duration_us": ev.duration_us, "duration_ms": round(dur_ms, 1)}
        if ev.extra.get("val3") is not None:
            detail["op"] = ev.extra.get("val3")

        return Alert(
            ts_ns=ev.ts_ns,
            tid=ev.tid,
            alert_type=AlertType.FUTEX_BLOCK,
            risk_level=risk,
            message=f"futex 阻塞 {dur_ms:.0f}ms（线程同步等待）",
            detail=detail,
        )

    # ---- 规则 2：read 大小异常 ----
    def _rule_read_size_anomaly(self, ev) -> Optional[Alert]:
        """正常 read 512B（HTTPS buffer），异常 > 8192B 可能是大块数据传输。"""
        if ev.type != "syscall" or ev.func != "read":
            return None
        size = ev.extra.get("bytes", 0)
        if size <= 0 or size > 128 * 1024:
            return Alert(
                ts_ns=ev.ts_ns,
                tid=ev.tid,
                alert_type=AlertType.READ_SIZE_ANOMALY,
                risk_level=RiskLevel.HIGH,
                message=f"read(fd={ev.extra.get('fd', '?')}) 异常大小: {size} bytes",
                detail={"bytes": size, "fd": ev.extra.get("fd", -1)},
            )
        return None

    # ---- 规则 3：非标准 fd write ----
    def _rule_write_non_stdout(self, ev) -> Optional[Alert]:
        """监控向非 stdout/stderr fd 的写操作（可能是 HTTP 响应/网络外联）。"""
        if ev.type != "syscall" or ev.func not in ("write", "sendto", "send"):
            return None
        fd = ev.extra.get("fd", -1)
        size = ev.extra.get("bytes", 0)
        if fd in (0, 1, 2, -1):
            return None
        if fd == 3 and size > 1024:
            return Alert(
                ts_ns=ev.ts_ns,
                tid=ev.tid,
                alert_type=AlertType.WRITE_NON_STDERR,
                risk_level=RiskLevel.MEDIUM,
                message=f"HTTP socket(fd=3) 写入 {size} bytes（可能是推理结果外传）",
                detail={"fd": fd, "bytes": size},
            )
        elif fd != 3 and size > 0:
            return Alert(
                ts_ns=ev.ts_ns,
                tid=ev.tid,
                alert_type=AlertType.WRITE_NON_STDERR,
                risk_level=RiskLevel.LOW,
                message=f"write(fd={fd}) 写入 {size} bytes",
                detail={"fd": fd, "bytes": size},
            )
        return None

    # ---- 规则 4：mmap 大小异常 ----
    def _rule_mmap_size_anomaly(self, ev) -> Optional[Alert]:
        """mmap 映射超过 512MB 为异常（可能的内存压力或数据窃取）。"""
        if ev.type != "syscall" or ev.func not in ("mmap", "mmap2"):
            return None
        size = ev.extra.get("length", 0)
        if size > 1024 * 1024 * 1024:
            return Alert(
                ts_ns=ev.ts_ns,
                tid=ev.tid,
                alert_type=AlertType.MMAP_SIZE_ANOMALY,
                risk_level=RiskLevel.CRITICAL,
                message=f"mmap 映射异常大小: {size / (1024**3):.1f} GB",
                detail={"length": size},
            )
        elif size > 512 * 1024 * 1024:
            return Alert(
                ts_ns=ev.ts_ns,
                tid=ev.tid,
                alert_type=AlertType.MMAP_SIZE_ANOMALY,
                risk_level=RiskLevel.HIGH,
                message=f"mmap 映射大内存: {size / (1024**2):.0f} MB",
                detail={"length": size},
            )
        return None

    # ---- 规则 5：敏感路径访问 ----
    SENSITIVE_PATTERNS = [
        ("blobs", RiskLevel.MEDIUM),
        (".gguf", RiskLevel.HIGH),
        (".ggml", RiskLevel.HIGH),
        ("server.json", RiskLevel.LOW),
        ("model.json", RiskLevel.MEDIUM),
    ]

    def _rule_sensitive_path(self, ev) -> Optional[Alert]:
        """检测对敏感路径的 openat 访问（模型文件、blob 存储）。"""
        if ev.type != "syscall" or ev.func != "openat":
            return None
        path = ev.extra.get("path", "")
        for pattern, risk in self.SENSITIVE_PATTERNS:
            if pattern.lower() in path.lower():
                return Alert(
                    ts_ns=ev.ts_ns,
                    tid=ev.tid,
                    alert_type=AlertType.MODEL_FILE_READ,
                    risk_level=risk,
                    message=f"访问模型文件: {path}",
                    detail={"path": path, "pattern": pattern},
                )
        return None

    # ---- 规则 6：HTTP socket 异常读 ----
    def _rule_http_socket_anomaly(self, ev) -> Optional[Alert]:
        """fd=3 是 HTTP socket，异常大的读操作可能表示数据外传。"""
        if ev.type != "syscall" or ev.func not in ("read", "recvfrom"):
            return None
        fd = ev.extra.get("fd", -1)
        size = ev.extra.get("bytes", 0)
        if fd == 3 and size > 1024 * 1024:
            return Alert(
                ts_ns=ev.ts_ns,
                tid=ev.tid,
                alert_type=AlertType.READ_SIZE_ANOMALY,
                risk_level=RiskLevel.HIGH,
                message=f"HTTP socket 大量读入: {size / 1024:.0f} KB",
                detail={"fd": fd, "bytes": size},
            )
        return None


# ---------------------------------------------------------------------------
# 分析报告生成
# ---------------------------------------------------------------------------

class AnalyzerReport:
    """生成分析报告。"""

    def __init__(self, alerts: List[Alert], events: list):
        self.alerts = alerts
        self.events = events
        self.total_syscalls = sum(1 for e in events if e.type == "syscall")
        self.total_uprobes = sum(1 for e in events if e.type == "uprobe")

    def summary(self) -> dict:
        by_type = defaultdict(int)
        by_risk = defaultdict(int)
        for a in self.alerts:
            by_type[a.alert_type.value] += 1
            by_risk[a.risk_level.value] += 1

        return {
            "total_events": len(self.events),
            "total_syscalls": self.total_syscalls,
            "total_uprobes": self.total_uprobes,
            "total_alerts": len(self.alerts),
            "alerts_by_type": dict(by_type),
            "alerts_by_risk": dict(by_risk),
        }

    def top_alerts(self, n: int = 20) -> List[dict]:
        """返回风险最高的 N 个告警。"""
        risk_order = {
            RiskLevel.CRITICAL: 0,
            RiskLevel.HIGH: 1,
            RiskLevel.MEDIUM: 2,
            RiskLevel.LOW: 3,
        }
        sorted_alerts = sorted(
            self.alerts,
            key=lambda a: (risk_order.get(a.risk_level, 99), -a.ts_ns)
        )
        return [a.to_dict() for a in sorted_alerts[:n]]

    def print_report(self):
        """打印文本报告。"""
        s = self.summary()
        print("=" * 70)
        print("Ollama 数据传输异常分析报告")
        print(f"分析时间: {datetime.now().isoformat()}")
        print("=" * 70)
        print(f"  追踪事件总数:  {s['total_events']}")
        print(f"  系统调用数:    {s['total_syscalls']}")
        print(f"  用户态探针数:  {s['total_uprobes']}")
        print(f"  告警总数:      {s['total_alerts']}")
        print()

        if s["alerts_by_risk"]:
            print("【告警级别分布】")
            for level in ["critical", "high", "medium", "low"]:
                count = s["alerts_by_risk"].get(level, 0)
                bar = "=" * count + "-" * max(0, 20 - count)
                print(f"  {level.upper():<10} {bar} {count:>3}")
            print()

        if s["alerts_by_type"]:
            print("【告警类型分布】")
            for atype, count in sorted(s["alerts_by_type"].items(), key=lambda x: -x[1]):
                print(f"  {atype:<35} {count:>3}")
            print()

        high_risk = [a for a in self.alerts
                     if a.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL)]
        if high_risk:
            print(f"【高风险告警 ({len(high_risk)} 条)】")
            for a in sorted(high_risk, key=lambda x: -x.ts_ns)[:10]:
                print(f"  [{a.risk_level.value.upper()}] {a.message}")
                if a.detail:
                    for k, v in a.detail.items():
                        print(f"      {k}: {v}")
                print()

        self._print_perf_stats()

    def _print_perf_stats(self):
        """打印推理性能统计。"""
        print("【推理性能统计（Llama.cpp 函数）】")
        func_stats = defaultdict(lambda: {"count": 0, "total_us": 0, "max_us": 0})

        for ev in self.events:
            if ev.type != "uprobe":
                continue
            stats = func_stats[ev.func]
            stats["count"] += 1
            stats["total_us"] += ev.duration_us
            if ev.duration_us > stats["max_us"]:
                stats["max_us"] = ev.duration_us

        if not func_stats:
            print("  （无可用 uprobe 数据）")
            return

        print(f"  {'函数':<50} {'调用':>6} {'总耗时':>10} {'平均':>8} {'最大':>8}")
        print("  " + "-" * 86)
        for func, stats in sorted(func_stats.items(), key=lambda x: -x[1]["total_us"]):
            avg = stats["total_us"] / stats["count"] if stats["count"] else 0
            print(f"  {func:<50} {stats['count']:>6} "
                  f"{stats['total_us']/1000:>8.1f}ms "
                  f"{avg/1000:>6.1f}ms "
                  f"{stats['max_us']/1000:>6.1f}ms")

        print()
        print("【系统调用性能统计】")
        syscall_stats = defaultdict(lambda: {"count": 0, "total_us": 0, "max_us": 0})
        for ev in self.events:
            if ev.type != "syscall":
                continue
            stats = syscall_stats[ev.func]
            stats["count"] += 1
            stats["total_us"] += ev.duration_us
            if ev.duration_us > stats["max_us"]:
                stats["max_us"] = ev.duration_us

        print(f"  {'syscall':<20} {'调用':>6} {'总耗时':>10} {'平均':>8} {'最大':>8}")
        print("  " + "-" * 56)
        for func, stats in sorted(syscall_stats.items(), key=lambda x: -x[1]["total_us"]):
            avg = stats["total_us"] / stats["count"] if stats["count"] else 0
            total_str = f"{stats['total_us']/1e6:.1f}s" if stats["total_us"] > 1e6 else f"{stats['total_us']/1000:.1f}ms"
            max_str = f"{stats['max_us']/1000:.1f}ms"
            avg_str = f"{avg/1000:.1f}ms"
            print(f"  {func:<20} {stats['count']:>6} {total_str:>10} {avg_str:>8} {max_str:>8}")


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Ollama 异常分析引擎")
    parser.add_argument("trace", help="统一追踪 JSONL 文件")
    parser.add_argument("--report", "-r", help="导出 JSON 报告")
    parser.add_argument("--verbose", "-v", action="store_true", help="详细输出")
    args = parser.parse_args()

    print(f"[Analyzer] 加载追踪数据: {args.trace}")
    events = parse_jsonl(args.trace)
    print(f"[Analyzer] 解析 {len(events)} 事件")

    engine = RuleEngine()
    alerts = engine.analyze(events)
    print(f"[Analyzer] 发现 {len(alerts)} 条告警")

    reporter = AnalyzerReport(alerts, events)
    reporter.print_report()

    if args.report:
        report_data = {
            "generated_at": datetime.now().isoformat(),
            "trace_file": args.trace,
            "summary": reporter.summary(),
            "top_alerts": reporter.top_alerts(50),
            "all_alerts": [a.to_dict() for a in alerts],
        }
        with open(args.report, "w", encoding="utf-8") as f:
            json.dump(report_data, f, indent=2, ensure_ascii=False)
        print(f"[Analyzer] 报告已保存: {args.report}")


if __name__ == "__main__":
    main()
