/**
 * Bearer token authentication for the API server.
 * Token is read from DASHBOARD_API_TOKEN env variable.
 * If no token is set, auth is disabled (dev fallback).
 */

const TOKEN = process.env.DASHBOARD_API_TOKEN?.trim();

// Routes that are always public (no auth required)
const PUBLIC_ROUTES = new Set(['/api/health']);

export function checkAuth(
  pathname: string,
  headers: Record<string, string | string[] | undefined>,
): { authorized: boolean; reason?: string } {
  // No token configured → auth disabled (warn once)
  if (!TOKEN) {
    return { authorized: true };
  }

  // Public routes skip auth
  if (PUBLIC_ROUTES.has(pathname)) {
    return { authorized: true };
  }

  const authHeader = (headers['authorization'] || headers['x-api-token'] || '') as string;
  const provided = authHeader.startsWith('Bearer ')
    ? authHeader.slice(7).trim()
    : authHeader.trim();

  if (!provided) {
    return { authorized: false, reason: 'Missing Authorization header' };
  }

  // Constant-time comparison to prevent timing attacks
  if (!timingSafeEqual(provided, TOKEN)) {
    return { authorized: false, reason: 'Invalid token' };
  }

  return { authorized: true };
}

function timingSafeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let result = 0;
  for (let i = 0; i < a.length; i++) {
    result |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return result === 0;
}
