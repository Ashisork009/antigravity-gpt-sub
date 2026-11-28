import { homedir } from 'node:os';
import { randomUUID } from 'node:crypto';
import { execFile } from 'node:child_process';
import { existsSync, lstatSync, mkdirSync, readFileSync, realpathSync, renameSync, unlinkSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { promisify } from 'node:util';

export const ttlMs = 30000;
export const clockSkewMs = 5000;
const exec = promisify(execFile);
export const appVersion = '2.36.0';
const uuid = /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/;
const retryableRead = new Set(['EPERM', 'EBUSY', 'EACCES', 'ENOENT']);
const retryableWrite = new Set(['EPERM', 'EBUSY', 'EACCES']);
const sleepBuffer = typeof SharedArrayBuffer === 'function' ? new Int32Array(new SharedArrayBuffer(4)) : null;

function pauseMs(ms) {
  if (sleepBuffer && ms > 0) {
    try { Atomics.wait(sleepBuffer, 0, 0, ms); } catch {}
  }
}

export function leaseRoot() {
  if (process.platform !== 'win32') throw Error('Windows LocalAppData required');
  return join(homedir(), '.antigravity-native-model-router', 'lease-v1');
}

export function readRecord(path) {
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      const stat = lstatSync(path);
      if (!stat.isFile() || stat.nlink !== 1 || stat.size > 4096) return null;
      return JSON.parse(readFileSync(path, 'utf8'));
    } catch (err) {
      if (attempt < 2 && retryableRead.has(err?.code)) {
        if (err.code !== 'ENOENT') pauseMs(5 * (attempt + 1));
        continue;
      }
      return null;
    }
  }
  return null;
}

function writeRecord(path, value) {
  const tmp = path + '.' + randomUUID() + '.tmp';
  try {
    writeFileSync(tmp, JSON.stringify(value), { flag: 'wx', mode: 0o600 });
    for (let attempt = 0; attempt < 3; attempt++) {
      try {
        renameSync(tmp, path);
        return;
      } catch (err) {
        if (attempt < 2 && retryableWrite.has(err?.code)) {
          pauseMs(5 * (attempt + 1));
          continue;
        }
        throw err;
      }
    }
  } finally {
    if (existsSync(tmp)) {
      try { unlinkSync(tmp); } catch {}
    }
  }
}

export function validSession(session) {
  const urls = Object.values(session?.urls ?? {});
  return session?.version === appVersion && uuid.test(session?.epoch) && urls.length === 3 &&
    new Set(urls).size === 3 && ['cloud', 'api', 'inference'].every(k => {
      try {
        const value = session.urls[k], u = new URL(value);
        return u.protocol === 'http:' && u.hostname === '127.0.0.1' && u.port && value === u.origin;
      } catch { return false; }
    });
}

export function readSession(dir) {
  const session = readRecord(join(dir, 'active.json'));
  return validSession(session) ? session : null;
}

export function publishLease(dir, session, leasePid = process.pid, hostPid, now = Date.now()) {
  if (!validSession(session) || readSession(dir)?.epoch !== session.epoch) return false;
  writeRecord(join(dir, 'lease-' + session.epoch + '.json'), { epoch: session.epoch, pid: leasePid, hostPid, time: now });
  return true;
}

export function releaseLease(dir, session, leasePid = process.pid) {
  if (!validSession(session)) return;
  const path = join(dir, 'lease-' + session.epoch + '.json');
  if (readRecord(path)?.pid === leasePid) {
    try { unlinkSync(path); } catch (err) { if (err?.code !== 'ENOENT') throw err; }
  }
}

export function openGate(urls, dir = leaseRoot(), { clock = Date.now } = {}) {
  mkdirSync(dir, { recursive: true });
  if (realpathSync.native(dir).toLowerCase() !== resolve(dir).toLowerCase()) throw Error('Redirected lease directory');
  const session = { version: appVersion, epoch: randomUUID(), urls };
  if (!validSession(session)) throw Error('Invalid local endpoints');
  const active = join(dir, 'active.json'), lease = join(dir, 'lease-' + session.epoch + '.json');
  writeRecord(active, session);
  let closed = false;
  function enabled() {
    if (closed || readSession(dir)?.epoch !== session.epoch) return false;
    const beat = readRecord(lease);
    const now = clock();
    if (beat?.epoch !== session.epoch || !Number.isSafeInteger(beat.pid) || beat.pid <= 0 ||
      !Number.isSafeInteger(beat.time) || beat.time > now + clockSkewMs || now - beat.time >= ttlMs) return false;
    try { process.kill(beat.pid, 0); return true; } catch { return false; }
  }
  return {
    session,
    enabled,
    async authorizeProbe(socket) {
      if (!enabled() || process.platform !== 'win32' || socket.remoteAddress !== '127.0.0.1' ||
          socket.localAddress !== '127.0.0.1') return false;
      const beat = readRecord(lease);
      if (!Number.isSafeInteger(beat?.hostPid) || beat.hostPid <= 0) return false;
      const client = '127.0.0.1:' + socket.remotePort, server = '127.0.0.1:' + socket.localPort;
      try {
        const { stdout } = await exec(join(process.env.SystemRoot, 'System32/netstat.exe'), ['-ano', '-p', 'tcp'],
          { windowsHide: true, timeout: 8000, maxBuffer: 8 * 1024 * 1024 });
        const match = stdout.split(/\r?\n/).some(line => {
          const cols = line.trim().split(/\s+/);
          return cols[0] === 'TCP' && cols[1] === client && cols[2] === server && Number(cols.at(-1)) === beat.hostPid;
        });
        return match && !socket.destroyed && enabled() && readRecord(lease)?.hostPid === beat.hostPid;
      } catch { return false; }
    },
    close() {
      closed = true;
      if (existsSync(lease)) {
        try { unlinkSync(lease); } catch (err) { if (err?.code !== 'ENOENT') throw err; }
      }
      // Keep the small epoch descriptor. A new router publishes a different
      // epoch atomically; a stopped router never removes a newer descriptor.
    }
  };
}
