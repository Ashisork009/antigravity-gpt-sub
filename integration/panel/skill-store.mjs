import {createHash,randomUUID} from 'node:crypto';
import {createServer} from 'node:net';
import {lstatSync,mkdirSync,readFileSync,readdirSync,realpathSync,renameSync,rmSync,writeFileSync} from 'node:fs';
import {homedir,tmpdir} from 'node:os';
import {dirname,join,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';

export const SKILL_SLUG='gpt-swarm-workflow';
export const SUPPORTED_LANGUAGES=Object.freeze(['zh','en']);
export const MARKER_FILE='.managed-by-antigravity-gpt-sub.json';
const owner='antigravity-gpt-sub',windows=process.platform==='win32';
const fileName=/^(?:SKILL\.md|references\/[^<>:"/\\|?*\x00-\x1f]+\.md)$/;
const hex=/^[a-f0-9]{64}$/;
const digest=bytes=>createHash('sha256').update(bytes).digest('hex');
const norm=path=>windows?path.toLowerCase():path;
const error=(message,status=400)=>Object.assign(Error(message),{status});
const conflict=()=>error('skill_directory_conflict',409);
function stat(path){
  try{return lstatSync(path);}catch(e){if(e.code!=='ENOENT')throw e;return null;}
}
function direct(path,type){
  const entry=stat(path);
  if(entry&&(entry.isSymbolicLink()||!entry[type]()||norm(realpathSync.native(path))!==norm(path)))throw conflict();
  return entry;
}
function verifyDirectory(path){
  const entry=direct(path,'isDirectory');
  if(!entry){
    const parent=dirname(path);
    if(parent===path)throw conflict();
    verifyDirectory(parent);
  }
  return entry;
}
function ensureDirectory(path){
  if(verifyDirectory(path))return;
  mkdirSync(path,{recursive:true});
  direct(path,'isDirectory');
}
function validFiles(files){
  return files&&typeof files==='object'&&!Array.isArray(files)&&Object.hasOwn(files,'SKILL.md')&&
    Object.entries(files).every(([name,hash])=>fileName.test(name)&&typeof hash==='string'&&hex.test(hash))&&
    new Set(Object.keys(files).map(norm)).size===Object.keys(files).length;
}
function read(path){
  if(!direct(path,'isFile'))throw Error('Missing skill file');
  return readFileSync(path);
}
function manifest(templates){
  const path=join(templates,'manifest.json');
  if(stat(path)){
    const data=JSON.parse(read(path));
    if(data?.schema!==1||data.slug!==SKILL_SLUG||typeof data.version!=='string'||!data.version||
      !SUPPORTED_LANGUAGES.every(language=>validFiles(data.languages?.[language]?.files)))throw Error('Invalid skill manifest');
    return data;
  }
  const languages=Object.fromEntries(SUPPORTED_LANGUAGES.map(language=>{
    const dir=join(templates,language),refs=join(dir,'references');
    const paths=['SKILL.md'];
    if(direct(refs,'isDirectory'))for(const name of readdirSync(refs).sort())if(fileName.test('references/'+name))paths.push('references/'+name);
    return [language,{files:Object.fromEntries(paths.map(name=>[name,digest(read(join(dir,name)))]))}];
  }));
  return {version:'dev',languages};
}
function installed(root,target){
  try{
    verifyDirectory(root);
    if(!direct(target,'isDirectory'))return {kind:'absent'};
    const raw=read(join(target,MARKER_FILE)),marker=JSON.parse(raw);
    if(marker?.schema!==1||marker.owner!==owner||marker.slug!==SKILL_SLUG||!SUPPORTED_LANGUAGES.includes(marker.language)||
      typeof marker.templateVersion!=='string'||!marker.templateVersion||!validFiles(marker.files))throw conflict();
    const names=[];
    for(const name of readdirSync(target)){
      if(name==='references'){
        const refs=join(target,name);
        if(!direct(refs,'isDirectory'))throw conflict();
        const entries=readdirSync(refs);
        if(!entries.length)throw conflict();
        names.push(...entries.map(file=>'references/'+file));
      }else if(name!==MARKER_FILE)names.push(name);
    }
    if(names.length!==Object.keys(marker.files).length||
      !names.every(name=>Object.hasOwn(marker.files,name)&&digest(read(join(target,name)))===marker.files[name]))throw conflict();
    return {kind:'managed',marker,hash:digest(raw)};
  }catch{return {kind:'conflict'};}
}

export function skillStore(stateDir,{skillsDir=join(homedir(),'.gemini','config','skills'),
  templatesDir=fileURLToPath(new URL('./bundled-skills',import.meta.url))}={}){
  const state=resolve(stateDir),prefs=join(state,'collaboration-skill.json');
  const root=resolve(skillsDir),parent=dirname(root),target=join(root,SKILL_SLUG),templates=resolve(templatesDir);
  const lockName='antigravity-skill-pref-'+digest(norm(target)).slice(0,28);
  const mutex=windows?'\\\\.\\pipe\\'+lockName:join(tmpdir(),lockName+'.sock');
  function current(){
    verifyDirectory(state);
    const raw=direct(prefs,'isFile')?readFileSync(prefs):null;
    const settings=raw?JSON.parse(raw):{version:1,enabled:false,language:'zh'};
    if(settings?.version!==1||typeof settings.enabled!=='boolean'||!SUPPORTED_LANGUAGES.includes(settings.language))throw Error('Invalid skill preferences');
    const tree=installed(root,target);
    const stamp=createHash('sha256').update(raw??'').update('\0'+tree.kind+':'+(tree.hash??'')).digest('hex');
    return {settings,tree,stamp};
  }
  function snapshot(){
    const {settings:{enabled,language},tree,stamp}=current(),bundledVersion=manifest(templates).version;
    const installedVersion=tree.marker?.templateVersion??null,installedLanguage=tree.marker?.language??null;
    const status=tree.kind==='conflict'?'conflict':tree.kind==='absent'?(enabled?'missing':'off'):
      enabled&&(installedVersion!==bundledVersion||installedLanguage!==language)?'outdated':'active';
    return {slug:SKILL_SLUG,enabled,language,status,installedVersion,installedLanguage,bundledVersion,stamp,languages:[...SUPPORTED_LANGUAGES]};
  }
  async function update(data){
    const lock=createServer(socket=>socket.destroy());
    try{await new Promise((ok,no)=>{lock.once('error',no);lock.listen(mutex,ok);});}
    catch{throw error('skill_changed',409);}
    let stage,pending;
    try{
      const {stamp,tree}=current(),{enabled,language,sync}=data??{};
      if(stamp!==data?.stamp)throw error('skill_changed',409);
      if(typeof enabled!=='boolean'||!SUPPORTED_LANGUAGES.includes(language)||(sync!==undefined&&typeof sync!=='boolean'))
        throw error('invalid_skill_settings');
      if(tree.kind==='conflict')throw conflict();
      const {version,languages}=manifest(templates);
      if(enabled&&(sync||tree.marker?.templateVersion!==version||tree.marker?.language!==language)){
        const files=languages[language].files;
        ensureDirectory(parent);
        const fresh=join(parent,'.gpt-sub-skill-stage-'+randomUUID());
        mkdirSync(fresh);stage=fresh;
        for(const [name,hash] of Object.entries(files)){
          const bytes=read(join(templates,language,name)),dest=join(stage,name);
          if(digest(bytes)!==hash)throw Error('Skill template differs from manifest');
          mkdirSync(dirname(dest),{recursive:true});writeFileSync(dest,bytes,{flag:'wx'});
        }
        writeFileSync(join(stage,MARKER_FILE),JSON.stringify({schema:1,owner,slug:SKILL_SLUG,language,templateVersion:version,files}),{flag:'wx'});
      }
      ensureDirectory(state);
      pending=prefs+'.'+randomUUID()+'.tmp';
      writeFileSync(pending,JSON.stringify({version:1,enabled,language}),{flag:'wx',mode:0o600});
      if(current().stamp!==stamp)throw error('skill_changed',409);
      if(stage)ensureDirectory(root);
      let old,mounted=false;
      try{
        if(tree.kind==='managed'&&(!enabled||stage)){
          const backup=join(parent,'.gpt-sub-skill-old-'+randomUUID());
          renameSync(target,backup);old=backup;
          if(installed(root,old).hash!==tree.hash)throw conflict();
        }
        if(stage){renameSync(stage,target);mounted=true;}
        renameSync(pending,prefs);pending=null;
      }catch(e){
        if(mounted)renameSync(target,stage);
        if(old)renameSync(old,target);
        throw e;
      }
      if(old)rmSync(old,{recursive:true,force:true});
      return snapshot();
    }finally{
      try{if(pending)rmSync(pending,{force:true});}
      finally{
        try{if(stage)rmSync(stage,{recursive:true,force:true});}
        finally{await new Promise(ok=>lock.close(ok));}
      }
    }
  }
  return {snapshot,update};
}
