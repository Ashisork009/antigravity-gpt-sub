import {createHash, randomUUID} from 'node:crypto';
import {createServer} from 'node:net';
import {mkdir, readFile, realpath, rename, unlink, writeFile} from 'node:fs/promises';
import {join, resolve} from 'node:path';
import {setTimeout as delay} from 'node:timers/promises';

export function vault(stateDir, safeStorage) {
  const root=resolve(stateDir,'subscription');
  const file=join(root,'connection.dpapi');
  const mutex='\\\\.\\pipe\\antigravity-plan-'+createHash('sha256').update(root.toLowerCase()).digest('hex').slice(0,32);
  async function check() {
    await mkdir(root,{recursive:true});
    if ((await realpath(root)).toLowerCase()!==root.toLowerCase()) throw Error('subscription_state_redirected');
    if (!safeStorage?.isEncryptionAvailable()) throw Error('windows_protected_storage_unavailable');
  }
  async function read() {
    await check();
    try {
      const location=await realpath(file);
      if (location.toLowerCase()!==file.toLowerCase()) throw Error('subscription_state_redirected');
      const state=JSON.parse(safeStorage.decryptString(await readFile(file)));
      if (state.version!==1 || typeof state.host!=='string') throw Error('subscription_state_invalid');
      return state;
    } catch(e) {
      if (e.code==='ENOENT') return null;
      throw e;
    }
  }
  async function write(state) {
    await check();
    const tmp=file+'.'+randomUUID()+'.tmp';
    try {
      await writeFile(tmp,safeStorage.encryptString(JSON.stringify(state)),{flag:'wx',mode:0o600});
      await rename(tmp,file);
    } finally { await unlink(tmp).catch(()=>{}); }
  }
  // A named pipe is used solely as an OS-released cross-process mutex. No requests are accepted.
  async function exclusive(action) {
    const server=createServer(socket=>socket.destroy());
    const deadline=Date.now()+35000;
    for (;;) {
      try {
        await new Promise((ok,fail)=>{
          server.once('error',fail);
          server.listen(mutex,()=>{server.off('error',fail);ok();});
        });
        break;
      } catch(e) {
        if (e.code!=='EADDRINUSE' || Date.now()>=deadline) throw Error('subscription_connection_busy');
        await delay(125);
      }
    }
    try {return await action();} finally {await new Promise(done=>server.close(done));}
  }
  return {read,write,exclusive};
}

