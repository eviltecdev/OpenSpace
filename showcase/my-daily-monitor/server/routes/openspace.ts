/**
 * OpenSpace route — reads skill evolution data from the local SQLite DB.
 * GET /api/openspace?action=skills
 */
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { existsSync } from 'node:fs';
import { join } from 'node:path';

const execFileAsync = promisify(execFile);

const DB_PATHS = [
  '/home/claude/OpenSpace/showcase/.openspace/openspace.db',
  '/home/claude/OpenSpace/.openspace/openspace.db',
];

function findDb(): string | null {
  for (const p of DB_PATHS) if (existsSync(p)) return p;
  return null;
}

export async function handleOpenSpaceRequest(
  query: Record<string, string>,
): Promise<unknown> {
  const db = findDb();
  if (!db) throw new Error('openspace.db not found');

  const script = `
import sqlite3, json, sys
conn = sqlite3.connect('${db}')
conn.row_factory = sqlite3.Row
c = conn.cursor()

c.execute("""
  SELECT skill_id, name, lineage_generation, lineage_origin, is_active,
         total_selections, total_completions, lineage_change_summary, first_seen
  FROM skill_records ORDER BY lineage_generation, name
""")
skills = [dict(r) for r in c.fetchall()]

c.execute("SELECT skill_id, parent_skill_id FROM skill_lineage_parents")
edges = [{'child': r[0], 'parent': r[1]} for r in c.fetchall()]

c.execute("""
  SELECT COUNT(*) as total, SUM(total_selections) as selections,
         SUM(total_completions) as completions, MAX(lineage_generation) as max_gen
  FROM skill_records WHERE is_active=1
""")
stats = dict(c.fetchone())

conn.close()
print(json.dumps({'skills': skills, 'edges': edges, 'stats': stats}))
`;

  const { stdout } = await execFileAsync('python3', ['-c', script], { timeout: 10_000 });
  return JSON.parse(stdout.trim());
}
