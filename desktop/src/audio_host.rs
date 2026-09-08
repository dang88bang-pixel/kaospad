#[derive(Debug, Clone)]
pub struct AudioHost {
    pub sample_rate_hz: u32,
    pub frames_per_buffer: u32,
    pub low_latency_backend: &'static str,
}

impl Default for AudioHost {
    fn default() -> Self {
        let backend = if cfg!(target_os = "macos") {
            "CoreAudio"
        } else if cfg!(target_os = "windows") {
            "ASIO/DirectSound"
        } else {
            "ALSA/PipeWire/JACK"
        };
        Self { sample_rate_hz: 96_000, frames_per_buffer: 128, low_latency_backend: backend }
    }
}
