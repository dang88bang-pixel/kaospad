mod audio_host;
mod daemon_manager;

fn main() {
    let host = audio_host::AudioHost::default();
    let daemons = daemon_manager::localhost_matrix();
    println!("Kaoss Desktop {} Hz, {} frame buffer", host.sample_rate_hz, host.frames_per_buffer);
    for daemon in daemons {
        println!("{} -> 127.0.0.1:{}", daemon.name, daemon.port);
    }
}
