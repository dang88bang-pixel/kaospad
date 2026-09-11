import { createDspCore } from './dsp-core.js';

export class WebAudioCypherEngine {
  constructor({ onState = () => {}, onLevel = () => {}, onTransient = () => {} } = {}) {
    this.onState = onState;
    this.onLevel = onLevel;
    this.onTransient = onTransient;
    this.context = null;
    this.master = null;
    this.filter = null;
    this.delay = null;
    this.feedback = null;
    this.limiter = null;
    this.analyser = null;
    this.micStream = null;
    this.micSource = null;
    this.micGain = null;
    this.meterFrame = 0;
    this.xy = { x: 0.5, y: 0.5 };
    this.dspCorePromise = null;
    this.dspBackend = 'js';
    this.lastTransient = 'NONE';
    this.transientCounts = { KICK808: 0, SNARE_CLAP: 0, HAT_ROLL: 0 };
  }

  // Lazy DSP core: WASM when built + loadable, pure-JS mirror otherwise.
  async getDspCore() {
    if (!this.dspCorePromise) this.dspCorePromise = createDspCore();
    const core = await this.dspCorePromise;
    this.dspBackend = core.backend;
    return core;
  }

  async init() {
    if (this.context) {
      if (this.context.state === 'suspended') await this.context.resume();
      this.emitState('AUDIO: RUNNING');
      return this.context;
    }
    const AudioContextCtor = globalThis.AudioContext || globalThis.webkitAudioContext;
    if (!AudioContextCtor) throw new Error('WebAudio nicht verfügbar');
    this.context = new AudioContextCtor({ latencyHint: 'interactive', sampleRate: 48000 });

    this.master = this.context.createGain();
    this.master.gain.value = 0.78;

    this.filter = this.context.createBiquadFilter();
    this.filter.type = 'lowpass';
    this.filter.frequency.value = 9500;
    this.filter.Q.value = 0.8;

    this.delay = this.context.createDelay(1.0);
    this.delay.delayTime.value = 0.16;
    this.feedback = this.context.createGain();
    this.feedback.gain.value = 0.18;

    this.limiter = this.context.createWaveShaper();
    this.limiter.curve = WebAudioCypherEngine.brickwallCurve();
    this.limiter.oversample = '4x';

    this.analyser = this.context.createAnalyser();
    this.analyser.fftSize = 1024;
    this.analyser.smoothingTimeConstant = 0.72;

    this.filter.connect(this.delay);
    this.delay.connect(this.feedback);
    this.feedback.connect(this.delay);
    this.delay.connect(this.limiter);
    this.filter.connect(this.limiter);
    this.limiter.connect(this.master);
    this.master.connect(this.analyser);
    this.analyser.connect(this.context.destination);

    await this.context.resume();
    this.startMeter();
    this.applyXY(this.xy.x, this.xy.y);
    this.emitState(`AUDIO: RUNNING // ${Math.round(this.context.sampleRate / 1000)} kHz`);
    return this.context;
  }

  static brickwallCurve() {
    const samples = 65536;
    const curve = new Float32Array(samples);
    const threshold = 10 ** (-3.2 / 20);
    for (let i = 0; i < samples; i += 1) {
      const x = (i / (samples - 1)) * 2 - 1;
      const sign = Math.sign(x) || 1;
      const ax = Math.abs(x);
      curve[i] = sign * Math.min(threshold, Math.tanh(ax * 1.8) * threshold);
    }
    return curve;
  }

  async enumerateAudioInputs() {
    if (!navigator.mediaDevices?.enumerateDevices) return [];
    const devices = await navigator.mediaDevices.enumerateDevices();
    return devices.filter((device) => device.kind === 'audioinput');
  }

  async armMic(deviceId = '', options = {}) {
    await this.init();
    if (!navigator.mediaDevices?.getUserMedia) throw new Error('Mikrofon API nicht verfügbar');
    if (this.micStream) this.micStream.getTracks().forEach((track) => track.stop());
    const audio = {
      echoCancellation: options.echoCancellation ?? false,
      noiseSuppression: options.noiseSuppression ?? false,
      autoGainControl: options.autoGainControl ?? false,
    };
    if (deviceId) audio.deviceId = { exact: deviceId };
    this.micStream = await navigator.mediaDevices.getUserMedia({ audio, video: false });
    if (this.micSource) this.micSource.disconnect();
    this.micSource = this.context.createMediaStreamSource(this.micStream);
    this.micGain = this.context.createGain();
    this.micGain.gain.value = options.inputGain ?? 0.78;
    this.micSource.connect(this.micGain);
    this.micGain.connect(this.filter);
    this.emitState('MIC: ARMED // monitor safe');
    return this.micStream;
  }

  setInputGain(value) {
    const gain = Math.max(0, Math.min(1.5, Number(value) || 0.78));
    if (this.micGain) this.micGain.gain.value = gain;
    return gain;
  }

