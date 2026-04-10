/**
 * SkillGraphPanel — visualizes OpenSpace skill evolution as an interactive SVG graph.
 * Nodes = skills, edges = lineage (parent → child).
 * Color = generation. Size = usage (completions).
 */
import { Panel } from './Panel';

interface Skill {
  skill_id: string;
  name: string;
  lineage_generation: number;
  lineage_origin: string;
  is_active: number;
  total_selections: number;
  total_completions: number;
  lineage_change_summary: string | null;
  first_seen: string;
}

interface Edge { child: string; parent: string; }

interface Stats {
  total: number;
  selections: number;
  completions: number;
  max_gen: number;
}

const GEN_COLORS = ['#3b82f6', '#8b5cf6', '#ec4899', '#f59e0b', '#10b981'];

export class SkillGraphPanel extends Panel {
  private svg: SVGSVGElement | null = null;
  private tooltip: HTMLElement | null = null;
  private skills: Skill[] = [];
  private edges: Edge[] = [];
  private stats: Stats | null = null;
  private zoom = 1;
  private pan = { x: 0, y: 0 };
  private dragging = false;
  private dragStart = { x: 0, y: 0, px: 0, py: 0 };

  constructor() {
    super({ id: 'skill-graph', title: 'Skill Evolution', className: 'panel-wide', showCount: true });
    this.content.style.padding = '0';
    this.content.style.overflow = 'hidden';
    this.content.style.position = 'relative';
    this.content.style.display = 'flex';
    this.content.style.flexDirection = 'column';
    this.buildUI();
    this.refresh();
  }

  private buildUI(): void {
    this.content.innerHTML = `
      <div class="sg-toolbar">
        <span class="sg-stat" id="sgStatTotal">— skills</span>
        <span class="sg-stat" id="sgStatGen">— generations</span>
        <span class="sg-stat" id="sgStatUse">— completions</span>
        <button class="monitor-add-btn" id="sgReset" style="font-size:10px;margin-left:auto;">Reset View</button>
      </div>
      <div class="sg-container" id="sgContainer">
        <svg id="sgSvg" style="width:100%;height:100%;cursor:grab;"></svg>
      </div>
      <div class="sg-tooltip" id="sgTooltip" style="display:none;"></div>
    `;

    this.svg = this.content.querySelector('#sgSvg');
    this.tooltip = this.content.querySelector('#sgTooltip');

    this.content.querySelector('#sgReset')?.addEventListener('click', () => {
      this.zoom = 1; this.pan = { x: 0, y: 0 };
      this.applyTransform();
    });

    this.setupDrag();
  }

  private setupDrag(): void {
    const svg = this.svg!;

    svg.addEventListener('wheel', (e: WheelEvent) => {
      e.preventDefault();
      const delta = e.deltaY > 0 ? 0.9 : 1.1;
      this.zoom = Math.max(0.3, Math.min(3, this.zoom * delta));
      this.applyTransform();
    }, { passive: false });

    svg.addEventListener('mousedown', (e) => {
      if ((e.target as Element).classList.contains('sg-node')) return;
      this.dragging = true;
      this.dragStart = { x: e.clientX, y: e.clientY, px: this.pan.x, py: this.pan.y };
      svg.style.cursor = 'grabbing';
    });
    window.addEventListener('mousemove', (e) => {
      if (!this.dragging) return;
      this.pan.x = this.dragStart.px + (e.clientX - this.dragStart.x);
      this.pan.y = this.dragStart.py + (e.clientY - this.dragStart.y);
      this.applyTransform();
    });
    window.addEventListener('mouseup', () => {
      this.dragging = false;
      svg.style.cursor = 'grab';
    });
  }

  private applyTransform(): void {
    const g = this.svg?.querySelector<SVGGElement>('#sgRoot');
    if (g) g.setAttribute('transform', `translate(${this.pan.x},${this.pan.y}) scale(${this.zoom})`);
  }

  async refresh(): Promise<void> {
    if (this.isFetching) return;
    this.setFetching(true);
    try {
      const resp = await fetch('/api/openspace?action=skills');
      const data = await resp.json() as any;
      this.skills = data.skills || [];
      this.edges = data.edges || [];
      this.stats = data.stats || null;
      this.setCount(this.skills.length);
      this.updateStats();
      this.renderGraph();
      this.setDataBadge('live', `${this.skills.length} skills`);
    } catch (e) {
      this.showError('Fehler beim Laden', () => this.refresh());
    } finally {
      this.setFetching(false);
    }
  }

  private updateStats(): void {
    if (!this.stats) return;
    const el = (id: string) => this.content.querySelector(`#${id}`);
    el('sgStatTotal')!.textContent = `${this.stats.total} skills`;
    el('sgStatGen')!.textContent = `${this.stats.max_gen + 1} generations`;
    el('sgStatUse')!.textContent = `${this.stats.completions} completions`;
  }

