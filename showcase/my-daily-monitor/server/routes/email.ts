/**
 * Email API proxy — Gmail API via App Password.
 * Credentials come from environment variables or request headers.
 */
import type { IncomingHttpHeaders } from 'node:http';

const GMAIL_API = 'https://gmail.googleapis.com/gmail/v1';

function getBasicAuth(email: string, appPassword: string): string {
  return 'Basic ' + Buffer.from(`${email}:${appPassword}`).toString('base64');
}

export async function handleEmailRequest(
  query: Record<string, string>,
  _body: string,
  headers: IncomingHttpHeaders,
): Promise<unknown> {
  // Read credentials from headers or env
  const email = (headers['x-gmail-email'] as string) || process.env.GMAIL_EMAIL || '';
  const appPassword = (headers['x-gmail-app-password'] as string) || process.env.GMAIL_APP_PASSWORD || '';

  if (!email || !appPassword) {
    return { emails: [], configured: false, message: 'Gmail App Password not configured — need email and app password' };
  }

  const authHeader = getBasicAuth(email, appPassword);

  const maxResults = query.maxResults || '15';
  const q = query.q || 'is:unread';

  try {
    const listResp = await fetch(
      `${GMAIL_API}/users/me/messages?maxResults=${maxResults}&q=${encodeURIComponent(q)}`,
      { headers: { Authorization: authHeader } },
    );
    if (!listResp.ok) throw new Error(`Gmail list: ${listResp.status}`);
    const listData = await listResp.json() as any;
    const messageIds: string[] = (listData.messages || []).map((m: any) => m.id);

    const emails = await Promise.all(
      messageIds.slice(0, 15).map(async (id) => {
        const resp = await fetch(
          `${GMAIL_API}/users/me/messages/${id}?format=metadata&metadataHeaders=From&metadataHeaders=Subject&metadataHeaders=Date`,
          { headers: { Authorization: authHeader } },
        );
        if (!resp.ok) return null;
        const msg = await resp.json() as any;
        const getHeader = (name: string) =>
          msg.payload?.headers?.find((h: any) => h.name.toLowerCase() === name.toLowerCase())?.value || '';
        return {
          id: msg.id,
          from: getHeader('From').replace(/<.*>/, '').trim(),
          subject: getHeader('Subject'),
          snippet: msg.snippet || '',
          receivedAt: new Date(parseInt(msg.internalDate, 10)).toISOString(),
          unread: (msg.labelIds || []).includes('UNREAD'),
          labels: msg.labelIds || [],
        };
      })
    );

    return { emails: emails.filter(Boolean), configured: true, totalUnread: listData.resultSizeEstimate || 0 };
  } catch (err: any) {
    return { emails: [], configured: true, error: err.message };
  }
}
