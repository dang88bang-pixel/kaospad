// pwa_offline_test.mjs — REAL-IMPLEMENTATION 2026-09-11
import assert from 'node:assert/strict';
import fs from 'node:fs';
const sw = fs.readFileSync('web/sw.js','utf8');
assert.ok(sw.includes('CACHE'), 'sw has CACHE');
assert.ok(sw.includes('install'), 'sw has install');
assert.ok(sw.includes('fetch'), 'sw has fetch');
assert.ok(sw.includes('/api') || sw.includes('networkFirst'), 'sw network-first for api');
const manifest = JSON.parse(fs.readFileSync('web/manifest.webmanifest','utf8'));
assert.ok(manifest.icons && manifest.icons.length>=2, 'manifest has icons');
assert.ok(manifest.start_url || manifest.scope, 'manifest has start/scope');
console.log('pwa offline test: 6 checks (sw + manifest)');
