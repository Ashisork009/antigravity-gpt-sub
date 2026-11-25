// Fixed-origin HTTP transport reused from the validated 2.35.1 v3.3 adapter.
import { request as httpsRequest } from 'node:https';
import { brotliDecompressSync, gunzipSync, inflateSync } from 'node:zlib';
const cloudHost = 'daily-cloudcode-pa.googleapis.com';
const apiHost = 'generativelanguage.googleapis.com';
const maxBody = 32 * 1024 * 1024;
const gzip = { gzip: gunzipSync, br: brotliDecompressSync, deflate: inflateSync };
const error = (status, message) => Object.assign(new Error(message), { status });

async function collect(stream) {
  const chunks = [];
  let length = 0;
  for await (const chunk of stream) {
    length += chunk.length;
    if (length > maxBody) throw error(413, 'Payload exceeds probe limit');
    chunks.push(chunk);
  }
  return Buffer.concat(chunks);
}

function readJson(bytes, encoding) {
  try {
    const raw = !encoding || encoding === 'identity' ? bytes : gzip[encoding](bytes, { maxOutputLength: maxBody });
    return JSON.parse(raw.toString('utf8'));
  } catch { return undefined; }
}

function forGoogle(headers, catalog) {
  const allowed = new Set(['authorization','content-type','content-encoding','content-length',
    'user-agent','accept','accept-encoding','accept-language','x-client-name','x-client-version','x-client-data']);
  const result = Object.fromEntries(Object.entries(headers).filter(([key]) =>
    allowed.has(key) || /^x-goog-[a-z0-9-]+$/.test(key)));
  if (result['x-goog-api-key'] === 'antigravity-local-fixture-only') delete result['x-goog-api-key'];
  if (catalog) result['accept-encoding'] = 'identity';
  return result;
}

function callGoogle({ origin, path, method, headers, signal, body }) {
  if (![apiHost, cloudHost].includes(origin)) throw error(502, 'Invalid vendor origin');
  return new Promise((accept,reject) => {
    const upstream = httpsRequest({ hostname:origin, port:443, path, method, headers, signal },accept);
    upstream.once('error',reject);
    upstream.setTimeout(120_000, () => upstream.destroy(new Error('Vendor timeout')));
    if (Buffer.isBuffer(body) || body === undefined) upstream.end(body);
    else body.pipe(upstream);
  });
}

export {collect,readJson,forGoogle,callGoogle,error,cloudHost,apiHost};
