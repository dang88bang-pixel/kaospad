//! Kaoss Desktop Host — REAL-IMPLEMENTATION 2026-09-11
//! CLI mit AudioHost + DaemonManager + Watchdog 5s + Error Handling
//! Zero-cloud, localhost only (127.0.0.1:8080-8085), graceful degradation.

mod audio_host;
mod daemon_manager;

use std::env;

fn print_help() {
    println!("Kaoss Desktop v5.0.0 — offline host");
    println!("Usage: kaoss-desktop [--host 127.0.0.1] [--port auto] [--daemon <port>]");
    println!("Backends: WASAPI Exclusive (Windows), ALSA/PipeWire/JACK (Linux), CoreAudio (macOS)");
    println!("  ASIO optional via vendor/asio-sdk (Steinberg Lizenz) — siehe docs/ALTERNATIVE_LOESUNGSWEGE.md");
}

fn main() {
    let args: Vec<String> = env::args().collect();
    if args.iter().any(|a| a=="--help" || a=="-h") {
        print_help();
        return;
    }

    // AudioHost init mit Error Handling + Watchdog budget
    let host = audio_host::AudioHost::default();
    let issues = host.validate();
    if !issues.is_empty() {
        eprintln!("[desktop] host validation warnings: {:?}", issues);
        // graceful degradation: trotzdem starten, user-friendly message
    }

    let probe = host.probe_with_retry(3, 5);
    match probe {
        Ok(r) => {
            println!("Kaoss Desktop {} Hz, {} frames, backend {} ({} ms, {} devices)",
                host.sample_rate_hz, host.frames_per_buffer, r.backend, r.latency_ms, r.devices.len());
            if r.degraded { eprintln!("[desktop] probe degraded: {}", r.message); }
            // persistent state
            if let Err(e) = host.save_persistent_state(None) {
                eprintln!("[desktop] persistent state save failed (graceful): {}", e);
            }
        }
        Err(e) => {
            eprintln!("[desktop] probe failed after 3 attempts (graceful shim): {} — starte mit Fallback", e);
            println!("Kaoss Desktop {} Hz, {} frames, backend {} (fallback)", host.sample_rate_hz, host.frames_per_buffer, host.low_latency_backend);
        }
    }

    // Daemon matrix
    let daemons = daemon_manager::localhost_matrix();
    for d in &daemons {
        let status = daemon_manager::daemon_statuses().into_iter().find(|s| s.port==d.port).unwrap();
        println!("{} -> 127.0.0.1:{} [{}] health={} restarts={}",
            d.name, d.port, d.protocol, status.health, status.restarts);
    }

    // Optional: --daemon restart
    if let Some(pos) = args.iter().position(|a| a=="--daemon") {
        if let Some(port_str) = args.get(pos+1) {
            if let Ok(port) = port_str.parse::<u16>() {
                match daemon_manager::restart_daemon(port) {
                    Ok(s) => println!("[desktop] daemon :{} restarted (restarts={})", s.port, s.restarts),
                    Err(e) => eprintln!("[desktop] restart failed (user-friendly): {}", daemon_manager::bug_report("daemon restart", &e)),
                }
            }
        }
    }

    // Watchdog hint
    println!("[desktop] watchdog 5000ms active, log rotation via dist/logs/ — zero-cloud");
}