  private renderGraph(): void {
    if (!this.svg) return;
    const W = 900, H = 520;
    this.svg.setAttribute('viewBox', `0 0 ${W} ${H}`);

    // Layout: columns by generation
    const byGen = new Map<number, Skill[]>();
    for (const s of this.skills) {
      if (!byGen.has(s.lineage_generation)) byGen.set(s.lineage_generation, []);
      byGen.get(s.lineage_generation)!.push(s);
    }
    const maxGen = Math.max(...byGen.keys());
    const colW = W / (maxGen + 2);

    const positions = new Map<string, { x: number; y: number }>();
    for (const [gen, skills] of byGen) {
      const x = colW * (gen + 0.8);
      skills.forEach((s, i) => {
        const y = H * (i + 0.5) / skills.length;
        positions.set(s.skill_id, { x, y });
      });
    }

    // Build SVG
    const ns = 'http://www.w3.org/2000/svg';
    this.svg.innerHTML = '';
    const defs = document.createElementNS(ns, 'defs');
    // Arrow marker
    defs.innerHTML = `<marker id="arrow" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
      <path d="M0,0 L0,6 L6,3 z" fill="#555"/>
    </marker>`;
    this.svg.appendChild(defs);

    const root = document.createElementNS(ns, 'g');
    root.id = 'sgRoot';
    this.svg.appendChild(root);

    // Draw edges
    for (const e of this.edges) {
      const from = positions.get(e.parent);
      const to = positions.get(e.child);
      if (!from || !to) continue;
      const line = document.createElementNS(ns, 'line');
      line.setAttribute('x1', String(from.x));
      line.setAttribute('y1', String(from.y));
      line.setAttribute('x2', String(to.x));
      line.setAttribute('y2', String(to.y));
      line.setAttribute('stroke', '#333');
      line.setAttribute('stroke-width', '1');
      line.setAttribute('marker-end', 'url(#arrow)');
      root.appendChild(line);
    }

    // Calculate max completions for relative sizing
    const maxCompletions = Math.max(1, ...this.skills.map(s => s.total_completions));

    // Draw nodes
    for (const s of this.skills) {
      const pos = positions.get(s.skill_id);
      if (!pos) continue;
      const color = GEN_COLORS[s.lineage_generation % GEN_COLORS.length];
      // Scale: min 6px, max 22px — relative to highest completion count
      const r = 6 + Math.round((s.total_completions / maxCompletions) * 16);
      const opacity = s.is_active ? 1 : 0.35;

      const g = document.createElementNS(ns, 'g');
      g.classList.add('sg-node');
      g.style.cursor = 'pointer';

      const circle = document.createElementNS(ns, 'circle');
      circle.setAttribute('cx', String(pos.x));
      circle.setAttribute('cy', String(pos.y));
      circle.setAttribute('r', String(r));
      circle.setAttribute('fill', color);
      circle.setAttribute('opacity', String(opacity));
      circle.setAttribute('stroke', 'rgba(255,255,255,0.6)');
      circle.setAttribute('stroke-width', '1.5');

      // Skill name label below node
      const text = document.createElementNS(ns, 'text');
      text.setAttribute('x', String(pos.x));
      text.setAttribute('y', String(pos.y + r + 9));
      text.setAttribute('text-anchor', 'middle');
      text.setAttribute('font-size', '7');
      text.setAttribute('fill', color);
      text.setAttribute('opacity', String(opacity));
      text.setAttribute('pointer-events', 'none');
      // Truncate long names
      const label = s.name.length > 18 ? s.name.slice(0, 16) + '…' : s.name;
      text.textContent = label;

      g.appendChild(circle);
      g.appendChild(text);

      g.addEventListener('mouseenter', (e) => this.showTooltip(e as MouseEvent, s));
      g.addEventListener('mouseleave', () => this.hideTooltip());
      root.appendChild(g);
    }

    // Gen labels
    for (let gen = 0; gen <= maxGen; gen++) {
      const x = colW * (gen + 0.8);
      const label = document.createElementNS(ns, 'text');
      label.setAttribute('x', String(x));
      label.setAttribute('y', '14');
      label.setAttribute('text-anchor', 'middle');
      label.setAttribute('font-size', '10');
      label.setAttribute('font-weight', '700');
      label.setAttribute('fill', GEN_COLORS[gen % GEN_COLORS.length]);
      label.textContent = `v${gen}`;
      root.appendChild(label);
    }

    this.applyTransform();
  }

  private showTooltip(e: MouseEvent, s: Skill): void {
    if (!this.tooltip) return;
    const parents = this.edges.filter(ed => ed.child === s.skill_id).map(ed => {
      const p = this.skills.find(sk => sk.skill_id === ed.parent);
      return p?.name || ed.parent.split('__')[0];
    });
    this.tooltip.innerHTML = `
      <div style="font-weight:700;margin-bottom:4px;color:${GEN_COLORS[s.lineage_generation % GEN_COLORS.length]}">${s.name}</div>
      <div>Generation: v${s.lineage_generation} · ${s.lineage_origin}</div>
      <div>Selections: ${s.total_selections} · Completions: ${s.total_completions}</div>
      ${parents.length ? `<div style="margin-top:4px;color:#aaa">Parents: ${parents.join(', ')}</div>` : ''}
      ${s.lineage_change_summary ? `<div style="margin-top:4px;color:#888;font-size:10px;">${s.lineage_change_summary.slice(0, 100)}</div>` : ''}
    `;
    this.tooltip.style.display = 'block';
    this.tooltip.style.left = '-9999px'; // render off-screen first to measure width
    this.tooltip.style.top = `${e.offsetY - 10}px`;

    const containerW = this.content.offsetWidth;
    const tipW = this.tooltip.offsetWidth;
    const leftPos = e.offsetX + 12;
    // Flip to left side if tooltip would overflow the right edge
    this.tooltip.style.left = (leftPos + tipW > containerW - 8)
      ? `${e.offsetX - tipW - 8}px`
      : `${leftPos}px`;
  }

  private hideTooltip(): void {
    if (this.tooltip) this.tooltip.style.display = 'none';
  }
}
