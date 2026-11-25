// Once verified by the native host check, a sidecar belongs to exactly one LS process instance.
export function ownerLifetime({exists,inspect,onEnd,clock=Date.now,steadyMs=15000,recheckMs=1800,missingMs=9000}) {
  let original,ended=false,busy=false,suspectAt,due=0;
  const cancel=new AbortController();
  function end() {
    if (ended) return;
    ended=true;
    cancel.abort();
    onEnd();
  }
  function pin(owner) {
    if (ended || !Number.isSafeInteger(owner?.pid) || owner.pid<=0 || !/^\d{10,22}$/.test(owner.birth)) return false;
    if (original && (owner.pid!==original.pid || owner.birth!==original.birth)) {end();return false;}
    original??=owner;
    suspectAt=undefined;
    due=clock()+steadyMs;
    return true;
  }
  function tick() {
    if (!original || ended) return;
    if (!exists(original.pid)) {end();return;}
    if (busy || clock()<due) return;
    busy=true;
    Promise.resolve().then(()=>inspect(original,cancel.signal)).then(status=>{
      if (ended) return;
      const now=clock();
      if (status==='gone' || status==='replaced') {end();return;}
      if (status==='same') {suspectAt=undefined;due=now+steadyMs;return;}
      if (status==='missing') {
        suspectAt??=now;
        if (now-suspectAt>=missingMs) {end();return;}
      }
      due=now+recheckMs;
    },()=>{due=clock()+recheckMs;}).finally(()=>{busy=false;});
  }
  return {pin,tick,ready:()=>Boolean(original)&&!ended&&suspectAt===undefined,
    close(){ended=true;cancel.abort();}};
}
