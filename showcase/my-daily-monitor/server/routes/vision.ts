/**
 * Vision route — accepts a base64 image, sends it to Claude claude-sonnet-4-6 via Anthropic API,
 * returns the analysis as text.
 * POST /api/vision  { image: "<base64>", mediaType: "image/jpeg|png|gif|webp", prompt?: string }
 * POST /api/vision/save  { image: "<base64>", mediaType: string } — saves image to disk for CLI pickup
 */
import { writeFileSync } from 'node:fs';
import { join } from 'node:path';

const SAVE_PATH = '/tmp/mdm-vision-latest.png';
const SAVE_META = '/tmp/mdm-vision-latest.json';

export async function handleVisionRequest(
  query: Record<string, string>,
  body: string,
): Promise<unknown> {
  // Save-only mode — just write to disk, no AI call
  if (query.action === 'save') {
    const { image, mediaType = 'image/jpeg' } = JSON.parse(body || '{}');
    if (!image) throw new Error('No image provided');
    const buf = Buffer.from(image, 'base64');
    writeFileSync(SAVE_PATH, buf);
    writeFileSync(SAVE_META, JSON.stringify({ mediaType, savedAt: Date.now() }));
    return { saved: true, path: SAVE_PATH };
  }

  // Full analysis mode
  const { image, mediaType = 'image/jpeg', prompt = 'Beschreibe dieses Bild detailliert auf Deutsch.' } = JSON.parse(body || '{}');
  if (!image) throw new Error('No image provided');

  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) throw new Error('ANTHROPIC_API_KEY not set');

  const resp = await fetch('https://api.anthropic.com/v1/messages', {
    method: 'POST',
    headers: {
      'x-api-key': apiKey,
      'anthropic-version': '2023-06-01',
      'content-type': 'application/json',
    },
    body: JSON.stringify({
      model: 'claude-sonnet-4-6',
      max_tokens: 1024,
      messages: [{
        role: 'user',
        content: [
          { type: 'image', source: { type: 'base64', media_type: mediaType, data: image } },
          { type: 'text', text: prompt },
        ],
      }],
    }),
  });

  if (!resp.ok) {
    const err = await resp.text();
    throw new Error(`Anthropic API error ${resp.status}: ${err.slice(0, 200)}`);
  }

  const data = await resp.json() as any;
  const text = data?.content?.[0]?.text;
  if (!text) throw new Error('No response from Claude');

  return { text, model: data.model, usage: data.usage };
}
