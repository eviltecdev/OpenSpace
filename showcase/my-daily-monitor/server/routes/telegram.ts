/**
 * Telegram ↔ Dashboard sync route.
 * GET /api/telegram-history?since=<ISO timestamp>
 * Returns recent messages from the shared OpenClaw session.
 */
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import type { IncomingHttpHeaders } from 'node:http';
import { existsSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';

const execFileAsync = promisify(execFile);
const SESSION_DIR = `${process.env.HOME}/.openclaw/agents/main/sessions`;

function getLatestSessionFile(): string | null {
  if (!existsSync(SESSION_DIR)) return null;
  const files = readdirSync(SESSION_DIR)
    .filter(f => f.endsWith('.jsonl'))
    .map(f => ({ f, mtime: statSync(join(SESSION_DIR, f)).mtimeMs }))
    .sort((a, b) => b.mtime - a.mtime);
  return files[0] ? join(SESSION_DIR, files[0].f) : null;
}

const PARSE_SCRIPT = `
import sys, json, ast

session_file = sys.argv[1]
since = sys.argv[2] if len(sys.argv) > 2 else ''

messages = []
with open(session_file) as f:
    for line in f:
        line = line.strip()
        if not line: continue
        try:
            entry = json.loads(line)
            if entry.get('type') != 'message': continue
            ts = entry.get('timestamp', '')
            if since and ts <= since: continue
            msg = ast.literal_eval(entry['message'])
            role = msg.get('role')
            if role not in ('user', 'assistant'): continue
            content = msg.get('content', '')
            text = ''
            if isinstance(content, str):
                text = content
            elif isinstance(content, list):
                for c in content:
                    if isinstance(c, dict) and c.get('type') == 'text':
                        text = c.get('text', '')
                        break
            if not text or not text.strip(): continue
            # Skip internal context dumps from dashboard
            if text.startswith('Context data:') or text.startswith('[') and 'UTC] Context' in text: continue
            if text == 'NO_REPLY': continue
            messages.append({'role': role, 'timestamp': ts, 'text': text.strip()})
        except: pass

print(json.dumps(messages[-30:]))
`;

export async function handleTelegramHistoryRequest(
  query: Record<string, string>,
  _body: string,
  _headers: IncomingHttpHeaders,
): Promise<unknown> {
  const since = query.since || '';
  const sessionFile = getLatestSessionFile();
  if (!sessionFile) return { messages: [], error: 'No session file found' };

  try {
    const { stdout } = await execFileAsync(
      'python3', ['-c', PARSE_SCRIPT, sessionFile, since],
      { timeout: 5_000 },
    );
    const messages = JSON.parse(stdout.trim());
    return { messages, sessionFile: sessionFile.split('/').pop() };
  } catch (err: any) {
    return { messages: [], error: err.message };
  }
}
