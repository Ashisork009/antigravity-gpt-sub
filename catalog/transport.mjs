// Fixed-origin HTTP transport reused from the validated desktop adapter.
import { request as httpsRequest } from 'node:https';
import { brotliDecompressSync, gunzipSync, inflateSync } from 'node:zlib';
const cloudHost = 'daily-cloudcode-pa.googleapis.com';
const apiHost = 'generativelanguage.googleapis.com';
const maxBody = 256 * 1024 * 1024;
const gzip = { gzip: gunzipSync, br: brotliDecompressSync, deflate: inflateSync };
const error = (status, message, reason) => Object.assign(new Error(message), reason ? { status, reason } : { status });
const tooLarge = () => error(413, 'Payload exceeds local router limit', 'request_payload_too_large');

async function collect(stream, limit = maxBody) {
  const chunks = [];
  let length = 0;
  for await (const chunk of stream) {
    length += chunk.length;
    if (length > limit) throw tooLarge();
    chunks.push(chunk);
  }
  return Buffer.concat(chunks);
}

function readJson(bytes, encoding, limit = maxBody) {
  let raw;
  try {
    if (!encoding || encoding === 'identity') {
      if (bytes.length > limit) throw tooLarge();
      raw = bytes;
    } else {
      const decompress = gzip[encoding];
      if (!decompress) return undefined;
      raw = decompress(bytes, { maxOutputLength: limit });
    }
  } catch (err) {
    if (err?.status === 413 || err?.code === 'ERR_BUFFER_TOO_LARGE' || err?.code === 'ERR_MEMORY_ALLOCATION_FAILED') throw tooLarge();
    return undefined;
  }
  try {
    return JSON.parse(raw.toString('utf8'));
  } catch (err) {
    if (err?.code === 'ERR_STRING_TOO_LONG') throw tooLarge();
    return undefined;
  }
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

export {collect,readJson,forGoogle,callGoogle,error,cloudHost,apiHost,maxBody};
