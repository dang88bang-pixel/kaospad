export class WebAudioCypherEngine {
  constructor({ onState = () => {}, onLevel = () => {} } = {}) {
    this.onState = onState;
    this.onLevel = onLevel;
    this.context = null;
    this.master = null;
    this.filter = null;
    this.delay = null;
    this.feedback = null;
    this.limiter = null;
    this.analyser = null;
    this.micStream = null;
    this.micSource = null;
    this.meterFrame = 0;
    this.xy = { x: 0.5, y: 0.5 };
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

  async armMic(deviceId = '') {
    await this.init();
    if (!navigator.mediaDevices?.getUserMedia) throw new Error('Mikrofon API nicht verfügbar');
    if (this.micStream) this.micStream.getTracks().forEach((track) => track.stop());
    const audio = deviceId ? { deviceId: { exact: deviceId }, echoCancellation: false, noiseSuppression: false, autoGainControl: false } : { echoCancellation: false, noiseSuppression: false, autoGainControl: false };
    this.micStream = await navigator.mediaDevices.getUserMedia({ audio, video: false });
    if (this.micSource) this.micSource.disconnect();
    this.micSource = this.context.createMediaStreamSource(this.micStream);
    this.micSource.connect(this.filter);
    this.emitState('MIC: ARMED // monitor safe');
    return this.micStream;
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
      this.meterFrame = requestAnimationFrame(tick);
    };
    this.meterFrame = requestAnimationFrame(tick);
  }

  emitState(message) {
    this.onState(message);
  }
}
