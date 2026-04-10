#!/usr/bin/env python3
"""
OpenSpace Nightly Optimizer
============================
Läuft täglich um 3:00 Uhr und:
1. Analysiert Kosten-Trends (Claude + OpenAI)
2. Erkennt wiederkehrende Task-Patterns aus Recordings
3. Erstellt automatisch openclaw Skills für häufige Patterns
4. Schreibt Optimierungsempfehlungen als Markdown-Report

Modell: claude-haiku-4-5-20251001 (günstig, reicht für Analyse)
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

# ── Pfade ────────────────────────────────────────────────────────────────────
OPENSPACE_DIR = Path("/home/claude/OpenSpace")
RECORDINGS_DIR = OPENSPACE_DIR / "logs" / "recordings"
REPORT_DIR = OPENSPACE_DIR / "logs" / "optimizer"
SKILLS_DIR = Path("/home/claude/.agents/skills")
LOG_FILE = REPORT_DIR / "optimizer.log"

CLAUDE_COST_PATTERN = "/tmp/claude-daily-costs-{}.json"
OPENAI_COST_PATTERN = "/tmp/openai-daily-costs-{}.json"

ANALYSIS_MODEL = os.environ.get("OPENSPACE_ANALYSIS_MODEL", "anthropic/claude-haiku-4-5-20251001")
PATTERN_MIN_OCCURRENCES = 3   # Wie oft ein Pattern vorkommen muss um ein Skill zu werden

# Zu generische Patterns die keinen Skill-Wert haben
SKIP_PATTERNS = {
    "ja bitte", "ja", "nein", "ok", "okay", "was sagst du",
    "kannst du mir", "kannst du mir sagen", "logout", "claude",
    "last login", "sudo pm2", "npx skills add",
}
LOOKBACK_DAYS = 7             # Wie viele Tage zurück analysiert werden


# ── Logging ──────────────────────────────────────────────────────────────────
def _log(msg: str) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{ts} {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


# ── Kosten-Analyse ────────────────────────────────────────────────────────────
def load_costs(days: int = LOOKBACK_DAYS) -> dict:
    """Lädt Kosten der letzten N Tage."""
    result = {"claude": {}, "openai": {}, "total_claude": 0.0, "total_openai": 0.0}
    today = date.today()

    for i in range(days):
        d = today - timedelta(days=i)
        ds = d.strftime("%Y-%m-%d")

        # Claude Kosten
        f = Path(CLAUDE_COST_PATTERN.format(ds))
        if f.exists():
            try:
                data = json.loads(f.read_text())
                daily_total = sum(v for v in data.values() if isinstance(v, (int, float)))
                result["claude"][ds] = daily_total
                result["total_claude"] += daily_total
            except Exception:
                pass

        # OpenAI Kosten
        f = Path(OPENAI_COST_PATTERN.format(ds))
        if f.exists():
            try:
                data = json.loads(f.read_text())
                total = data.get("total", 0.0)
                result["openai"][ds] = {"total": total, "models": data.get("models", {})}
                result["total_openai"] += total
            except Exception:
                pass

    return result


# ── Pattern-Erkennung ─────────────────────────────────────────────────────────
def normalize_task(name: str) -> str:
    """Normalisiert Task-Namen für Pattern-Matching."""
    name = name.lower().strip()
    name = re.sub(r"[^a-z0-9äöüß\s]", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    # Ersten 4 Wörter als Fingerprint
    words = name.split()[:4]
    return " ".join(words)


def load_task_patterns(days: int = LOOKBACK_DAYS) -> Counter:
    """Liest alle Recording-Metadaten und zählt Task-Patterns."""
    patterns: Counter = Counter()
    pattern_examples: dict = defaultdict(list)
    cutoff = datetime.now() - timedelta(days=days)

    if not RECORDINGS_DIR.exists():
        return patterns

    for task_dir in RECORDINGS_DIR.iterdir():
        if not task_dir.is_dir():
            continue
        meta_file = task_dir / "metadata.json"
        if not meta_file.exists():
            continue
        try:
            meta = json.loads(meta_file.read_text())
            start_str = meta.get("start_time", "")
            if start_str:
                start_dt = datetime.fromisoformat(start_str)
                if start_dt < cutoff:
                    continue
            task_name = meta.get("task_name", "").strip("…").strip()
            if not task_name or len(task_name) < 5:
                continue
            key = normalize_task(task_name)
            if key:
                patterns[key] += 1
                pattern_examples[key].append(task_name)
        except Exception:
            pass

    return patterns, pattern_examples


# ── Skill-Erstellung ──────────────────────────────────────────────────────────
def skill_exists(pattern_key: str) -> bool:
    """Prüft ob bereits ein Skill für dieses Pattern existiert."""
    skill_name = pattern_key.replace(" ", "-")[:40]
    return (SKILLS_DIR / skill_name).exists()


async def create_skill_for_pattern(
    pattern_key: str,
    examples: list[str],
    occurrence_count: int,
) -> Optional[Path]:
    """Erstellt automatisch ein openclaw SKILL.md für ein erkanntes Pattern."""
    skill_name = re.sub(r"[^a-z0-9\-]", "-", pattern_key.replace(" ", "-"))
    skill_name = re.sub(r"-{2,}", "-", skill_name).strip("-")[:40]
    skill_dir = SKILLS_DIR / skill_name

    if skill_dir.exists():
        return None  # Bereits vorhanden

    _log(f"[Skill] Erstelle neuen Skill: {skill_name} ({occurrence_count}x vorgekommen)")

    # LLM generiert den Skill-Inhalt
    try:
        sys.path.insert(0, str(OPENSPACE_DIR))
        from openspace.host_detection import load_runtime_env
        load_runtime_env()
        from openspace.llm.client import LLMClient

        llm = LLMClient(model=ANALYSIS_MODEL, timeout=30.0, max_retries=1)

        examples_text = "\n".join(f"- {e}" for e in examples[:5])
        prompt = f"""Du erstellst ein openclaw SKILL.md für einen automatisch erkannten wiederkehrenden Task-Typ.

