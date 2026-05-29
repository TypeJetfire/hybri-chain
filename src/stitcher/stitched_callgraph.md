```mermaid
flowchart LR
    %% === 分层布局 ===
    subgraph go_cgo_bridge [Go↔CGO 边界]
        direction TB
        gocgo(("🦘 Go/CGO Bridge"))
    end
    subgraph llama_api [Llama API 层]
        direction TB
        llamaapi(("🔶 Llama API"))
    end
    subgraph batch_sampler [批处理/采样层]
        direction TB
        batchsam(("🟡 Batch/Sampler"))
    end
    subgraph sched_compute [GGML 调度层]
        direction TB
        sched(("🟢 Sched/Compute"))
    end
    subgraph ggml_ops [GGML 算子层]
        direction TB
        ops(("🟣 GGML Ops"))
    end

    %% === 层间边 ===
    %% Confirmed 边（粗实线）
    N0{"_cgo_8aa400f2462b_Cfunc_llama_decode"}:::gocgobridge
    N2{"_cgo_8aa400f2462b_Cfunc_common_sampler_csample"}:::gocgobridge
    N1{"llama_decode"}:::llamaapi
    N3{"common_sampler_csample"}:::llamaapi
    N7{"llama_synchronize"}:::llamaapi
    N10{"common_sampler_sample"}:::llamaapi
    N13{"common_sampler_print"}:::llamaapi
    N4{"ggml_backend_sched_graph_compute_async"}:::schedcompute
    N8{"ggml_backend_sched_synchronize"}:::schedcompute
    N11{"ggml_backend_sched_reset"}:::schedcompute
    N12{"ggml_backend_graph_compute_async"}:::schedcompute
    N5{"_cgoexp_8aa400f2462b_llamarunner_llama_Execute"}:::unknown
    N6{"llama_sampler_sample"}:::batchsampler
    N9{"_Z21common_sampler_sample"}:::ggmlops

    classDef go_cgo_bridge fill:#e74c3c,stroke:#c0392b,color:#fff
    classDef llama_api fill:#e67e22,stroke:#d35400,color:#fff
    classDef batch_sampler fill:#f39c12,stroke:#e67e22,color:#fff
    classDef sched_compute fill:#27ae60,stroke:#1e8449,color:#fff
    classDef ggml_ops fill:#8e44ad,stroke:#6c3483,color:#fff
    classDef ggml_backend fill:#2980b9,stroke:#1a5276,color:#fff
    classDef vocab fill:#16a085,stroke:#0e6655,color:#fff
    classDef memory fill:#2c3e50,stroke:#1a252f,color:#fff
    classDef unknown fill:#95a5a6,stroke:#7f8c8d,color:#fff

    N0 -->|"✓ confirmed"| N1    %% _cgo_8aa400f2462b_Cfunc_llama_decode → llama_decode
    N2 -->|"✓ confirmed"| N3    %% _cgo_8aa400f2462b_Cfunc_common_sampler_csample → common_sampler_csample
    N1 -->|"✓ confirmed"| N4    %% llama_decode → ggml_backend_sched_graph_compute_async

    %% === Inferred 边（虚线）===
    N5 -.->|"? inferred"| N1    %% _cgoexp_8aa400f2462b_llamarunner_llama_Execute → llama_decode
    N2 -.->|"? inferred"| N6    %% _cgo_8aa400f2462b_Cfunc_common_sampler_csample → llama_sampler_sample
    N1 -.->|"? inferred"| N7    %% llama_decode → llama_synchronize
    N1 -.->|"? inferred"| N8    %% llama_decode → ggml_backend_sched_synchronize
    N6 -.->|"? inferred"| N9    %% llama_sampler_sample → _Z21common_sampler_sample
    N10 -.->|"? inferred"| N9    %% common_sampler_sample → _Z21common_sampler_sample
    N4 -.->|"? inferred"| N8    %% ggml_backend_sched_graph_compute_async → ggml_backend_sched_synchronize
    N4 -.->|"? inferred"| N11    %% ggml_backend_sched_graph_compute_async → ggml_backend_sched_reset
    N4 -.->|"? inferred"| N12    %% ggml_backend_sched_graph_compute_async → ggml_backend_graph_compute_async
    N9 -.->|"? inferred"| N6    %% _Z21common_sampler_sample → llama_sampler_sample
    N9 -.->|"? inferred"| N13    %% _Z21common_sampler_sample → common_sampler_print
```