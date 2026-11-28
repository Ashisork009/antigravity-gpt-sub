import { ownerLifetime } from './owner_lifetime.mjs';
import { inspectOwner, processExists } from './inspect_owner.mjs';
import { refreshTransition, recordRefresh } from './control.mjs';
import { execFile } from 'node:child_process';
import { readFileSync, realpathSync } from 'node:fs';
import { request } from 'node:http';
import { homedir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { promisify } from 'node:util';
import { leaseRoot, publishLease, readSession, releaseLease } from './gate.mjs';

const exec = promisify(execFile), here = dirname(fileURLToPath(import.meta.url));
const name = 'native-probe-router';
const expected = join(homedir(), '.gemini', 'config', 'plugins', name);
const norm = p => resolve(p).replaceAll('/', '\\').toLowerCase();

function endpoint(raw) {
  const loc = new URL('http://' + raw);
  if (!['localhost', '127.0.0.1', '[::1]'].includes(loc.hostname) || !loc.port || loc.username || loc.password ||
      loc.pathname !== '/' || loc.search || loc.hash) throw Error('Invalid local service');
  return loc;
}

function helperEnv() {
  const environment = Object.fromEntries(['SystemRoot', 'WINDIR', 'LOCALAPPDATA', 'USERPROFILE', 'TEMP', 'TMP', 'PSModulePath', 'PATH']
    .filter(k => process.env[k]).map(k => [k, process.env[k]]));
  return environment;
}

async function ownerIdentity(loc, urls) {
  const environment = helperEnv();
  const powershell = join(environment.SystemRoot, 'System32/WindowsPowerShell/v1.0/powershell.exe');
  const result = await exec(powershell, ['-NoLogo', '-NonInteractive', '-NoProfile', '-File', join(here, 'verify-host.ps1'),
    '-RpcPort', loc.port, '-Cloud', urls.cloud, '-Api', urls.api, '-Inference', urls.inference],
    { windowsHide: true, timeout: 20000, maxBuffer: 8192, env: environment });
  const match = /^(\d+) (\d{10,22})$/.exec(result.stdout.trim());
  if (!match || !Number.isSafeInteger(Number(match[1])) || Number(match[1]) <= 0) throw Error('Unknown service identity');
  return { pid: Number(match[1]), birth: match[2] };
}

export function pluginStatus(loc, {
  configPath = join(homedir(), '.gemini/config/config.json'),
  expectedPath = expected,
  timeoutMs = 10000,
} = {}) {
  const path = '/exa.language_server_pb.LanguageServerService/GetAllPlugins';
  const headers = { 'content-type': 'application/json', 'connect-protocol-version': '1' };
  if (process.env.ANTIGRAVITY_CSRF_TOKEN) headers['x-antigravity-csrf-token'] = process.env.ANTIGRAVITY_CSRF_TOKEN;
  const config = JSON.parse(readFileSync(configPath, 'utf8').replace(/^\uFEFF/, ''));
  if (config?.plugins?.[name]?.enabled === false) return false;
  return new Promise((ok, fail) => {
    const req = request(new URL(path, loc), { method: 'POST', headers, agent: false, signal: AbortSignal.timeout(timeoutMs) }, res => {
      let total = 0;
      const chunks = [];
      res.on('error', fail);
      res.on('data', chunk => {
        total += chunk.length;
        if (total > 2 * 1024 * 1024) { res.destroy(new Error('Plugin list too large')); return; }
        chunks.push(chunk);
      });
      res.on('end', () => {
        if (res.statusCode !== 200) return fail(new Error('Transient plugin status HTTP ' + res.statusCode));
        try {
          const plugins = JSON.parse(Buffer.concat(chunks)).plugins;
          const matches = Array.isArray(plugins) ? plugins.filter(p => p.name === name && typeof p.path === 'string' &&
            p.isGlobal === true && norm(p.path.startsWith('file:') ? fileURLToPath(p.path) : p.path) === norm(expectedPath)) : [];
          // ProtoJSON omits false booleans. Reject other types and duplicates.
          ok(matches.length === 1 && [matches[0].disabled, matches[0].forceDisabled].every(v => v === false || v === undefined));
        } catch (err) { fail(err); }
      });
    });
    req.on('error', fail);
    req.end('{"workspaceUris":[]}');
  });
}

export function refreshCatalog(loc, signal) {
  const headers = { 'content-type': 'application/json', 'connect-protocol-version': '1' };
  if (process.env.ANTIGRAVITY_CSRF_TOKEN) headers['x-antigravity-csrf-token'] = process.env.ANTIGRAVITY_CSRF_TOKEN;
  return new Promise((ok, fail) => {
    const url = new URL('/exa.language_server_pb.LanguageServerService/GetAvailableModels', loc);
    const req = request(url, { method: 'POST', headers, agent: false, signal: AbortSignal.any([signal, AbortSignal.timeout(10000)]) }, res => {
      const status = res.statusCode;
      res.resume();
      res.on('end', () => ok(status));
      res.on('error', fail);
    });
    req.on('error', fail);
    req.end('{"forceRefresh":true}');
  });
}

function panelRevision() {
  try {
    const file = join(homedir(), '.antigravity-native-model-router', 'run', 'plan-panel.json');
    const rev = JSON.parse(readFileSync(file, 'utf8')).revision;
    return typeof rev === 'string' && /^[a-f0-9]{64}$/i.test(rev) ? rev : 'initial';
  } catch { return 'initial'; }
}

export function createRenewController({
  dir,
  loc,
  lifetime,
  updates,
  ownerIdentityFn = ownerIdentity,
  pluginStatusFn = pluginStatus,
  panelRevisionFn = panelRevision,
  readSessionFn = readSession,
  publishLeaseFn = publishLease,
  releaseLeaseFn = releaseLease,
  maxTransientFailures = 3,
  isStopped = () => false,
}) {
  let verifiedEpoch, lsPid, session, transientFailures = 0;
  const release = () => { if (session) releaseLeaseFn(dir, session); };

  async function step() {
    lifetime.tick();
    if (isStopped()) return 'stopped';
    try {
      const active = readSessionFn(dir);
      if (!active) {
        release();
        verifiedEpoch = undefined;
        transientFailures = 0;
        throw Error('No active route');
      }
      if (session?.epoch !== active.epoch) {
        release();
        session = active;
        verifiedEpoch = undefined;
        transientFailures = 0;
      }
      if (verifiedEpoch !== active.epoch) {
        const identity = await ownerIdentityFn(loc, active.urls);
        if (!lifetime.pin(identity)) return 'ended';
        lsPid = identity.pid;
        verifiedEpoch = active.epoch;
      }
      lifetime.tick();
      if (isStopped()) return 'stopped';
      // Do not revoke on a single transient inspectOwner 'missing' (!lifetime.ready());
      // ownerLifetime enforces missingMs and triggers onEnd() -> stop() -> release() if truly gone.
      const enabled = await pluginStatusFn(loc);
      if (isStopped()) return 'stopped';
      transientFailures = 0;
      if (enabled) {
        if (publishLeaseFn(dir, active, process.pid, lsPid)) updates.update(active.epoch + ':' + panelRevisionFn() + ':1');
        return 'published';
      }
      release();
      updates.update(active.epoch + ':' + panelRevisionFn() + ':0');
      return 'disabled';
    } catch {
      transientFailures++;
      if (transientFailures >= maxTransientFailures) {
        release();
        verifiedEpoch = undefined;
        return 'released_after_failures';
      }
      return 'transient_failure';
    }
  }

  return {
    step,
    release,
    verifiedEpoch: () => verifiedEpoch,
    transientFailures: () => transientFailures,
  };
}

async function renew() {
  const ownedDir = join(homedir(), '.gemini', 'config', 'sidecars', 'native-model-router-switch');
  if (process.platform !== 'win32' || norm(realpathSync.native(here)) !== norm(ownedDir)) {
    throw Error('Expected an installed global desktop sidecar');
  }
  const dir = leaseRoot(), loc = endpoint(process.env.ANTIGRAVITY_LS_ADDRESS);
  let stopped = false, controller;
  const updates = refreshTransition({
    report: recordRefresh,
    refresh: async signal => {
      const current = readSession(dir);
      if (!current || current.epoch !== controller?.verifiedEpoch() || !lifetime.pin(await ownerIdentity(loc, current.urls))) return 0;
      signal.throwIfAborted();
      return refreshCatalog(loc, signal);
    }
  });
  const release = () => controller?.release();
  const stop = () => { stopped = true; updates.close(); lifetime.close(); release(); };
  const lifetime = ownerLifetime({ exists: processExists, inspect: (owner, signal) => inspectOwner(loc.port, owner, helperEnv(), signal), onEnd: stop });
  controller = createRenewController({ dir, loc, lifetime, updates, isStopped: () => stopped });
  for (const sig of ['SIGINT', 'SIGTERM']) process.once(sig, stop);
  process.once('exit', release);
  while (!stopped) {
    const outcome = await controller.step();
    if (outcome === 'ended' || stopped) break;
    await new Promise(ok => setTimeout(ok, 1250));
  }
}

if (process.argv[1] && pathToFileURL(resolve(process.argv[1])).href === import.meta.url) await renew();
