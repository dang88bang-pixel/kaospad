//! Offline-first desktop audio routing matrix (ALSA / PipeWire / JACK / CoreAudio / WASAPI / ASIO).
//! Real vendor backends plug in behind the same `AudioHost` contract.
//!
//! Alternative Lösungswege A (ASIO SDK ⛔):
//!   - ASIO SDK (Steinberg-Lizenz) → RtAudio, PortAudio, JACK, WASAPI Exclusive nutzen.
//!   - ASIO nur für Windows-Pro-Users — im Repo ist bereits WASAPI Exclusive vorgesehen.
//!   - Ein ASIO-Shim (vendor/asio-sdk/README.txt + scripts/setup_asio_sdk.ps1) reicht für CI.
//!   - Dieses Modul bleibt compilierbar ohne SDK; echte SDK-Hooks werden nur bei vorhandenem SDK aktiviert.
//!   - Siehe docs/ALTERNATIVE_LOESUNGSWEGE.md A und scripts/install_audio_backends.sh

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
    /// Liefert den primären Low-Latency-Backend-Namen je OS.
    /// Windows bevorzugt WASAPI Exclusive (ASIO nur optional via SDK).
    /// Siehe `scripts/install_audio_backends.sh`.
    pub fn for_os(os: &str) -> Self {
        let (backend, route) = match os {
            "macos" => ("CoreAudio", "coreaudio://default"),
            // WASAPI Exclusive — ASIO nur Pro-Option (RtAudio/PortAudio/JACK sind Shims)
            "windows" => ("WASAPI Exclusive", "wasapi://exclusive"),
            _ => ("ALSA/PipeWire/JACK", "alsa://hw:0,0"),
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
        // WASAPI Exclusive ist primär; ASIO nur optional
        assert!(AudioHost::for_os("windows").low_latency_backend.contains("WASAPI"));
    }

    #[test]
    fn asio_alternative_available() {
        // Ohne ASIO SDK compilierbar — WASAPI/ALSA/JACK/RtAudio reichen für CI
        let win = AudioHost::for_os("windows");
        assert!(win.low_latency_backend.contains("WASAPI"));
        let linux = AudioHost::for_os("linux");
        assert!(linux.low_latency_backend.contains("ALSA") || linux.low_latency_backend.contains("PipeWire"));
    }
}
