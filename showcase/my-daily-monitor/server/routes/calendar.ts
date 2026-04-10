/**
 * Calendar API proxy — Google Calendar API v3 via App Password.
 * Credentials come from environment variables or request headers.
 */
import type { IncomingHttpHeaders } from 'node:http';

const GCAL_API = 'https://www.googleapis.com/calendar/v3';

function getBasicAuth(email: string, appPassword: string): string {
  return 'Basic ' + Buffer.from(`${email}:${appPassword}`).toString('base64');
}

export async function handleCalendarRequest(
  query: Record<string, string>,
  _body: string,
  headers: IncomingHttpHeaders,
): Promise<unknown> {
  // Read credentials from headers or env
  const email = (headers['x-gmail-email'] as string) || process.env.GMAIL_EMAIL || '';
  const appPassword = (headers['x-gmail-app-password'] as string) || process.env.GMAIL_APP_PASSWORD || '';

  if (!email || !appPassword) {
    return { events: [], configured: false, message: 'Google Calendar not configured (needs Gmail email and app password)' };
  }

  const authHeader = getBasicAuth(email, appPassword);

  const calendarId = query.calendarId || 'primary';
  const now = new Date();
  const dayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate()).toISOString();
  const dayEnd = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1).toISOString();

  try {
    const resp = await fetch(
      `${GCAL_API}/calendars/${encodeURIComponent(calendarId)}/events?timeMin=${dayStart}&timeMax=${dayEnd}&singleEvents=true&orderBy=startTime&maxResults=20`,
      { headers: { Authorization: authHeader } },
    );
    if (!resp.ok) throw new Error(`Calendar API: ${resp.status}`);
    const data = await resp.json() as any;
    const events = (data.items || []).map((ev: any) => ({
      id: ev.id,
      title: ev.summary || '(No title)',
      startTime: ev.start?.dateTime || ev.start?.date || '',
      endTime: ev.end?.dateTime || ev.end?.date || '',
      location: ev.location || '',
      isAllDay: !!ev.start?.date,
      meetingLink: ev.hangoutLink || ev.conferenceData?.entryPoints?.[0]?.uri || '',
    }));
    return { events, configured: true };
  } catch (err: any) {
    return { events: [], configured: true, error: err.message };
  }
}