Pattern: "{pattern_key}"
Vorgekommen: {occurrence_count}x in den letzten {LOOKBACK_DAYS} Tagen
Beispiele:
{examples_text}

Erstelle ein präzises, kurzes SKILL.md in diesem Format (EXAKT so, keine Extras):

---
name: {skill_name}
description: |
  [1-2 Sätze was dieser Skill tut und wann er verwendet wird. Deutsch.]
allowed-tools:
  - Bash
  - Read
  - Edit
  - Write
---

# {skill_name.replace("-", " ").title()}

[3-5 Zeilen: Was zu tun ist wenn dieser Task-Typ erkannt wird. Kurz, operativ, kein Fließtext.]

## Schritte
1. [Schritt 1]
2. [Schritt 2]
3. [Schritt 3]

Antworte NUR mit dem SKILL.md Inhalt, nichts anderes."""

        response = await llm.complete(messages=prompt, execute_tools=False)
        content = response["message"]["content"].strip()

        # Frontmatter bereinigen
        if not content.startswith("---"):
            content = f"---\nname: {skill_name}\ndescription: |\n  Automatisch erkannter wiederkehrender Task: {pattern_key}\nallowed-tools:\n  - Bash\n  - Read\n  - Edit\n---\n\n# {skill_name}\n\n{content}"

        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(content)
        _log(f"[Skill] ✓ Erstellt: {skill_dir}/SKILL.md")
        return skill_dir

    except Exception as e:
        _log(f"[Skill] Fehler bei Skill-Erstellung für '{skill_name}': {e}")
        return None


# ── Report-Generierung ────────────────────────────────────────────────────────
def generate_report(costs: dict, patterns: Counter, pattern_examples: dict, new_skills: list) -> str:
    """Erstellt den täglichen Optimierungs-Report."""
    today = date.today().strftime("%Y-%m-%d")
    lines = [
        f"# OpenSpace Nightly Optimizer Report — {today}",
        "",
        "## Kosten (letzte 7 Tage)",
        "",
    ]

    # Claude Kosten
    total_claude = costs["total_claude"]
    lines.append(f"**Claude Code CLI:** ${total_claude:.2f} gesamt")
    for d, v in sorted(costs["claude"].items(), reverse=True)[:5]:
        lines.append(f"  - {d}: ${v:.2f}")

    lines.append("")

    # OpenAI Kosten
    total_openai = costs["total_openai"]
    lines.append(f"**OpenAI API:** ${total_openai:.4f} gesamt")
    for d, v in sorted(costs["openai"].items(), reverse=True)[:5]:
        models = ", ".join(f"{m}: ${c:.4f}" for m, c in v.get("models", {}).items())
        lines.append(f"  - {d}: ${v['total']:.4f} ({models})")

    lines += ["", f"**Gesamt:** ${total_claude + total_openai:.2f}", ""]

    # Task Patterns
    lines += ["## Erkannte Task-Patterns", ""]
    top_patterns = patterns.most_common(10)
    if top_patterns:
        for pattern, count in top_patterns:
            marker = "🆕 " if any(s.name == pattern.replace(" ", "-")[:40] for s in [Path(p) for p in new_skills]) else ""
            lines.append(f"- {marker}`{pattern}` — {count}x")
    else:
        lines.append("_Keine Patterns erkannt (zu wenig Daten)_")

    lines += [""]

    # Neue Skills
    if new_skills:
        lines += ["## Automatisch erstellte Skills", ""]
        for skill_path in new_skills:
            lines.append(f"- `{skill_path}`")
        lines += [""]

    # Empfehlungen
    lines += ["## Optimierungshinweise", ""]

    # Kostenwarnungen
    avg_claude = total_claude / LOOKBACK_DAYS if LOOKBACK_DAYS > 0 else 0
    if avg_claude > 10:
        lines.append(f"⚠️  Hohe Claude-Tageskosten: ${avg_claude:.2f}/Tag — kurze Sessions + /clear nutzen")
    elif avg_claude > 5:
        lines.append(f"ℹ️  Moderate Claude-Kosten: ${avg_claude:.2f}/Tag — im normalen Bereich")
    else:
        lines.append(f"✅ Claude-Kosten gut: ${avg_claude:.2f}/Tag")

    if total_openai > 1.0:
        lines.append(f"⚠️  OpenAI API-Kosten erhöht: ${total_openai:.2f} — Task-Router prüfen")
    else:
        lines.append(f"✅ OpenAI API-Kosten niedrig: ${total_openai:.4f}")

    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────
async def main() -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    _log("[Start] Nightly Optimizer gestartet")

    # 1. Kosten laden
    _log("[Kosten] Lade Kostendaten...")
    costs = load_costs()
    _log(f"[Kosten] Claude: ${costs['total_claude']:.2f} | OpenAI: ${costs['total_openai']:.4f}")

    # 2. Task-Patterns erkennen
    _log("[Patterns] Analysiere Recording-Metadaten...")
    patterns, pattern_examples = load_task_patterns()
    _log(f"[Patterns] {len(patterns)} unique Patterns gefunden")

    # 3. Skills für häufige Patterns erstellen
    new_skills = []
    recurring = [(k, v) for k, v in patterns.items() if v >= PATTERN_MIN_OCCURRENCES]
    _log(f"[Skills] {len(recurring)} Patterns mit {PATTERN_MIN_OCCURRENCES}+ Vorkommen")

    for pattern_key, count in sorted(recurring, key=lambda x: -x[1])[:5]:  # max 5 neue Skills pro Nacht
        if pattern_key in SKIP_PATTERNS:
            continue
        if not skill_exists(pattern_key):
            examples = pattern_examples.get(pattern_key, [])
            skill_path = await create_skill_for_pattern(pattern_key, examples, count)
            if skill_path:
                new_skills.append(skill_path)

    # 4. Report schreiben
    report = generate_report(costs, patterns, pattern_examples, new_skills)
    today = date.today().strftime("%Y-%m-%d")
    report_file = REPORT_DIR / f"{today}.md"
    report_file.write_text(report)
    _log(f"[Report] Geschrieben: {report_file}")

    # 5. Summary ausgeben
    _log(f"[Done] {len(new_skills)} neue Skills | Report: {report_file}")
    print("\n" + report)


if __name__ == "__main__":
    asyncio.run(main())
