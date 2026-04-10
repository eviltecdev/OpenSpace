import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams, useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { skillsApi, type SkillDetail, type SkillLineage } from '../api';
import EmptyState from '../components/EmptyState';
import MetricCard from '../components/MetricCard';
import SkillEvolutionGraph from '../components/skill-detail/SkillEvolutionGraph';
import SkillVersionDrawer from '../components/skill-detail/SkillVersionDrawer';
import SkillVersionFilterBar from '../components/skill-detail/SkillVersionFilterBar';
import { useSkillEvolutionGraphData } from '../hooks/useSkillEvolutionGraphData';
import { formatDate } from '../utils/format';

function resolveLineageGraph(skill: SkillDetail | null): SkillLineage | null {
  if (!skill) {
    return null;
  }
  if (skill.lineage_graph && Array.isArray(skill.lineage_graph.nodes)) {
    return skill.lineage_graph;
  }
  const legacyGraph = (skill as SkillDetail & { lineage?: SkillLineage }).lineage;
  if (legacyGraph && Array.isArray(legacyGraph.nodes)) {
    return legacyGraph;
  }
  return null;
}

const DRAWER_ANIMATION_DURATION_MS = 300;

export default function SkillDetailPage() {
  const { t } = useTranslation();
  const { skillId = '' } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const [skillClass, setSkillClass] = useState<SkillDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedVersion, setSelectedVersion] = useState<SkillDetail | null>(null);
  const [drawerVersion, setDrawerVersion] = useState<SkillDetail | null>(null);
  const [drawerLoading, setDrawerLoading] = useState(false);
  const [drawerError, setDrawerError] = useState<string | null>(null);
  const [originFilter, setOriginFilter] = useState('all');
  const [tagFilter, setTagFilter] = useState('all');
  const [graphSearchQuery, setGraphSearchQuery] = useState('');
  const [autoRefreshInterval, setAutoRefreshInterval] = useState<number>(0);
  const [lastRefreshed, setLastRefreshed] = useState<Date | null>(null);

  const selectedVersionId = searchParams.get('version');

  const loadSkill = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    setError(null);
    try {
      const detail = await skillsApi.getSkill(skillId);
      setSkillClass(detail);
      setLastRefreshed(new Date());
    } catch (err) {
      setError(err instanceof Error ? err.message : t('skillDetail.failedToLoad'));
    } finally {
      if (!silent) setLoading(false);
    }
  }, [skillId, t]);

  useEffect(() => {
    if (skillId) {
      void loadSkill();
    }
  }, [skillId, loadSkill]);

  useEffect(() => {
    if (autoRefreshInterval <= 0) return;
    const id = window.setInterval(() => {
      void loadSkill(true);
    }, autoRefreshInterval * 60 * 1000);
    return () => window.clearInterval(id);
  }, [autoRefreshInterval, loadSkill]);

  const lineageGraph = useMemo(() => resolveLineageGraph(skillClass), [skillClass]);

  useEffect(() => {
    if (!selectedVersionId) {
      setSelectedVersion(null);
      setDrawerError(null);
      return;
    }

    if (skillClass && selectedVersionId === skillClass.skill_id) {
      setSelectedVersion(skillClass);
      setDrawerError(null);
      return;
    }

    let cancelled = false;
    const loadSelectedVersion = async () => {
      setDrawerLoading(true);
      setDrawerError(null);
      try {
        const detail = await skillsApi.getSkill(selectedVersionId);
        if (!cancelled) {
          setSelectedVersion(detail);
        }
      } catch (err) {
        if (!cancelled) {
          setSelectedVersion(null);
          setDrawerError(err instanceof Error ? err.message : t('skillDetail.failedToLoad'));
        }
      } finally {
        if (!cancelled) {
          setDrawerLoading(false);
        }
      }
    };

    void loadSelectedVersion();
    return () => {
      cancelled = true;
    };
  }, [selectedVersionId, skillClass, t]);

  useEffect(() => {
    if (selectedVersion) {
      setDrawerVersion(selectedVersion);
      return;
    }

    if (!drawerVersion) {
      return;
    }

    const timeoutId = window.setTimeout(() => {
      setDrawerVersion(null);
    }, DRAWER_ANIMATION_DURATION_MS);

    return () => {
      window.clearTimeout(timeoutId);
    };
  }, [drawerVersion, selectedVersion]);

  useEffect(() => {
    if (!lineageGraph || !selectedVersionId) {
      return;
    }
    const exists = lineageGraph.nodes.some((node) => node.skill_id === selectedVersionId);
    if (!exists && skillClass && selectedVersionId !== skillClass.skill_id) {
      const next = new URLSearchParams(searchParams);
      next.delete('version');
      setSearchParams(next);
    }
  }, [lineageGraph, searchParams, selectedVersionId, setSearchParams, skillClass]);

  const alwaysVisibleSkillIds = useMemo(
    () => [skillId, selectedVersionId].filter((value): value is string => Boolean(value)),
    [selectedVersionId, skillId],
  );

  const { allOrigins, allTags, graphData } = useSkillEvolutionGraphData(
    lineageGraph,
    originFilter,
    tagFilter,
    alwaysVisibleSkillIds,
  );

  const classSummary = useMemo(() => {
    const nodes = lineageGraph?.nodes ?? [];
    if (nodes.length === 0) {
      return {
        versionCount: 0,
        activeCount: 0,
        bestScore: 0,
        averageScore: 0,
        maxGeneration: 0,
        totalSelections: 0,
        latestCreatedAt: null as string | null,
        tags: [] as string[],
        origins: [] as string[],
      };
    }

    const tags = new Set<string>();
    const origins = new Set<string>();
    let totalSelections = 0;
    let bestScore = 0;
    let maxGeneration = 0;
    let latestCreatedAt: string | null = null;

    nodes.forEach((node) => {
      node.tags.forEach((tag) => tags.add(tag));
      origins.add(node.origin);
      totalSelections += node.total_selections;
      bestScore = Math.max(bestScore, node.score);
      maxGeneration = Math.max(maxGeneration, node.generation);
      if (!latestCreatedAt || Date.parse(node.created_at) > Date.parse(latestCreatedAt)) {
        latestCreatedAt = node.created_at;
      }
    });

    return {
      versionCount: nodes.length,
      activeCount: nodes.filter((node) => node.is_active).length,
      bestScore,
      averageScore: nodes.reduce((sum, node) => sum + node.score, 0) / nodes.length,
      maxGeneration,
      totalSelections,
      latestCreatedAt,
      tags: Array.from(tags).sort(),
      origins: Array.from(origins).sort(),
    };
  }, [lineageGraph]);

  const openVersion = (nextSkillId: string) => {
    const next = new URLSearchParams(searchParams);
    next.set('version', nextSkillId);
    setSearchParams(next);
  };

  const closeDrawer = () => {
    const next = new URLSearchParams(searchParams);
    next.delete('version');
    setSearchParams(next);
  };

  if (loading) {
    return <div className="p-6 text-sm text-muted">{t('skillDetail.loadingDetail')}</div>;
  }

  if (error || !skillClass) {
    return <div className="p-6 text-sm text-danger">{error ?? t('skillDetail.skillNotFound')}</div>;
  }

  return (
    <div className="p-6 space-y-6 relative">
      <div className="flex items-center gap-4">
        <Link to="/skills" className="chip text-sm transition-colors hover:border-[color:var(--color-border-dark)] hover:text-ink">{t('skillDetail.backToSkills')}</Link>
        <div className="min-w-0">
          <h1 className="text-3xl font-bold font-serif truncate">{skillClass.name}</h1>
          <div className="text-sm text-muted mt-1">{t('skillDetail.anchoredOn', { id: skillClass.skill_id })}</div>
        </div>
      </div>

      <section className="panel-surface p-5 space-y-4">
        <div className="flex items-start justify-between gap-6">
          <div className="space-y-3 min-w-0 flex-1">
            <div>
              <div className="text-xs uppercase tracking-[0.16em] text-muted">{t('skillDetail.skillClass')}</div>
              <h2 className="text-2xl font-bold font-serif mt-1">{t('skillDetail.evolutionOverview')}</h2>
            </div>
            <div className="flex flex-wrap gap-2 text-xs">
              <span className="tag px-2 py-1">{skillClass.category}</span>
              <span className="tag px-2 py-1">{skillClass.visibility}</span>
              <span className="tag px-2 py-1">{skillClass.is_active ? t('skillDetail.activeTip') : t('skillDetail.inactiveAnchor')}</span>
              {classSummary.origins.map((origin) => (
                <span key={origin} className="tag px-2 py-1">{origin}</span>
              ))}
              {classSummary.tags.slice(0, 8).map((tag) => (
                <span key={tag} className="tag px-2 py-1">{tag}</span>
              ))}
              {classSummary.tags.length > 8 ? (
                <span className="tag px-2 py-1">{t('common.tags', { count: classSummary.tags.length - 8 })}</span>
              ) : null}
            </div>
          </div>
          <div className="shrink-0 text-right">
            <div className="text-5xl font-bold font-serif leading-none">{classSummary.bestScore.toFixed(1)}</div>
            <div className="text-xs uppercase tracking-[0.16em] text-muted mt-2">{t('skillDetail.bestVersionScore')}</div>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-4 text-sm text-muted">
          <div>
            <div className="font-bold text-ink">{t('skillDetail.skillDirectory')}</div>
            <div className="break-all">{skillClass.skill_dir || t('common.unavailable')}</div>
          </div>
          <div>
            <div className="font-bold text-ink">{t('skillDetail.latestVersionCreated')}</div>
            <div>{formatDate(classSummary.latestCreatedAt)}</div>
          </div>
          <div>
            <div className="font-bold text-ink">{t('skillDetail.representativeVersion')}</div>
            <div className="break-all">{skillClass.skill_id}</div>
          </div>
          <div>
            <div className="font-bold text-ink">{t('skillDetail.representativeUpdate')}</div>
            <div>{formatDate(skillClass.last_updated)}</div>
          </div>
        </div>
      </section>

      <section className="metrics-row">
        <MetricCard label={t('skillDetail.versions')} value={classSummary.versionCount} hint={t('skillDetail.maxGeneration', { count: classSummary.maxGeneration })} />
        <MetricCard label={t('skillDetail.activeVersions')} value={classSummary.activeCount} hint={t('skillDetail.originsCount', { count: classSummary.origins.length })} />
        <MetricCard label={t('skillDetail.averageScore')} value={classSummary.averageScore.toFixed(1)} hint={t('skillDetail.acrossAllVersions')} />
        <MetricCard label={t('skillDetail.selections')} value={classSummary.totalSelections} hint={t('skillDetail.representativeScore', { score: skillClass.score.toFixed(1) })} />
      </section>

      <section className="panel-surface overflow-hidden relative min-h-[620px]">
        <div className="px-5 py-4 border-b border-[color:var(--color-border)] bg-surface flex items-center justify-between gap-4 flex-wrap">
          <div>
            <div className="text-xs uppercase tracking-[0.16em] text-muted">{t('skillDetail.evolutionGraph')}</div>
            <h2 className="text-2xl font-bold font-serif mt-1">{t('skillDetail.versionLineage')}</h2>
          </div>
          <div className="flex items-center gap-3 flex-wrap">
            <input
              value={graphSearchQuery}
              onChange={(e) => setGraphSearchQuery(e.target.value)}
              placeholder={t('skillDetail.searchNodes')}
              className="px-2.5 py-1 text-sm min-w-[180px]"
            />
            <SkillVersionFilterBar
              originFilter={originFilter}
              onOriginFilterChange={setOriginFilter}
              tagFilter={tagFilter}
              onTagFilterChange={setTagFilter}
              allOrigins={allOrigins}
              allTags={allTags}
            />
            <div className="flex items-center gap-2 text-sm">
              <label className="font-medium text-muted">{t('skillDetail.autoRefresh')}</label>
              <select
                value={autoRefreshInterval}
                onChange={(e) => setAutoRefreshInterval(Number(e.target.value))}
                className="border border-[color:var(--color-ink)] bg-transparent px-2 py-1 text-sm"
              >
                <option value={0}>{t('skillDetail.refreshOff')}</option>
                <option value={1}>1 min</option>
                <option value={5}>5 min</option>
                <option value={10}>10 min</option>
              </select>
              <button
                type="button"
                onClick={() => void loadSkill(true)}
                className="px-2 py-1 text-xs border border-[color:var(--color-border-dark)] rounded hover:bg-[color:var(--color-surface)] transition-colors cursor-pointer bg-transparent text-ink"
                title={lastRefreshed ? t('skillDetail.lastRefreshed', { time: lastRefreshed.toLocaleTimeString() }) : undefined}
              >
                ↺
              </button>
            </div>
          </div>
        </div>
        <SkillEvolutionGraph
          graphData={graphData}
          selectedNodeId={selectedVersionId}
          searchQuery={graphSearchQuery}
          onNodeClick={(node) => openVersion(node.id)}
          onBackgroundClick={closeDrawer}
        />
        {drawerLoading ? (
          <div className="absolute bottom-4 left-4 text-xs text-muted">{t('skillDetail.loadingDrawer')}</div>
        ) : null}
        {drawerError ? (
          <div className="absolute bottom-4 left-4 text-xs text-danger">{drawerError}</div>
        ) : null}
      </section>

      {lineageGraph && lineageGraph.nodes.length === 0 ? (
        <EmptyState title={t('skillDetail.noLineageGraph')} description={t('skillDetail.noLineageGraphDesc')} />
      ) : null}

      <SkillVersionDrawer skill={drawerVersion} isOpen={Boolean(selectedVersion)} onClose={closeDrawer} />
    </div>
  );
}
