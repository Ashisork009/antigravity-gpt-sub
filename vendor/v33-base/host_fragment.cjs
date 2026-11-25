// This source is part of the version-checked desktop adapter.
let nativeRouterStartup;
async function acquireNativeModelRoute() {
    const app = electron_1.app;
    if (process.platform !== 'win32' || !app.isPackaged || app.getVersion() !== '2.35.1') return;
    if (!nativeRouterStartup) {
        nativeRouterStartup = (async () => {
            const fs = require('node:fs');
            const path = require('node:path');
            const crypto = require('node:crypto');
            async function digest(file) {
                const hash = crypto.createHash('sha256');
                for await (const chunk of fs.createReadStream(file)) hash.update(chunk);
                return hash.digest('hex');
            }
            const base = path.join(app.getPath('home'), '.antigravity-native-model-router');
            const runtime = path.join(base,'runtime','__BUILD_ID__');
            const hashes = __RUNTIME_HASHES__;
            const binaryMatches = await Promise.all([
                digest(process.execPath),digest(path.join(process.resourcesPath,'bin','language_server.exe'))
            ]);
            if (binaryMatches[0] !== '__EXE_HASH__' || binaryMatches[1] !== '__LANG_HASH__') return;
            for (const [name,hash] of Object.entries(hashes)) {
                const file = path.join(runtime,name);
                if (fs.realpathSync.native(file).toLowerCase() !== file.toLowerCase() || await digest(file) !== hash) return;
            }
            const mod = await import(require('node:url').pathToFileURL(path.join(runtime,'restart2351','router','desktop_runtime.mjs')).href);
            const router = await mod.startDesktopRouter({
                stateDir:base,
                fetch:(url,options)=>electron_1.net.fetch(url,options)
            });
            app.once('will-quit',()=>router.close());
            return router.cloud;
        })().catch(()=>{
            console.warn('Native model router unavailable; using original desktop endpoints.');
            return undefined;
        });
    }
    return nativeRouterStartup;
}
