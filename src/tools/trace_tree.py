#!/usr/bin/env python3
"""
Parse trace_output.txt → complete call tree.

Output format per session:
  [Phase 1] Runner accept
  [Phase 2] Main process connects to runner
  [Phase 3] Model loading (llama_model_load_from_file)
  [Phase 4] Inference iterations (ggml → llama_decode → sampler chain)
"""

TRACE = str(Path(__file__).resolve().parent.parent.parent / 'trace_output.txt')

def parse_trace(path):
    events = []
    with open(path) as f:
        for lineno, line in enumerate(f, 1):
            line = line.rstrip()
            if not line or line.startswith("Tracing") or line.startswith("Stop") or line.startswith("---") or line.startswith("[TRACE"):
                continue

            if line.startswith("@RUNNER@"):
                # @RUNNER@ accept ts tid fd=X dur=Y
                parts = line.split()
                # 0=RUNNER, 1=accept, 2=ts, 3=tid, 4=fd=X, 5=dur=Y
                if len(parts) >= 6:
                    ts = int(parts[2])
                    tid = int(parts[3])
                    fd_val = int(parts[4].split("=")[1])
                    dur = int(parts[5].split("=")[1])
                    events.append(("RUNNER", "accept", ts, tid, dur, fd_val))

            elif line.startswith("@GOCALL@"):
                # @GOCALL@ connect_runner ts tid port=X
                parts = line.split()
                if len(parts) >= 5:
                    ts = int(parts[2])
                    tid = int(parts[3])
                    port = parts[4].split("=")[1]
                    events.append(("GOCALL", "connect_runner", ts, tid, 0, port))

            elif line.startswith("@UPROBE@"):
                # @UPROBE@ func ts tid dur
                parts = line.split()
                if len(parts) >= 5:
                    func = parts[1]
                    ts = int(parts[2])
                    tid = int(parts[3])
                    dur = int(parts[4])
                    events.append(("UPROBE", func, ts, tid, dur, None))

            elif line.startswith("@SYSCALL@"):
                # @SYSCALL@ func ts tid bytes=X dur=Y
                # or @SYSCALL@ func ts tid dur=Y
                parts = line.split()
                if len(parts) >= 5:
                    func = parts[1]
                    ts = int(parts[2])
                    tid = int(parts[3])
                    dur = 0
                    bytes_val = 0
                    for p in parts[4:]:
                        if p.startswith("bytes="):
                            bytes_val = int(p.split("=")[1])
                        elif p.startswith("dur="):
                            dur = int(p.split("=")[1])
                    events.append(("SYSCALL", func, ts, tid, dur, bytes_val))

    return events


def split_sessions(events):
    """Split events into sessions by RUNNER accept boundary."""
    events.sort(key=lambda e: e[2])  # sort by timestamp
    sessions = []
    current = []
    for ev in events:
        if ev[0] == "RUNNER" and ev[1] == "accept":
            if current:
                sessions.append(current)
            current = []
        current.append(ev)
    if current:
        sessions.append(current)
    return sessions


def print_tree(sessions):
    for si, sess in enumerate(sessions):
        print("=" * 80)
        print(f"Session {si + 1}  (total events: {len(sess)})")
        print("=" * 80)

        # Phase 1: Runner accept
        print("\n[Phase 1] Runner HTTP server starts")
        for ev in sess:
            if ev[0] == "RUNNER":
                print(f"  RUNNER.accept  ts={ev[2]}  tid={ev[3]}  fd={ev[5]}  dur={ev[4]}us")

        # Phase 2: Main connects
        print("\n[Phase 2] Main process connects to runner (internal HTTP)")
        for ev in sess:
            if ev[0] == "GOCALL":
                print(f"  GOCALL.connect_runner  ts={ev[2]}  tid={ev[3]}  port={ev[5]}")

        # Phase 3: Model loading
        print("\n[Phase 3] Model loading into memory (mmap)")
        for ev in sess:
            if ev[0] == "UPROBE" and ev[1] == "llama_model_load_from_file":
                dur_ms = ev[4] / 1000
                print(f"  llama_model_load_from_file  dur={dur_ms:.1f}ms  (tid={ev[3]})")

        # Phase 4: Inference
        print("\n[Phase 4] Inference loop (per-token generation step)")
        print("  Structure: ggml_compute → llama_decode → llama_synchronize → sampler")
        print("")

        uprobe_events = [ev for ev in sess if ev[0] == "UPROBE" and ev[1] != "llama_model_load_from_file"]

        # Group by ggml_backend_sched_graph_compute_async as iteration boundary
        iterations = []
        current_iter = []
        for ev in uprobe_events:
            if ev[1] == "ggml_backend_sched_graph_compute_async":
                if current_iter:
                    iterations.append(current_iter)
                current_iter = [ev]
            elif current_iter:
                current_iter.append(ev)

        if current_iter:
            iterations.append(current_iter)

        for i, it in enumerate(iterations):
            total_dur = sum(ev[4] for ev in it)
            print(f"  Iteration {i + 1}  (total: {total_dur}us = {total_dur/1000:.1f}ms)")
            for ev in it:
                func = ev[1]
                dur = ev[4]
                tid = ev[3]
                if func == "ggml_backend_sched_graph_compute_async":
                    print(f"    └─ ggml_backend_sched_graph_compute_async  dur={dur}us")
                elif func == "llama_decode":
                    print(f"      ├─ llama_decode                   dur={dur}us  ({dur/1000:.1f}ms)")
                elif func == "llama_synchronize":
                    print(f"      ├─ llama_synchronize              dur={dur}us")
                elif func == "common_sampler_sample_cpp":
                    print(f"      ├─ common_sampler_sample_cpp      dur={dur}us")
                elif func == "common_sampler_csample":
                    print(f"      └─ common_sampler_csample          dur={dur}us")

        # Phase 5: Key syscalls (large reads, futex waits)
        print("\n[Phase 5] Key syscall activity (large reads / futex waits > 1ms)")
        syscall_count = 0
        for ev in sess:
            if ev[0] == "SYSCALL":
                if ev[1] == "read" and ev[5] and ev[5] > 32768:
                    syscall_count += 1
                    print(f"  read  bytes={ev[5]:>10}  dur={ev[4]}us  (tid={ev[3]})")
                elif ev[1] == "futex" and ev[4] > 1000:
                    syscall_count += 1
                    print(f"  futex(wait)  dur={ev[4]}us  (tid={ev[3]})")
        if syscall_count == 0:
            print("  (none > 1ms)")

        print()


def main():
    events = parse_trace(TRACE)
    sessions = split_sessions(events)
    print(f"Parsed {len(events)} events, split into {len(sessions)} session(s)\n")
    print_tree(sessions)


if __name__ == "__main__":
    main()
