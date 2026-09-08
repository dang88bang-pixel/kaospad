#!/usr/bin/env node
const avatars = 8;
const frames = 360;
const start = process.hrtime.bigint();
let checksum = 0;
for (let frame = 0; frame < frames; frame += 1) {
  for (let avatar = 0; avatar < avatars; avatar += 1) {
    for (let bone = 0; bone < 33; bone += 1) {
      checksum += Math.sin((frame + avatar * 7 + bone * 3) / 60.0);
    }
  }
}
const elapsedSeconds = Number(process.hrtime.bigint() - start) / 1e9;
const fps = frames / Math.max(elapsedSeconds, 1e-6);
console.log(JSON.stringify({ avatars, frames, fps, checksum: Number(checksum.toFixed(3)) }));
if (fps < 55) process.exit(1);
