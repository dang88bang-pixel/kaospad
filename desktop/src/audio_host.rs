//! Offline-first desktop audio routing matrix (ALSA / PipeWire / JACK / CoreAudio / WASAPI / ASIO).
//! Real vendor backends plug in behind the same `AudioHost` contract.

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AudioHost {
    pub sample_rate_hz: u32,
    pub frames_per_buffer: u32,
    pub low_latency_backend: &'static str,
    pub route: &'static str,
    pub localhost_only: bool,
}

impl Default for AudioHost {
    fn default() -> Self {
        Self::for_os(std::env::consts::OS)
    }
}

impl AudioHost {
    pub fn for_os(os: &str) -> Self {
        let (backend, route) = match os {
            "macos" => ("CoreAudio", "coreaudio://default"),
            "windows" => ("WASAPI/ASIO", "wasapi://default"),
            _ => ("ALSA/PipeWire/JACK", "alsa://default"),
        };
        Self {
            sample_rate_hz: 96_000,
            frames_per_buffer: 128,
            low_latency_backend: backend,
            route,
            localhost_only: true,
        }
    }

    pub fn block_ms(&self) -> f64 {
        (self.frames_per_buffer as f64 / self.sample_rate_hz as f64) * 1000.0
    }

    pub fn roundtrip_budget_ms(&self) -> f64 {
        1.2
    }

    pub fn route_locked(&self) -> bool {
        self.localhost_only && self.frames_per_buffer <= 256
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn linux_backend_is_alsa_family() {
        let host = AudioHost::for_os("linux");
        assert!(host.low_latency_backend.contains("ALSA"));
        assert!(host.route_locked());
        assert!(host.block_ms() < 2.0);
    }

    #[test]
    fn macos_and_windows_backends() {
        assert_eq!(AudioHost::for_os("macos").low_latency_backend, "CoreAudio");
        assert_eq!(AudioHost::for_os("windows").low_latency_backend, "WASAPI/ASIO");
    }
}