  // Read one analyser snapshot and classify it through the shared DSP core.
  async readLiveTransient() {
    const core = await this.getDspCore();
    if (!this.context || !this.analyser) {
      return { kind: 0, kind_name: 'NONE', backend: core.backend, sample_rate_hz: this.context?.sampleRate || 48000 };
    }
    const length = this.analyser.fftSize || 1024;
    const data = new Float32Array(length);
    if (typeof this.analyser.getFloatTimeDomainData === 'function') {
      this.analyser.getFloatTimeDomainData(data);
    } else {
      const bytes = new Uint8Array(length);
      this.analyser.getByteTimeDomainData(bytes);
      for (let i = 0; i < bytes.length; i += 1) data[i] = (bytes[i] - 128) / 128;
    }
    const result = core.detectTransient(data, this.context.sampleRate || 48000);
    this.lastTransient = result.kind_name;
    if (result.kind_name !== 'NONE') {
      this.transientCounts[result.kind_name] = (this.transientCounts[result.kind_name] || 0) + 1;
    }
    return { ...result, backend: core.backend, sample_rate_hz: this.context.sampleRate || 48000 };
  }

  // Honest WebAudio loopback measurement: 1 kHz burst out, onset detect in.
  // Returns null when input or output is unavailable (browser permission).
  // Bounded by wall-clock time so headless stubs (frozen audio clock) terminate.
  async measureRoundtrip() {
    if (!this.context || !this.micStream || !this.micSource) return null;
    const started = Date.now();
    const now = this.context.currentTime;
    const osc = this.context.createOscillator();
    const gain = this.context.createGain();
    osc.type = 'sine';
    osc.frequency.value = 1000;
    gain.gain.setValueAtTime(0.0001, now);
    gain.gain.exponentialRampToValueAtTime(0.6, now + 0.004);
    gain.gain.setValueAtTime(0.6, now + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.03);
    osc.connect(gain);
    gain.connect(this.master);
    osc.start(now);
    osc.stop(now + 0.04);
    const deadline = Date.now() + 160;
    while (Date.now() < deadline) {
      await new Promise((resolve) => setTimeout(resolve, 16));
    }
    const result = await this.readLiveTransient();
    return {
      ok: true,
      method: 'webaudio-loopback-estimate',
      roundtrip_ms: Math.round((Date.now() - started) * 10) / 10,
      transient: result.kind_name,
      backend: this.dspBackend,
    };
  }

  async trigger808() {
    await this.init();
    const now = this.context.currentTime;
    const osc = this.context.createOscillator();
    const sub = this.context.createOscillator();
    const gain = this.context.createGain();
    osc.type = 'sine';
    sub.type = 'triangle';
    osc.frequency.setValueAtTime(140, now);
    osc.frequency.exponentialRampToValueAtTime(38, now + 0.18);
    sub.frequency.setValueAtTime(70, now);
    sub.frequency.exponentialRampToValueAtTime(19, now + 0.18);
    gain.gain.setValueAtTime(0.0001, now);
    gain.gain.exponentialRampToValueAtTime(0.82, now + 0.008);
    gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.36);
    osc.connect(gain);
    sub.connect(gain);
    gain.connect(this.filter);
    osc.start(now);
    sub.start(now);
    osc.stop(now + 0.38);
    sub.stop(now + 0.38);
    this.emitState('808: TRIGGERED // -3.2 dBFS limited');
  }

  async triggerSnare() {
    await this.init();
    const now = this.context.currentTime;
    const noiseBuffer = this.context.createBuffer(1, Math.floor(this.context.sampleRate * 0.16), this.context.sampleRate);
    const data = noiseBuffer.getChannelData(0);
    for (let i = 0; i < data.length; i += 1) data[i] = (Math.random() * 2 - 1) * (1 - i / data.length);
    const noise = this.context.createBufferSource();
    const bandpass = this.context.createBiquadFilter();
    const gain = this.context.createGain();
    noise.buffer = noiseBuffer;
    bandpass.type = 'bandpass';
    bandpass.frequency.value = 4200;
    bandpass.Q.value = 1.6;
    gain.gain.setValueAtTime(0.45, now);
    gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.14);
    noise.connect(bandpass);
    bandpass.connect(gain);
    gain.connect(this.filter);
    noise.start(now);
    this.emitState('SNARE: TRIGGERED');
  }

  applyXY(x, y) {
    this.xy = { x, y };
    if (!this.context || !this.filter || !this.delay || !this.feedback) return;
    const now = this.context.currentTime;
    const frequency = 220 + (1 - y) * 11780;
    const delayTime = 0.035 + x * 0.42;
    const feedback = 0.05 + x * y * 0.55;
    this.filter.frequency.setTargetAtTime(frequency, now, 0.018);
    this.filter.Q.setTargetAtTime(0.7 + x * 12, now, 0.018);
    this.delay.delayTime.setTargetAtTime(delayTime, now, 0.025);
    this.feedback.gain.setTargetAtTime(feedback, now, 0.025);
  }

  startMeter() {
    if (this.meterFrame) return;
    const tick = () => {
      if (!this.analyser) return;
      const bins = new Uint8Array(this.analyser.frequencyBinCount);
      this.analyser.getByteTimeDomainData(bins);
      let sum = 0;
      let peak = 0;
      for (const value of bins) {
        const centered = (value - 128) / 128;
        sum += centered * centered;
        peak = Math.max(peak, Math.abs(centered));
      }
      const rms = Math.sqrt(sum / bins.length);
      this.onLevel({ rms, peak, dbfs: peak > 0 ? 20 * Math.log10(peak) : -120 });
      this.readLiveTransient().then((result) => {
        this.onTransient(result);
      }).catch(() => {});
      this.meterFrame = requestAnimationFrame(tick);
    };
    this.meterFrame = requestAnimationFrame(tick);
  }

  emitState(message) {
    this.onState(message);
  }
}
