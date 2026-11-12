/* SQLite persistence: session snapshot, undo stack and applied-action ids. */

import { Database } from "bun:sqlite";
import { mkdirSync } from "node:fs";
import path from "node:path";
import type { SessionState } from "../lib/types";

export interface Snapshot {
  label: string;
  at: number;
  state: SessionState;
}

export interface SessionRecord {
  state: SessionState;
  history: Snapshot[];
  hostToken: string;
}

const MAX_HISTORY = 50;

export class Store {
  private db: Database;

  constructor(file: string) {
    mkdirSync(path.dirname(file), { recursive: true });
    this.db = new Database(file, { create: true });
    this.db.run("PRAGMA journal_mode = WAL");
    this.db.run(`
      CREATE TABLE IF NOT EXISTS sessions (
        code TEXT PRIMARY KEY,
        id TEXT NOT NULL,
        host_token TEXT NOT NULL,
        state TEXT NOT NULL,
        history TEXT NOT NULL,
        updated_at INTEGER NOT NULL
      )
    `);
    this.db.run(`
      CREATE TABLE IF NOT EXISTS applied_actions (
        session_id TEXT NOT NULL,
        action_id TEXT NOT NULL,
        at INTEGER NOT NULL,
        PRIMARY KEY (session_id, action_id)
      )
    `);
  }

  create(code: string, hostToken: string, state: SessionState): void {
    this.db
      .query(
        "INSERT INTO sessions (code, id, host_token, state, history, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
      )
      .run(code, state.id, hostToken, JSON.stringify(state), JSON.stringify([]), state.updatedAt);
  }

  get(code: string): SessionRecord | null {
    const row = this.db
      .query<{ host_token: string; state: string; history: string }, [string]>(
        "SELECT host_token, state, history FROM sessions WHERE code = ?",
      )
      .get(code);
    if (!row) return null;
    return {
      hostToken: row.host_token,
      state: JSON.parse(row.state) as SessionState,
      history: JSON.parse(row.history) as Snapshot[],
    };
  }

  save(record: SessionRecord, now: number): void {
    const history = record.history.slice(-MAX_HISTORY);
    this.db
      .query("UPDATE sessions SET state = ?, history = ?, updated_at = ? WHERE code = ?")
      .run(JSON.stringify(record.state), JSON.stringify(history), now, record.state.code);
    record.history = history;
  }

  /** True when this action id had not been applied before. */
  markAction(sessionId: string, actionId: string, now: number): boolean {
    const result = this.db
      .query(
        "INSERT OR IGNORE INTO applied_actions (session_id, action_id, at) VALUES (?, ?, ?)",
      )
      .run(sessionId, actionId, now);
    if (result.changes > 0) {
      this.db
        .query("DELETE FROM applied_actions WHERE session_id = ? AND at < ?")
        .run(sessionId, now - 24 * 60 * 60 * 1000);
      return true;
    }
    return false;
  }
}
