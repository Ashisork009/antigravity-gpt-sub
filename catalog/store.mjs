import {DatabaseSync} from 'node:sqlite';
import {compileCatalog,preferences} from './catalog.mjs';

// All writers, including concurrent desktop windows, serialize through SQLite.
// Only store display preferences and opaque slot assignments. No request or account data.
export class CatalogStore {
  constructor(path) {
    this.db=new DatabaseSync(path);
    this.db.exec(`PRAGMA busy_timeout=2500;
      CREATE TABLE IF NOT EXISTS catalog_preferences(
        singleton INTEGER PRIMARY KEY CHECK(singleton=1), revision INTEGER NOT NULL, body TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS catalog_assignments(slug TEXT PRIMARY KEY, slot INTEGER UNIQUE NOT NULL);`);
  }
  read() {
    const row=this.db.prepare('SELECT revision,body FROM catalog_preferences WHERE singleton=1').get();
    return {revision:row?.revision??0,settings:preferences(row?JSON.parse(row.body):undefined)};
  }
  update(settings,expectedRevision) {
    const checked=preferences(settings);
    if(!Number.isSafeInteger(expectedRevision)||expectedRevision<0)throw Error('Expected current preferences revision');
    this.db.exec('BEGIN IMMEDIATE');
    try {
      const before=this.read();
      if(before.revision!==expectedRevision)throw Object.assign(Error('Settings changed in another window'),{status:409});
      const revision=before.revision+1;
      this.db.prepare(`INSERT INTO catalog_preferences VALUES(1,?,?)
        ON CONFLICT(singleton) DO UPDATE SET revision=excluded.revision,body=excluded.body`).run(revision,JSON.stringify(checked));
      this.db.exec('COMMIT');
      return {revision,settings:checked};
    } catch(err) {this.db.exec('ROLLBACK');throw err;}
  }
  assignments() {
    return Object.fromEntries(this.db.prepare('SELECT slug,slot FROM catalog_assignments').all().map(r=>[r.slug,r.slot]));
  }
  compile(catalog,capabilities,enabled=true,settingsOverride) {
    this.db.exec('BEGIN IMMEDIATE');
    try {
      const saved=this.assignments();
      const {revision,settings}=this.read();
      const result=compileCatalog(catalog,capabilities,settingsOverride??settings,saved,enabled);
      const upsert=this.db.prepare('INSERT INTO catalog_assignments(slug,slot) VALUES(?,?) ON CONFLICT(slot) DO UPDATE SET slug=excluded.slug');
      for(const [slug,slot] of Object.entries(result.assignments)) if(saved[slug]!==slot)upsert.run(slug,slot);
      this.db.exec('COMMIT');
      return {...result,revision};
    } catch(err) {this.db.exec('ROLLBACK');throw err;}
  }
  close() {this.db.close();}
}
