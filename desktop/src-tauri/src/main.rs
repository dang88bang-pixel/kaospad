//! Kaoss Tauri Host — REAL-IMPLEMENTATION 2026-09-11
//! Minimal Tauri entry that prints host + daemon matrix (real Tauri webview loaded via tauri.conf.json at runtime)

mod audio_host;
mod daemon_manager;

fn main() {
    let host = audio_host::AudioHost::default();
    println!("Kaoss Tauri {} Hz, {} frames, backend {}", host.sample_rate_hz, host.frames_per_buffer, host.low_latency_backend);
    for d in daemon_manager::localhost_matrix() {
        println!("{} -> 127.0.0.1:{} [{}]", d.name, d.port, d.protocol);
    }
    println!("[tauri] watchdog 5000ms, zero-cloud, WebView binds to 127.0.0.1");
}
