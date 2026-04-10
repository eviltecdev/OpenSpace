import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import ForceGraph2D from 'react-force-graph-2d';
import type { SkillGraphNode } from '../../hooks/useSkillEvolutionGraphData';

interface SkillGraphLink {
  source: string;
  target: string;
}

interface SkillEvolutionGraphProps {
  graphData: {
    nodes: SkillGraphNode[];
    links: SkillGraphLink[];
  };
  selectedNodeId?: string | null;
  searchQuery?: string;
  onNodeClick: (node: SkillGraphNode) => void;
  onBackgroundClick?: () => void;
}

const GRAPH_BG = '#FAF9F5';

export default function SkillEvolutionGraph({
  graphData,
  selectedNodeId,
  searchQuery,
  onNodeClick,
  onBackgroundClick,
}: SkillEvolutionGraphProps) {
  const { t } = useTranslation();
  const graphContainerRef = useRef<HTMLDivElement>(null);
  const fgRef = useRef<any>(null);
  const [graphDim, setGraphDim] = useState({ width: 0, height: 0 });

  useEffect(() => {
    if (!graphContainerRef.current) {
      return;
    }

    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (!entry) {
        return;
      }
      const { width, height } = entry.contentRect;
      if (width > 0 && height > 0) {
        setGraphDim({ width, height });
      }
    });

    observer.observe(graphContainerRef.current);
    return () => observer.disconnect();
  }, []);

  // Configure forces synchronously after DOM update (before first paint) so
  // they apply before the simulation's first tick — this prevents nodes from
  // flying off-screen on initial render.
  useLayoutEffect(() => {
    const fg = fgRef.current;
    if (!fg) return;
    fg.d3Force('charge')?.strength(-100);
    fg.d3Force('link')?.distance(40);
    fg.d3Force('center')?.strength(0.05);
  }, [graphDim]);

  // Intercept wheel events on the graph container: plain two-finger scroll
  // should scroll the page; only Ctrl/Meta+scroll (pinch-to-zoom) goes to the
  // graph's zoom handler.
  useEffect(() => {
    const container = graphContainerRef.current;
    if (!container) return;

    const handleWheel = (e: WheelEvent) => {
      if (e.ctrlKey || e.metaKey) return; // pinch-to-zoom — let graph handle it
      e.stopPropagation();
      const scrollRegion = container.closest<HTMLElement>('.app-scroll-region');
      if (scrollRegion) {
        scrollRegion.scrollTop += e.deltaY;
      }
    };

    container.addEventListener('wheel', handleWheel, { capture: true, passive: false });
    return () => container.removeEventListener('wheel', handleWheel, { capture: true });
  }, []);

  const paintNode = useCallback((node: object, ctx: CanvasRenderingContext2D, globalScale: number) => {
    ctx.save();
    const graphNode = node as SkillGraphNode;
    const normalizedScore = Math.max(0, Math.min(1, graphNode.score / 100));
    const baseRadius = 7 + graphNode.usageRatio * 7;
    const fontSize = 12 / globalScale;
    const x = graphNode.x ?? 0;
    const y = graphNode.y ?? 0;
    const isSelected = graphNode.id === selectedNodeId;

    const hasQuery = Boolean(searchQuery?.trim());
    const isMatch = !hasQuery || graphNode.name.toLowerCase().includes(searchQuery!.trim().toLowerCase());
    const dimFactor = hasQuery && !isMatch ? 0.18 : 1;

    const red = 184 + Math.round(71 * normalizedScore);
    const green = 92 + Math.round(99 * normalizedScore);
    const blue = 80 + Math.round(7 * normalizedScore);
    const nodeColor = graphNode.isActive
      ? `rgba(${red}, ${green}, ${blue}, ${0.92 * dimFactor})`
      : `rgba(184, 180, 168, ${0.82 * dimFactor})`;
    const glowColor = graphNode.isActive
      ? `rgba(${red}, ${green}, ${blue}, ${0.45 * dimFactor})`
      : `rgba(184, 180, 168, ${0.3 * dimFactor})`;

    ctx.globalAlpha = dimFactor;

    ctx.beginPath();
    ctx.arc(x, y, baseRadius + 1.5, 0, 2 * Math.PI, false);
    ctx.fillStyle = GRAPH_BG;
    ctx.fill();

    ctx.beginPath();
    ctx.arc(x, y, baseRadius, 0, 2 * Math.PI, false);
    ctx.fillStyle = nodeColor;
    ctx.shadowColor = glowColor;
    ctx.shadowBlur = isSelected ? 22 : 14;
    ctx.fill();
    ctx.shadowBlur = 0;

    ctx.beginPath();
    ctx.arc(x, y, Math.max(2.6, baseRadius * 0.45), 0, 2 * Math.PI, false);
    ctx.fillStyle = graphNode.isActive ? 'rgba(255, 255, 255, 0.96)' : 'rgba(255, 255, 255, 0.72)';
    ctx.fill();

    if (isSelected) {
      ctx.beginPath();
      ctx.arc(x, y, baseRadius + 4, 0, 2 * Math.PI, false);
      ctx.strokeStyle = '#141413';
      ctx.lineWidth = 2 / globalScale;
      ctx.stroke();
    }

    ctx.globalAlpha = isMatch ? 1 : dimFactor;
    ctx.font = `${fontSize}px ui-monospace`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    ctx.fillStyle = '#4A3B2A';
    ctx.fillText(graphNode.name, x, y + baseRadius + 5 / globalScale);

    ctx.restore();
  }, [selectedNodeId, searchQuery]);

  const paintLink = useCallback((link: object, ctx: CanvasRenderingContext2D) => {
    const source = (link as any).source as SkillGraphNode | undefined;
    const target = (link as any).target as SkillGraphNode | undefined;
    if (!source || !target) {
      return;
    }

    const sx = source.x;
    const sy = source.y;
    const tx = target.x;
    const ty = target.y;
    if (sx === undefined || sy === undefined || tx === undefined || ty === undefined) {
      return;
    }

    const dx = tx - sx;
    const dy = ty - sy;
    const dist = Math.hypot(dx, dy) || 1;
    const nx = -dy / dist;
    const ny = dx / dist;

    const curveKey = `${source.id}->${target.id}`;
    let hash = 0;
    for (let i = 0; i < curveKey.length; i += 1) {
      hash = ((hash << 5) - hash + curveKey.charCodeAt(i)) | 0;
    }
    const curveSign = hash % 2 === 0 ? 1 : -1;
    const baseOffset = Math.min(14, dist * 0.08) * curveSign;

    const c1x = sx + dx * 0.33 + nx * baseOffset;
    const c1y = sy + dy * 0.33 + ny * baseOffset;
    const c2x = sx + dx * 0.67 + nx * baseOffset;
    const c2y = sy + dy * 0.67 + ny * baseOffset;

    ctx.save();
    ctx.lineCap = 'round';

    ctx.beginPath();
    ctx.moveTo(sx, sy);
    ctx.bezierCurveTo(c1x, c1y, c2x, c2y, tx, ty);
    ctx.strokeStyle = 'rgba(138, 90, 68, 0.07)';
    ctx.lineWidth = 5;
    ctx.shadowColor = 'rgba(202, 103, 2, 0.15)';
    ctx.shadowBlur = 3;
    ctx.shadowOffsetX = 1;
    ctx.shadowOffsetY = 1;
    ctx.stroke();

    const gradient = ctx.createLinearGradient(sx, sy, tx, ty);
    gradient.addColorStop(0, 'rgba(189, 140, 99, 0.55)');
    gradient.addColorStop(1, 'rgba(148, 104, 70, 0.4)');

    ctx.beginPath();
    ctx.moveTo(sx, sy);
    ctx.bezierCurveTo(c1x, c1y, c2x, c2y, tx, ty);
    ctx.strokeStyle = gradient;
    ctx.lineWidth = 2.4;
    ctx.shadowBlur = 0;
    ctx.shadowOffsetX = 0;
    ctx.shadowOffsetY = 0;
    ctx.stroke();

    ctx.restore();
  }, []);

  if (graphData.nodes.length === 0) {
    return <div className="text-sm text-muted p-4">{t('graph.noGraphData')}</div>;
  }

  return (
    <div className="h-[540px] bg-bg-page" ref={graphContainerRef}>
      {graphDim.width > 0 && graphDim.height > 0 ? (
        <ForceGraph2D
          ref={fgRef}
          width={graphDim.width}
          height={graphDim.height}
          graphData={graphData}
          cooldownTicks={200}
          warmupTicks={0}
          nodeRelSize={6}
          nodeLabel={(node) => {
            const graphNode = node as SkillGraphNode;
            return [
              graphNode.name,
              t('graph.tooltipScore', { value: graphNode.score.toFixed(1) }),
              t('graph.tooltipGeneration', { value: graphNode.generation }),
              t('graph.tooltipOrigin', { value: graphNode.origin }),
            ].join('\n');
          }}
          onNodeClick={(node) => {
            const graphNode = node as SkillGraphNode;
            if (fgRef.current && typeof graphNode.x === 'number' && typeof graphNode.y === 'number') {
              fgRef.current.centerAt(graphNode.x, graphNode.y, 600);
              fgRef.current.zoom(2.3, 600);
            }
            onNodeClick(graphNode);
          }}
          onBackgroundClick={() => onBackgroundClick?.()}
          onNodeHover={(node) => {
            document.body.style.cursor = node ? 'pointer' : 'default';
          }}
          nodeCanvasObject={paintNode}
          linkCanvasObject={paintLink}
          linkCanvasObjectMode={() => 'replace'}
          d3AlphaDecay={0.02}
          d3VelocityDecay={0.3}
        />
      ) : null}
    </div>
  );
}
