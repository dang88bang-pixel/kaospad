#[derive(Debug, Clone)]
pub struct DaemonSpec {
    pub name: &'static str,
    pub port: u16,
}

pub fn localhost_matrix() -> Vec<DaemonSpec> {
    vec![
        DaemonSpec { name: "master-system-orchestrator", port: 8080 },
        DaemonSpec { name: "audio-loopback-daemon", port: 8081 },
        DaemonSpec { name: "neurallift-engine", port: 8082 },
        DaemonSpec { name: "avatar-orchestrator", port: 8083 },
        DaemonSpec { name: "dsp-transient-bridge", port: 8084 },
        DaemonSpec { name: "offline-whisper-daemon", port: 8085 },
    ]
}
