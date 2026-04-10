/**
 * AI proxy route — calls OpenClaw bot (claude-agent) via CLI.
 * POST /api/ai  { messages: [{role, content}] }
 * Returns: { content: string, model: string }
 */
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import type { IncomingHttpHeaders } from 'node:http';

const execFileAsync = promisify(execFile);
const OPENCLAW_BIN = '/home/claude/.npm-global/bin/openclaw';

export async function handleAiRequest(
  _query: Record<string, string>,
  body: string,
  _headers: IncomingHttpHeaders | Record<string, string | string[] | undefined>,
): Promise<unknown> {
  const { messages = [] } = JSON.parse(body || '{}');

  const rawMessage = messages
    .filter((m: any) => m.role === 'user')
    .map((m: any) => m.content)
    .join('\n\n');
  if (!rawMessage.trim()) throw new Error('No message provided');

  // Strip context block prefix — send clean message to OpenClaw
  const userQuestionMatch = rawMessage.match(/User:\s*([\s\S]+)$/);
  const userText = userQuestionMatch ? userQuestionMatch[1].trim() : rawMessage.trim();

  // Include context if present
  const contextMatch = rawMessage.match(/^Context data:\n([\s\S]*?)\n\nUser:/);
  const context = contextMatch ? contextMatch[1].trim() : '';
  const message = context
    ? `Dashboard data:\n${context}\n\nFrage: ${userText}`
    : userText;

  const { stdout, stderr } = await execFileAsync(
    OPENCLAW_BIN,
    ['agent', '--message', message, '--agent', 'claude-agent', '--json'],
    { timeout: 30_000, env: { ...process.env } },
  );

  let parsed: any;
  try {
    const jsonMatch = stdout.match(/(\{[\s\S]*\})\s*$/);
    parsed = JSON.parse(jsonMatch ? jsonMatch[1] : stdout);
  } catch {
    throw new Error(`OpenClaw returned invalid JSON: ${stderr || stdout.slice(0, 200)}`);
  }

  const text = parsed?.result?.payloads?.[0]?.text
    || parsed?.result?.payloads?.find((p: any) => p?.text)?.text;
  if (!text) throw new Error(`No reply from OpenClaw (status: ${parsed?.status})`);

  return {
    content: text,
    model: parsed?.result?.meta?.agentMeta?.model || 'openclaw/claude-agent',
  };
}
