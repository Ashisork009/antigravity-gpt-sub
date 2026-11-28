import { writeFileSync, renameSync, mkdirSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';

export function refreshTransition({ refresh, report, clock = Date.now, retryMs = 2500, renewAfterMs = 480000 }) {
  let state, pending, active, attempt = 0, retryAt = 0, renewAt = Infinity, closed = false;
  function update(next) {
    if (closed) return;
    if (next !== state) { state = next; pending = next; attempt = 0; retryAt = 0; renewAt = Infinity; active?.abort(); }
    else if (next.endsWith(':1') && !pending && !active && clock() >= renewAt) { pending = next; attempt = 0; retryAt = 0; }
    if (!pending || active || clock() < retryAt) return;
    const current = pending, controller = new AbortController();
    active = controller;
    const n = ++attempt;
    Promise.resolve().then(() => refresh(controller.signal)).then(status => {
      if (closed || controller.signal.aborted || current !== pending) return;
      report({ status, attempt: n, epoch: current.split(':')[0], revision: current.split(':')[1], enabled: current.endsWith(':1') });
      if (status === 200 || n >= 4) { pending = undefined; renewAt = clock() + (status === 200 ? renewAfterMs : 30000); }
      else retryAt = clock() + retryMs;
    }, () => {
      if (closed || controller.signal.aborted || current !== pending) return;
      report({ status: 0, attempt: n, epoch: current.split(':')[0], revision: current.split(':')[1], enabled: current.endsWith(':1') });
      if (n >= 4) { pending = undefined; renewAt = clock() + 30000; } else retryAt = clock() + retryMs;
    }).finally(() => { active = undefined; });
  }
  return { update, close() { closed = true; active?.abort(); } };
}

export function recordRefresh(fields) {
  try {
    const dir = join(homedir(), '.antigravity-native-model-router', 'run');
    mkdirSync(dir, { recursive: true });
    const p = join(dir, 'refresh.json');
    writeFileSync(p + '.tmp', JSON.stringify({ time: new Date().toISOString(), ...fields }));
    renameSync(p + '.tmp', p);
  } catch { /* A diagnostic reader must not interrupt lease renewal. */ }
}
