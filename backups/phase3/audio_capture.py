#!/usr/bin/env python3
"""Echte Audio-Capture-Blöcke (Mic / USB-UAC2 / BLE) für die DSP-Kette.

Bis hierher wurde ``dsp.process`` ausschließlich mit deterministischen Fixtures
aus ``dsp_chain.test_signal()`` gefüttert. Dieses Modul stellt die echte
Erfassungsseite daneben und liefert *Blöcke*, keine Konstanten:

``AlsaCapture``
    ``/dev/snd`` über ``arecord`` (internes Mic oder die USB-UAC2-Karte).
``UsbUac2Capture``
    dieselbe ALSA-Route, die Karte wird aus dem sysfs/ALSA-Scan der
    USB-Audio-Class-2-Geräte aufgelöst (``engines/usb_uac2.py``).
``IpcCapture``
    Float32-PCM-Pipe auf Loopback (Unix-Datagramm-Socket). Hier schieben echte
    Clients ihre Blöcke hinein: Android ``UsbUac2Client.kt`` /
    ``BleCodecClient.kt`` (LC3plus-decodiert) oder die Desktop-Mic-Bridge.
``FileCapture``
    WAV/RAW-Aufnahme von der Platte – Regression und Doku, nie als "live"
    gekennzeichnet.

Jeder Block trägt Provenienz (``source``, ``device``, ``real``), damit Kette und
``.cypher`` jederzeit ausweisen, ob echte Hardware oder eine Fixture gerechnet
wurde. Kein Socket verlässt Loopback. Ohne Hardware meldet der Router
``available=False`` statt still eine Fixture als Live-Capture auszugeben.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import struct
import subprocess
import threading
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
SOCKET_DIR = ROOT / "dist" / "sockets"
CAPTURE_DIR = ROOT / "dist" / "captures"

# IPC-Frame-Protokoll der Float32-PCM-Pipe (127.0.0.1 / Unix-Socket):
#   b"KPCM" | uint32 sample_rate_hz | uint32 frames | frames * float32 (LE)
#   b"KCTL" | UTF-8 JSON  (Meta: device, codec, client)
PCM_MAGIC = b"KPCM"
CTL_MAGIC = b"KCTL"
HEADER = struct.Struct("<4sII")

# Route (Device-Matrix) -> präferierter Capture-Backend.
ROUTE_BACKENDS = {
    "internal_mic": ("alsa", "ipc_mic"),
    "usb_c_audio": ("usb_uac2", "alsa", "ipc_uac2"),
    "bluetooth_client": ("ipc_ble",),
}

IPC_SOCKETS = {
    "ipc_mic": "kaoss-capture-mic.sock",
    "ipc_uac2": "kaoss-capture-uac2.sock",
    "ipc_ble": "kaoss-capture-ble.sock",
}

IPC_SOURCE_LABEL = {
    "ipc_mic": "mic_ipc",
    "ipc_uac2": "usb_uac2_ipc",
    "ipc_ble": "ble_lc3_ipc",
}


def _now_ms() -> float:
    return round(time.time() * 1000.0, 3)


@dataclass
class CaptureBlock:
    """Ein echter PCM-Block inklusive Provenienz."""

    pcm: list[float]
    frames: int
    sample_rate_hz: float
    source: str
    device: str
    real: bool
    t_ms: float = field(default_factory=_now_ms)
    note: str = ""

    def peak_dbfs(self) -> float:
        peak = max((abs(sample) for sample in self.pcm), default=0.0)
        if peak <= 0.0:
            return -120.0
        import math

        return round(20.0 * math.log10(peak), 3)

    def provenance(self) -> dict[str, object]:
        return {
            "backend": self.source,
            "device": self.device,
            "real_capture": bool(self.real),
            "frames": int(self.frames),
            "sample_rate_hz": float(self.sample_rate_hz),
            "block_ms": round((self.frames / self.sample_rate_hz) * 1000.0, 3) if self.sample_rate_hz else 0.0,
            "peak_dbfs": self.peak_dbfs(),
            "t_ms": self.t_ms,
            "note": self.note,
        }


def _s16_to_float(raw: bytes) -> list[float]:
    count = len(raw) // 2
    samples = struct.unpack(f"<{count}h", raw[: count * 2])
    return [sample / 32768.0 for sample in samples]


# --------------------------------------------------------------------------- #
# ALSA / USB-UAC2 (echte Soundkarten)
# --------------------------------------------------------------------------- #
def _alsa_capture_nodes() -> list[str]:
    snd = Path("/dev/snd")
    if not snd.is_dir():
        return []
    return sorted(node.name for node in snd.iterdir() if node.name.startswith("pcmC") and node.name.endswith("c"))


def _alsa_cards() -> list[dict[str, object]]:
    cards: list[dict[str, object]] = []
    proc = Path("/proc/asound")
    if not (proc / "cards").exists():
        return cards
    current: dict[str, object] | None = None
    for line in (proc / "cards").read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped[:1].isdigit():
            index, _, rest = stripped.partition(" [")
            name = rest.split("]", 1)[0].strip() if "]" in rest else rest
            current = {"index": int(index.split()[0]), "name": name or "ALSA", "usb": False}
            cards.append(current)
        elif current is not None:
            current["driver"] = stripped
    for card in cards:
        index = card.get("index")
        if (proc / f"card{index}" / "usbbus").exists():
            card["usb"] = True
            card["usbbus"] = (proc / f"card{index}" / "usbbus").read_text(encoding="utf-8", errors="replace").strip()
    return cards


def resolve_alsa_device(prefer_usb: bool = False) -> dict[str, object]:
    """Wählt eine echte Capture-Karte; USB-Karten haben Vorrang für UAC2."""
    cards = _alsa_cards()
    nodes = _alsa_capture_nodes()
    chosen = None
    if prefer_usb:
        chosen = next((card for card in cards if card.get("usb")), None)
    if chosen is None and cards:
        chosen = cards[0]
    if chosen is None and nodes:
        # z. B. pcmC0D0c -> hw:0,0
        name = nodes[0]
        card = name[4:].split("D")[0]
        device = name.split("D")[1].rstrip("c")
        return {"device": f"hw:{card},{device}", "card": f"card{card}", "cards": cards, "nodes": nodes}
    if chosen is not None:
        return {
            "device": f"hw:{chosen['index']},0",
            "card": f"card{chosen['index']}",
            "name": chosen.get("name"),
            "usb": bool(chosen.get("usb")),
            "cards": cards,
            "nodes": nodes,
        }
    return {"device": "", "cards": cards, "nodes": nodes}


class AlsaCapture:
    """Liest echte Blöcke über ``arecord`` von ``/dev/snd`` (Mic oder UAC2-Karte)."""

    backend = "alsa"

    def __init__(self, prefer_usb: bool = False) -> None:
        self.prefer_usb = prefer_usb
        self.proc: subprocess.Popen | None = None
        self.device = ""
        self.sample_rate_hz = 48_000.0
        self.frames_read = 0
        self.error = ""

    @staticmethod
    def available(prefer_usb: bool = False) -> dict[str, object]:
        info = resolve_alsa_device(prefer_usb=prefer_usb)
        has_arecord = shutil.which("arecord") is not None
        hardware = bool(info.get("device"))
        return {
            "available": bool(has_arecord and hardware),
            "reason": "" if (has_arecord and hardware) else ("no arecord binary" if not has_arecord else "no capture card in /dev/snd"),
            "device": info.get("device", ""),
            "card": info.get("card", ""),
            "usb": bool(info.get("usb", False)),
            "capture_nodes": info.get("nodes", []),
        }

    def open(self, sample_rate_hz: float = 48_000.0, device: str | None = None) -> dict[str, object]:
        info = resolve_alsa_device(prefer_usb=self.prefer_usb)
        self.device = device or str(info.get("device") or "default")
        self.sample_rate_hz = float(sample_rate_hz)
        self.frames_read = 0
        if shutil.which("arecord") is None:
            raise RuntimeError("arecord not available – keine echte ALSA-Capture möglich")
        self.proc = subprocess.Popen(
            [
                "arecord", "-q", "-t", "raw", "-f", "S16_LE", "-c", "1",
                "-r", str(int(self.sample_rate_hz)), "-D", self.device,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        return {
            "backend": "usb_uac2" if self.prefer_usb else "alsa",
            "device": self.device,
            "sample_rate_hz": self.sample_rate_hz,
            "transport": "arecord raw S16_LE mono",
            "real_capture": True,
            "live_on_open": True,
            "pid": self.proc.pid,
        }

    def read_block(self, frames: int, timeout_s: float = 1.5) -> CaptureBlock | None:
        if self.proc is None or self.proc.stdout is None:
            return None
        want = int(frames) * 2
        deadline = time.perf_counter() + timeout_s
        raw = b""
        while len(raw) < want:
            if self.proc.poll() is not None:
                self.error = "arecord exited"
                return None
            chunk = self.proc.stdout.read(want - len(raw))
            if not chunk:
                if time.perf_counter() > deadline:
                    self.error = "arecord timeout"
                    return None
                continue
            raw += chunk
        self.frames_read += len(raw) // 2
        return CaptureBlock(
            pcm=_s16_to_float(raw),
            frames=len(raw) // 2,
            sample_rate_hz=self.sample_rate_hz,
            source="usb_uac2" if self.prefer_usb else "alsa",
            device=self.device,
            real=True,
            note="arecord /dev/snd",
        )

    def close(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None


class UsbUac2Capture(AlsaCapture):
    """USB Audio Class 2 Karte: identische PCM-Route, andere Kartenauflösung."""

    backend = "usb_uac2"

    def __init__(self) -> None:
        super().__init__(prefer_usb=True)

    @staticmethod
    def available() -> dict[str, object]:
        info = AlsaCapture.available(prefer_usb=True)
        try:
            from usb_uac2 import scan_sysfs

            sysfs = scan_sysfs()
        except Exception:  # noqa: BLE001 - Engine optional
            sysfs = []
        info["sysfs_devices"] = sysfs
        return info


# --------------------------------------------------------------------------- #
# Loopback IPC-Pipe (echte Clients: Android UAC2/BLE, Desktop-Mic-Bridge)
# --------------------------------------------------------------------------- #
class IpcCapture:
    """Float32-PCM-Pipe auf Loopback: echte Blöcke von einem Client-Prozess."""

    def __init__(self, name: str) -> None:
        if name not in IPC_SOCKETS:
            raise ValueError(f"unknown capture pipe: {name}")
        self.name = name
        self.source = IPC_SOURCE_LABEL[name]
        self.backend = name
        self.path = SOCKET_DIR / IPC_SOCKETS[name]
        self.sock: socket.socket | None = None
        self.buffer: bytearray = bytearray()
        self.sample_rate_hz = 48_000.0
        self.frames_read = 0
        self.datagrams = 0
        self.client: dict[str, object] = {}
        self.opened_at = 0.0
        self.lock = threading.Lock()

    @staticmethod
    def available() -> dict[str, object]:
        return {"available": True, "reason": "", "transport": "unix datagram (loopback)"}

    def open(self, sample_rate_hz: float = 48_000.0, device: str | None = None) -> dict[str, object]:
        SOCKET_DIR.mkdir(parents=True, exist_ok=True)
        self.close()
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        if self.path.exists():
            self.path.unlink()
        self.sock.bind(str(self.path))
        self.sock.settimeout(0.05)
        self.sample_rate_hz = float(sample_rate_hz)
        self.opened_at = _now_ms()
        self.buffer = bytearray()
        self.frames_read = 0
        self.datagrams = 0
        return {
            "backend": self.backend,
            "device": device or str(self.path.relative_to(ROOT)),
            "sample_rate_hz": self.sample_rate_hz,
            "transport": "unix datagram KPCM/KCTL",
            "real_capture": True,
            "live_on_open": False,
            "note": "Pipe offen – echt, sobald ein Client Blöcke schickt",
            "socket": str(self.path),
        }

    def _drain(self, deadline: float) -> bool:
        """Liest Datagramme, bis genug Samples im Puffer liegen."""
        assert self.sock is not None
        while len(self.buffer) < 4:
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                return False
            self.sock.settimeout(min(0.25, remaining))
            try:
                datagram = self.sock.recv(1 << 20)
            except socket.timeout:
                continue
            except OSError:
                return False
            if not datagram:
                continue
            if datagram[:4] == CTL_MAGIC:
                try:
                    self.client = json.loads(datagram[4:].decode("utf-8", "replace"))
                except json.JSONDecodeError:
                    self.client = {"raw": len(datagram)}
                continue
            if datagram[:4] != PCM_MAGIC or len(datagram) < HEADER.size:
                continue
            _, rate, frames = HEADER.unpack(datagram[: HEADER.size])
            self.sample_rate_hz = float(rate)
            self.buffer.extend(datagram[HEADER.size : HEADER.size + frames * 4])
            self.datagrams += 1
        return True

    def read_block(self, frames: int, timeout_s: float = 0.4) -> CaptureBlock | None:
        if self.sock is None:
            return None
        want = int(frames) * 4
        with self.lock:
            if len(self.buffer) < want and not self._drain(time.perf_counter() + timeout_s):
                return None
            if len(self.buffer) < want:
                return None
            raw = bytes(self.buffer[:want])
            del self.buffer[:want]
        count = len(raw) // 4
        samples = list(struct.unpack(f"<{count}f", raw))
        self.frames_read += count
        return CaptureBlock(
            pcm=samples,
            frames=count,
            sample_rate_hz=self.sample_rate_hz,
            source=self.source,
            device=str(self.client.get("device") or self.path.name),
            real=True,
            note=f"loopback ipc pipe // {self.client.get('codec') or self.client.get('client') or 'pcm'}",
        )

    def close(self) -> None:
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
        self.sock = None
        if self.path.exists():
            try:
                self.path.unlink()
            except OSError:
                pass


# --------------------------------------------------------------------------- #
# Datei-Capture (Regression/Doku, ausdrücklich NICHT live)
# --------------------------------------------------------------------------- #
class FileCapture:
    """Streamt eine WAV/RAW-Aufnahme blockweise – deterministisch, nie "live"."""

    backend = "file"

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.wave = None
        self.raw = None
        self.sample_rate_hz = 48_000.0
        self.frames_read = 0
        self.buffer: bytearray = bytearray()
        self.bytes_per_frame = 2

    @staticmethod
    def available(path: Path | str | None = None) -> dict[str, object]:
        target = Path(path) if path else None
        if target is None:
            candidates = sorted(CAPTURE_DIR.glob("*.wav")) if CAPTURE_DIR.is_dir() else []
            target = candidates[0] if candidates else None
        exists = bool(target and target.is_file())
        return {"available": exists, "reason": "" if exists else "no capture file", "path": str(target) if target else ""}

    def open(self, sample_rate_hz: float = 48_000.0, device: str | None = None) -> dict[str, object]:
        target = Path(device) if device else self.path
        self.path = target
        if target.suffix.lower() == ".wav":
            self.wave = wave.open(str(target), "rb")
            self.sample_rate_hz = float(self.wave.getframerate())
            self.bytes_per_frame = self.wave.getsampwidth() * max(1, self.wave.getnchannels())
        else:
            self.raw = target.open("rb")
            self.sample_rate_hz = float(sample_rate_hz)
            self.bytes_per_frame = 2
        self.buffer = bytearray()
        self.frames_read = 0
        return {
            "backend": "file",
            "device": str(self.path),
            "sample_rate_hz": self.sample_rate_hz,
            "transport": f"file {self.path.suffix or '.raw'}",
            "real_capture": False,
            "live_on_open": False,
        }

    def read_block(self, frames: int, timeout_s: float = 0.0) -> CaptureBlock | None:
        want = int(frames) * self.bytes_per_frame
        while len(self.buffer) < want:
            if self.wave is not None:
                chunk = self.wave.readframes(int(frames))
            elif self.raw is not None:
                chunk = self.raw.read(want)
            else:
                return None
            if not chunk:
                return None
            self.buffer.extend(chunk)
        raw = bytes(self.buffer[:want])
        del self.buffer[:want]
        if self.bytes_per_frame == 2:
            pcm = _s16_to_float(raw)
        else:
            count = len(raw) // 4
            pcm = list(struct.unpack(f"<{count}f", raw))
        self.frames_read += len(pcm)
        return CaptureBlock(
            pcm=pcm,
            frames=len(pcm),
            sample_rate_hz=self.sample_rate_hz,
            source="file",
            device=self.path.name,
            real=False,
            note="offline capture file",
        )

    def close(self) -> None:
        for handle in (self.wave, self.raw):
            if handle is not None:
                try:
                    handle.close()
                except Exception:  # noqa: BLE001
                    pass
        self.wave = None
        self.raw = None


# --------------------------------------------------------------------------- #
# Router: Route -> Backend, mit ehrlicher Provenienz
# --------------------------------------------------------------------------- #
class CaptureRouter:
    """Wählt pro Device-Matrix-Route den besten verfügbaren Capture-Backend."""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.backend: object | None = None
        self.route = "internal_mic"
        self.mode = "none"
        self.sample_rate_hz = 48_000.0
        self.frames_per_buffer = 128
        self.info: dict[str, object] = {}
        self.blocks = 0
        self.frames = 0
        self.last: dict[str, object] | None = None
        self.error = ""
        self.file_path: Path | None = None

    # ------------------------------------------------------------------ #
    def probe(self) -> dict[str, object]:
        mic = AlsaCapture.available(prefer_usb=False)
        usb = UsbUac2Capture.available()
        pipes = {name: str((SOCKET_DIR / filename)) for name, filename in IPC_SOCKETS.items()}
        return {
            "ok": True,
            "offline": True,
            "zero_cloud": True,
            "backends": {
                "alsa": mic,
                "usb_uac2": usb,
                "ipc": {"available": True, "sockets": pipes, "protocol": "KPCM float32 mono"},
                "file": FileCapture.available(self.file_path),
            },
            "routes": {route: list(order) for route, order in ROUTE_BACKENDS.items()},
        }

    def _make(self, name: str) -> object | None:
        if name == "alsa":
            return AlsaCapture(prefer_usb=False)
        if name == "usb_uac2":
            return UsbUac2Capture()
        if name in IPC_SOCKETS:
            return IpcCapture(name)
        if name == "file":
            return FileCapture(self.file_path or "")
        return None

    def open(
        self,
        route: str = "internal_mic",
        sample_rate_hz: float = 48_000.0,
        frames_per_buffer: int = 128,
        mode: str = "auto",
        device: str | None = None,
        file_path: Path | str | None = None,
    ) -> dict[str, object]:
        """Öffnet einen Capture-Backend; ``mode``: auto|none|alsa|usb_uac2|ipc_*|file."""
        with self.lock:
            self.close()
            self.route = route if route in ROUTE_BACKENDS else "internal_mic"
            self.sample_rate_hz = float(sample_rate_hz)
            self.frames_per_buffer = int(frames_per_buffer)
            self.mode = str(mode or "auto")
            self.error = ""
            if file_path:
                self.file_path = Path(file_path)
            if self.mode == "none":
                self.info = {"opened": False, "backend": "none", "reason": "capture disabled"}
                return dict(self.info)

            order = [self.mode] if self.mode not in {"auto"} else list(ROUTE_BACKENDS.get(self.route, ()))
            attempts: list[dict[str, object]] = []
            for name in order:
                candidate = self._make(name)
                if candidate is None:
                    attempts.append({"backend": name, "opened": False, "reason": "unknown backend"})
                    continue
                try:
                    self.info = candidate.open(self.sample_rate_hz, device=device)  # type: ignore[attr-defined]
                    self.backend = candidate
                    self.info.update({"opened": True, "route": self.route, "mode": self.mode, "attempts": attempts})
                    return dict(self.info)
                except Exception as exc:  # noqa: BLE001 - Hardware darf nicht crashen
                    self.error = f"{name}: {exc}"
                    attempts.append({"backend": name, "opened": False, "reason": str(exc)})
            self.backend = None
            self.info = {
                "opened": False,
                "backend": "none",
                "route": self.route,
                "mode": self.mode,
                "reason": self.error or "no capture backend available",
                "attempts": attempts,
            }
            return dict(self.info)

    def pull(self, frames: int | None = None, timeout_s: float = 0.4) -> CaptureBlock | None:
        """Liefert den nächsten echten Block oder ``None`` (kein Backend/kein Datum)."""
        with self.lock:
            if self.backend is None:
                return None
            block = self.backend.read_block(int(frames or self.frames_per_buffer), timeout_s=timeout_s)  # type: ignore[attr-defined]
            if block is None:
                return None
            self.blocks += 1
            self.frames += block.frames
            self.last = block.provenance()
            return block

    def status(self) -> dict[str, object]:
        with self.lock:
            live = self.backend is not None
            streaming = bool(self.info.get("live_on_open")) or self.blocks > 0
            return {
                "ok": True,
                "armed": bool(live),
                "backend": (self.info.get("backend") if live else "none") or "none",
                "route": self.route,
                "mode": self.mode,
                "device": self.info.get("device", ""),
                "real_capture": bool(live and self.info.get("real_capture", False) and streaming),
                "sample_rate_hz": self.sample_rate_hz,
                "frames_per_buffer": self.frames_per_buffer,
                "blocks": self.blocks,
                "frames": self.frames,
                "last_block": self.last,
                "reason": self.info.get("reason", ""),
                "offline": True,
            }

    def close(self) -> None:
        with self.lock:
            if self.backend is not None:
                try:
                    self.backend.close()  # type: ignore[attr-defined]
                except Exception:  # noqa: BLE001
                    pass
            self.backend = None
            self.info = {"opened": False, "backend": "none", "reason": "closed"}


def fixture_block(kind: str, frames: int, sample_rate_hz: float) -> CaptureBlock:
    """Deterministischer Ersatzblock – ausdrücklich als Fixture gekennzeichnet."""
    from dsp_chain import test_signal

    pcm = test_signal(kind, frames=frames, sample_rate_hz=sample_rate_hz)
    return CaptureBlock(
        pcm=pcm,
        frames=len(pcm),
        sample_rate_hz=float(sample_rate_hz),
        source="fixture",
        device=f"test_signal:{kind}",
        real=False,
        note="deterministic fixture (keine Hardware-Capture)",
    )


def pull_block(
    router: CaptureRouter,
    frames: int,
    sample_rate_hz: float,
    fallback_signal: str = "mouth_bass",
) -> CaptureBlock:
    """Erst echte Capture, sonst gekennzeichnete Fixture."""
    block = router.pull(frames) if router is not None else None
    if block is not None:
        return block
    return fixture_block(fallback_signal, frames, sample_rate_hz)


def encode_ipc_frame(pcm: Sequence[float], sample_rate_hz: float = 48_000.0) -> bytes:
    """Baut einen KPCM-Datagramm-Frame (Client-Seite der Float32-Pipe)."""
    samples = [float(value) for value in pcm]
    header = struct.pack("<4sII", PCM_MAGIC, int(sample_rate_hz), len(samples))
    return header + struct.pack(f"<{len(samples)}f", *samples)


def encode_ipc_control(payload: dict[str, object]) -> bytes:
    return CTL_MAGIC + json.dumps(payload, ensure_ascii=False).encode("utf-8")


if __name__ == "__main__":  # pragma: no cover - manueller Smoke-Run
    router = CaptureRouter()
    print(json.dumps(router.probe(), ensure_ascii=False, indent=2))
    print(json.dumps(router.open("usb_c_audio", 48_000, 128, "auto"), ensure_ascii=False, indent=2))
    print(json.dumps(router.status(), ensure_ascii=False, indent=2))
    router.close()
    print("sockets:", os.listdir(SOCKET_DIR) if SOCKET_DIR.is_dir() else [])
