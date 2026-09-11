//! Tauri host re-exports same logic as desktop/src/daemon_manager.rs — REAL-IMPLEMENTATION 2026-09-11
//! Keeps API parity for Tauri build.

#[derive(Debug, Clone)]
pub struct DaemonSpec {
    pub name: &'static str,
    pub port: u16,
    pub protocol: &'static str,
    pub latency: &'static str,
}

pub fn localhost_matrix() -> Vec<DaemonSpec> {
    vec![
        DaemonSpec { name: "master-system-orchestrator", port: 8080, protocol: "HTTP JSON", latency: "AUTO" },
        DaemonSpec { name: "audio-loopback-daemon", port: 8081, protocol: "Float32 PCM pipe", latency: "<1.2ms" },
        DaemonSpec { name: "neurallift-engine", port: 8082, protocol: "HTTP GLB JSON", latency: "1.8s fallback" },
        DaemonSpec { name: "avatar-orchestrator", port: 8083, protocol: "skeleton JSONL", latency: "16.6ms" },
        DaemonSpec { name: "dsp-transient-bridge", port: 8084, protocol: "DSP block JSON", latency: "<1.2ms" },
        DaemonSpec { name: "offline-whisper-daemon", port: 8085, protocol: "HTTP UTF-8", latency: "<9ms" },
    ]
}
