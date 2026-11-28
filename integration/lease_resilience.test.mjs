import assert from 'node:assert/strict';
import fs, { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { createServer } from 'node:http';
import { syncBuiltinESMExports } from 'node:module';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { once } from 'node:events';
import { appVersion, clockSkewMs, openGate, publishLease, readRecord, ttlMs } from './sidecar/gate.mjs';
import { ownerLifetime } from './sidecar/owner_lifetime.mjs';
import { createRenewController, pluginStatus } from './sidecar/renew.mjs';

function tempDir(t) {
  const dir = mkdtempSync(join(tmpdir(), 'antigravity-lease-resilience-'));
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  return dir;
}

const sampleUrls = {
  cloud: 'http://127.0.0.1:41001',
  api: 'http://127.0.0.1:41002',
  inference: 'http://127.0.0.1:41003',
};

test('gate enforces 30s TTL, 5s NTP rollback tolerance, and retries transient Windows NTFS read contention', t => {
  assert.equal(ttlMs, 30000);
  assert.equal(clockSkewMs, 5000);
  assert.equal(appVersion, '2.36.0');
  const dir = tempDir(t);
  let now = 1_000_000;
  const gate = openGate(sampleUrls, dir, { clock: () => now });
  t.after(() => gate.close());

  assert.equal(gate.enabled(), false);
  assert.equal(publishLease(dir, gate.session, process.pid, process.pid, now), true);
  assert.equal(gate.enabled(), true);

  // Valid up to 29999ms, expired at 30000ms.
  now = 1_000_000 + 29_999;
  assert.equal(gate.enabled(), true);
  now = 1_000_000 + 30_000;
  assert.equal(gate.enabled(), false);

  // Clock rollback tolerance: +4500ms ahead passes, +5001ms fails closed.
  now = 1_000_000 - 4_500;
  assert.equal(gate.enabled(), true);
  now = 1_000_000 - 5_001;
  assert.equal(gate.enabled(), false);

  // Simulated Windows NTFS EBUSY / EPERM contention on readRecord recovers within 3 attempts.
  now = 1_000_000;
  const leasePath = join(dir, 'lease-' + gate.session.epoch + '.json');
  const origRead = fs.readFileSync;
  let injected = 0;
  fs.readFileSync = (target, encoding) => {
    if (target === leasePath && injected < 2) {
      injected++;
      throw Object.assign(new Error('busy'), { code: injected === 1 ? 'EBUSY' : 'EPERM' });
    }
    return origRead(target, encoding);
  };
  syncBuiltinESMExports();
  try {
    const parsed = readRecord(leasePath);
    assert.equal(parsed?.epoch, gate.session.epoch);
    assert.equal(injected, 2);
  } finally {
    fs.readFileSync = origRead;
    syncBuiltinESMExports();
  }
});

test('ownerLifetime waits full 20s missingMs window before ending and immediately ends on gone/replaced', async () => {
  let now = 10_000;
  let ended = 0;
  let inspectResult = 'missing';
  const life = ownerLifetime({
    exists: () => true,
    inspect: async () => inspectResult,
    onEnd: () => { ended++; },
    clock: () => now,
  });
  assert.equal(life.pin({ pid: 12345, birth: '133999999990000000' }), true);
  assert.equal(life.ready(), true);

  // Trigger first inspection at steadyMs (15s) -> missing starts suspectAt at 25_000.
  now = 25_000;
  life.tick();
  await new Promise(r => setImmediate(r));
  assert.equal(life.ready(), false);
  assert.equal(life.ended(), false);
  assert.equal(ended, 0);

  // At 19s elapsed (44_000), still within 20s missingMs -> must NOT end.
  now = 44_000;
  life.tick();
  await new Promise(r => setImmediate(r));
  assert.equal(life.ended(), false);
  assert.equal(ended, 0);

  // Recovery ('same') clears suspectAt and restores ready().
  inspectResult = 'same';
  now = 44_000 + 1_800;
  life.tick();
  await new Promise(r => setImmediate(r));
  assert.equal(life.ready(), true);
  assert.equal(ended, 0);

  // New missing sequence reaching full 20s triggers onEnd.
  inspectResult = 'missing';
  now += 15_000;
  life.tick();
  await new Promise(r => setImmediate(r));
  assert.equal(ended, 0);
  now += 20_000;
  life.tick();
  await new Promise(r => setImmediate(r));
  assert.equal(life.ended(), true);
  assert.equal(ended, 1);
});

test('pluginStatus distinguishes explicit disable from transient HTTP 503 and timeout', async t => {
  const dir = tempDir(t);
  const configPath = join(dir, 'config.json');
  const expectedPath = join(dir, 'plugins', 'native-probe-router');
  writeFileSync(configPath, JSON.stringify({ plugins: { 'native-probe-router': { enabled: true } } }));

  let mode = 'ok';
  const server = createServer((req, res) => {
    if (mode === 'hang') return;
    if (mode === '503') { res.writeHead(503); res.end('busy'); return; }
    res.writeHead(200, { 'content-type': 'application/json' });
    const plugin = mode === 'disabled'
      ? { name: 'native-probe-router', path: expectedPath, isGlobal: true, disabled: true }
      : { name: 'native-probe-router', path: expectedPath, isGlobal: true };
    res.end(JSON.stringify({ plugins: [plugin] }));
  });
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  t.after(() => { server.closeAllConnections(); server.close(); });
  const loc = new URL('http://127.0.0.1:' + server.address().port);

  assert.equal(await pluginStatus(loc, { configPath, expectedPath, timeoutMs: 300 }), true);

  mode = 'disabled';
  assert.equal(await pluginStatus(loc, { configPath, expectedPath, timeoutMs: 300 }), false);

  mode = '503';
  await assert.rejects(() => pluginStatus(loc, { configPath, expectedPath, timeoutMs: 300 }), /Transient plugin status HTTP 503/);

  mode = 'hang';
  await assert.rejects(() => pluginStatus(loc, { configPath, expectedPath, timeoutMs: 120 }));

  // Explicit config.json enabled:false short-circuits immediately to false without waiting on HTTP.
  writeFileSync(configPath, JSON.stringify({ plugins: { 'native-probe-router': { enabled: false } } }));
  assert.equal(await pluginStatus(loc, { configPath, expectedPath, timeoutMs: 120 }), false);
});

test('renew controller survives 2 transient timeouts and single missing without dropping lease, fails closed on 3rd failure or explicit disable', async t => {
  const dir = tempDir(t);
  const gate = openGate(sampleUrls, dir);
  t.after(() => gate.close());

  let identityCalls = 0;
  let statusAction = async () => true;
  const updateEvents = [];
  let readyFlag = true;
  const lifetime = {
    pin: () => true,
    tick: () => {},
    ready: () => readyFlag,
    ended: () => false,
    close: () => {},
  };

  const controller = createRenewController({
    dir,
    loc: new URL('http://127.0.0.1:45555'),
    lifetime,
    updates: { update: v => updateEvents.push(v) },
    ownerIdentityFn: async () => { identityCalls++; return { pid: process.pid, birth: '133999999990000000' }; },
    pluginStatusFn: () => statusAction(),
    panelRevisionFn: () => 'rev1',
  });

  // Initial publish establishes lease.
  assert.equal(await controller.step(), 'published');
  assert.equal(gate.enabled(), true);
  assert.equal(identityCalls, 1);

  // Single inspectOwner 'missing' (!lifetime.ready()) must NOT prematurely release lease.
  readyFlag = false;
  assert.equal(await controller.step(), 'published');
  assert.equal(gate.enabled(), true);
  readyFlag = true;

  // 2 consecutive TimeoutErrors preserve lease AND verifiedEpoch (no ownerIdentity churn).
  statusAction = async () => { throw Object.assign(new Error('timeout'), { name: 'TimeoutError' }); };
  assert.equal(await controller.step(), 'transient_failure');
  assert.equal(gate.enabled(), true);
  assert.equal(controller.verifiedEpoch(), gate.session.epoch);
  assert.equal(await controller.step(), 'transient_failure');
  assert.equal(gate.enabled(), true);
  assert.equal(controller.verifiedEpoch(), gate.session.epoch);

  // Recovery on 3rd tick resets transientFailures without re-running PowerShell verify-host.
  statusAction = async () => true;
  assert.equal(await controller.step(), 'published');
  assert.equal(gate.enabled(), true);
  assert.equal(controller.transientFailures(), 0);
  assert.equal(identityCalls, 1);

  // 3 consecutive failures fail closed: release lease and clear verifiedEpoch.
  statusAction = async () => { throw new Error('LS unreachable'); };
  assert.equal(await controller.step(), 'transient_failure');
  assert.equal(await controller.step(), 'transient_failure');
  assert.equal(await controller.step(), 'released_after_failures');
  assert.equal(gate.enabled(), false);
  assert.equal(controller.verifiedEpoch(), undefined);

  // Recover again, then explicit plugin disable must revoke IMMEDIATELY (zero grace ticks).
  statusAction = async () => true;
  assert.equal(await controller.step(), 'published');
  assert.equal(gate.enabled(), true);
  assert.equal(identityCalls, 2);

  statusAction = async () => false;
  assert.equal(await controller.step(), 'disabled');
  assert.equal(gate.enabled(), false);
  assert.ok(updateEvents.at(-1).endsWith(':0'));
});
