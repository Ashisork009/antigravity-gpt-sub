import { execFile } from 'node:child_process';
import { join } from 'node:path';
import { promisify } from 'node:util';

const exec=promisify(execFile);
export function processExists(pid) {
  try {process.kill(pid,0);return true;} catch (err) {return err.code!=='ESRCH';}
}

export async function inspectOwner(port,owner,environment,signal) {
  if (!processExists(owner.pid)) return 'gone';
  const system32=join(environment.SystemRoot,'System32');
  const options={signal,windowsHide:true,timeout:6500,env:{...environment,AGY_OWNED_PID:String(owner.pid)}};
  let birth,network;
  try {
    [birth,network]=await Promise.all([
      exec(join(system32,'WindowsPowerShell/v1.0/powershell.exe'),['-NoLogo','-NoProfile','-NonInteractive','-Command',
        '(Get-Process -Id $env:AGY_OWNED_PID -ErrorAction Stop).StartTime.ToUniversalTime().ToFileTimeUtc()'],
      {...options,maxBuffer:2048}),
      exec(join(system32,'netstat.exe'),['-ano','-p','tcp'],{...options,maxBuffer:8*1024*1024})
    ]);
  } catch {return processExists(owner.pid)?'unknown':'gone';}
  const current=birth.stdout.trim();
  if (!/^\d{10,22}$/.test(current)) return 'unknown';
  if (current!==owner.birth) return 'replaced';
  const locals=new Set(['127.0.0.1:'+port,'[::1]:'+port]);
  const listeners=network.stdout.split(/\r?\n/).map(row=>row.trim().split(/\s+/))
    .filter(c=>c.length===5 && c[0]==='TCP' && locals.has(c[1]) && ['0.0.0.0:0','[::]:0'].includes(c[2]));
  return listeners.some(c=>Number(c[4])===owner.pid)?'same':listeners.length?'replaced':'missing';
}
