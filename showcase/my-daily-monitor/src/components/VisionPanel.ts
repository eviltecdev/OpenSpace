/**
 * VisionPanel — Upload a photo and let Claude analyze it.
 * Drag & drop or click to upload. Sends image to /api/vision.
 */
import { Panel } from './Panel';
import { escapeHtml } from '@/utils';

export class VisionPanel extends Panel {
  private resultEl: HTMLElement | null = null;
  private promptInput: HTMLInputElement | null = null;
  private previewEl: HTMLImageElement | null = null;
  private currentImage: { base64: string; mediaType: string } | null = null;

  constructor() {
    super({ id: 'vision', title: 'Foto analysieren', showCount: false });
    // Let vision-wrap own the entire flex layout — disable panel-content's
    // own scroll/padding so height: 100% inside vision-wrap resolves correctly.
    this.content.style.padding = '0';
    this.content.style.overflow = 'hidden';
    this.content.style.display = 'flex';
    this.content.style.flexDirection = 'column';
    this.buildUI();
  }

  private buildUI(): void {
    this.content.innerHTML = `
      <div class="vision-wrap">
        <div class="vision-drop" id="visionDrop">
          <input type="file" id="visionFileInput" accept="image/*" style="display:none" />
          <div class="vision-drop-inner" id="visionDropInner">
            <div class="vision-drop-icon">🖼️</div>
            <div class="vision-drop-text">Foto hier ablegen<br><small>oder klicken zum Auswählen</small></div>
          </div>
          <img id="visionPreview" class="vision-preview" style="display:none" />
        </div>
        <div class="vision-controls">
          <input class="ch-search-input" id="visionPrompt" placeholder="Frage stellen (optional)..." value="Beschreibe dieses Bild detailliert." />
          <button class="monitor-add-btn" id="visionAnalyze" disabled>Analysieren</button>
        </div>
        <div class="vision-result" id="visionResult"></div>
      </div>
    `;

    this.resultEl = this.content.querySelector('#visionResult');
    this.promptInput = this.content.querySelector('#visionPrompt');
    this.previewEl = this.content.querySelector('#visionPreview');

    const drop = this.content.querySelector<HTMLElement>('#visionDrop')!;
    const fileInput = this.content.querySelector<HTMLInputElement>('#visionFileInput')!;
    const analyzeBtn = this.content.querySelector<HTMLButtonElement>('#visionAnalyze')!;

    // Click to open file picker
    drop.addEventListener('click', () => fileInput.click());

    // File input change
    fileInput.addEventListener('change', () => {
      if (fileInput.files?.[0]) this.loadFile(fileInput.files[0]);
    });

    // Drag & drop
    drop.addEventListener('dragover', (e) => { e.preventDefault(); drop.classList.add('vision-drop-over'); });
    drop.addEventListener('dragleave', () => drop.classList.remove('vision-drop-over'));
    drop.addEventListener('drop', (e) => {
      e.preventDefault();
      drop.classList.remove('vision-drop-over');
      const file = e.dataTransfer?.files?.[0];
      if (file && file.type.startsWith('image/')) this.loadFile(file);
    });

    // Analyze button
    analyzeBtn.addEventListener('click', () => this.analyze());
  }

  private loadFile(file: File): void {
    const reader = new FileReader();
    reader.onload = (e) => {
      const dataUrl = e.target?.result as string;
      // dataUrl = "data:image/jpeg;base64,/9j/..."
      const [header, base64] = dataUrl.split(',');
      const mediaType = header.replace('data:', '').replace(';base64', '') as 'image/jpeg' | 'image/png' | 'image/gif' | 'image/webp';
      this.currentImage = { base64, mediaType };

      // Show preview
      if (this.previewEl) {
        this.previewEl.src = dataUrl;
        this.previewEl.style.display = 'block';
        this.content.querySelector<HTMLElement>('#visionDropInner')!.style.display = 'none';
      }

      this.content.querySelector<HTMLButtonElement>('#visionAnalyze')!.disabled = false;
      if (this.resultEl) this.resultEl.innerHTML = '';

      // Save to server disk so CLI can pick it up
      fetch('/api/vision?action=save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ image: base64, mediaType }),
      }).catch(() => {});
    };
    reader.readAsDataURL(file);
  }

  private async analyze(): Promise<void> {
    if (!this.currentImage) return;

    // Always re-query so we never work with a detached element
    const resultEl = this.content.querySelector<HTMLElement>('#visionResult');
    const btn = this.content.querySelector<HTMLButtonElement>('#visionAnalyze');
    if (!resultEl || !btn) return;

    const prompt = this.promptInput?.value.trim() || 'Beschreibe dieses Bild detailliert.';
    btn.disabled = true;
    btn.textContent = '...';
    resultEl.innerHTML = '<div class="vision-loading">Claude analysiert das Bild...</div>';

    try {
      const resp = await fetch('/api/vision', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ image: this.currentImage.base64, mediaType: this.currentImage.mediaType, prompt }),
      });

      const data = await resp.json() as any;
      if (!resp.ok) throw new Error(data.error || `HTTP ${resp.status}`);
      if (!data.text) throw new Error('Keine Antwort von Claude erhalten');

      const tokens = data.usage
        ? `<div class="vision-meta">${escapeHtml(data.model ?? '')} · ${data.usage.input_tokens + data.usage.output_tokens} Tokens</div>`
        : '';
      resultEl.innerHTML = `
        <div class="vision-answer">${escapeHtml(data.text).replace(/\n/g, '<br>')}</div>
        ${tokens}
      `;
    } catch (err: any) {
      resultEl.innerHTML = `<div class="vision-error">Fehler: ${escapeHtml(String(err?.message ?? err))}</div>`;
    } finally {
      btn.disabled = false;
      btn.textContent = 'Analysieren';
    }
  }

  async refresh(): Promise<void> {}
}
