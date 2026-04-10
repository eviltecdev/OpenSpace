/**
 * Path-Jail: restricts file access to a defined allowlist of directories.
 * Prevents path traversal attacks on file-reading endpoints.
 */

import { resolve, normalize } from 'node:path';
import { homedir } from 'node:os';

const HOME = homedir();

// Only these directories are readable via API
const ALLOWED_DIRS = [
  `${HOME}/OpenSpace/logs`,
  `${HOME}/OpenSpace/.openspace`,
  `/tmp/openspace`,
  `/tmp/agent-output`,
  `/tmp/openai-daily-costs`,
  `${HOME}/.openclaw/agents/main/sessions`,
  `${HOME}/.openclaw/logs`,
];

export function isPathAllowed(filePath: string): boolean {
  if (!filePath || typeof filePath !== 'string') return false;

  // Resolve to absolute path (handles ../ traversal)
  const resolved = resolve(normalize(filePath));

  return ALLOWED_DIRS.some(dir => resolved.startsWith(dir));
}

export function assertPathAllowed(filePath: string): void {
  if (!isPathAllowed(filePath)) {
    throw new Error(`Access denied: path '${filePath}' is outside allowed directories.`);
  }
}
