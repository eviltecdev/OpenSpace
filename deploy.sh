#!/usr/bin/env bash
set -Eeuo pipefail

# =========================
# KONFIGURATION
# =========================
PROJECT_DIR="$HOME/OpenSpace"
# Override via env: DEPLOY_REMOTE_HOST=user@host ./deploy.sh
# Avoid hardcoding IPs in version-controlled files if this repo is public.
REMOTE_HOST="${DEPLOY_REMOTE_HOST:-root@187.77.113.83}"
REMOTE_CMD='su - claude -c "/home/claude/deploy-openspace.sh"'
# Set STRICT_DEPLOY=1 to exit with an error on local/remote commit mismatch.
STRICT_DEPLOY="${STRICT_DEPLOY:-0}"
LOG_DIR="$PROJECT_DIR/logs"
TIMESTAMP="$(date '+%Y-%m-%d_%H-%M-%S')"
LOG_FILE="$LOG_DIR/deploy_$TIMESTAMP.log"

# SSH options: no interactive prompts, 30s connect timeout, strict key checking
SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout=30 -o StrictHostKeyChecking=yes)

# =========================
# FARBEN
# =========================
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# =========================
# TIMER
# =========================
START_TIME=$(date +%s)

# =========================
# LOGGING SETUP
# =========================
mkdir -p "$LOG_DIR"
exec > >(tee -a "$LOG_FILE") 2>&1

# =========================
# HELPER FUNKTIONEN
# =========================
line() {
  echo -e "${BLUE}--------------------------------------------------${NC}"
}

info() {
  echo -e "${CYAN}[INFO]${NC} $1"
}

success() {
  echo -e "${GREEN}[OK]${NC} $1"
}

warn() {
  echo -e "${YELLOW}[WARNUNG]${NC} $1"
}

error() {
  echo -e "${RED}[FEHLER]${NC} $1"
}

section() {
  echo ""
  line
  echo -e "${BOLD}$1${NC}"
  line
}

cleanup_on_error() {
  trap - ERR  # prevent recursive invocation if cleanup itself fails
  local exit_code=$?
  local end_time
  local duration

  end_time=$(date +%s)
  duration=$((end_time - START_TIME))

  echo ""
  line
  error "DEPLOY ABGEBROCHEN"
  echo -e "${RED}Exit Code:${NC} $exit_code"
  echo -e "${RED}Zeit:${NC} $(date '+%Y-%m-%d %H:%M:%S')"
  echo -e "${RED}Dauer:${NC} ${duration}s"
  echo -e "${RED}Log:${NC} $LOG_FILE"
  line

  exit "$exit_code"
}
trap cleanup_on_error ERR

# =========================
# START
# =========================
echo ""
line
echo -e "${BOLD}${GREEN}LOCAL PRO DEPLOY START${NC}"
echo -e "${BOLD}Zeit:${NC} $(date '+%Y-%m-%d %H:%M:%S')"
echo -e "${BOLD}Log:${NC}  $LOG_FILE"
line

# =========================
# PROJEKT PRÜFEN
# =========================
section "1. Projekt prüfen"

if [ ! -d "$PROJECT_DIR" ]; then
  error "Projektverzeichnis nicht gefunden: $PROJECT_DIR"
  exit 1
fi

cd "$PROJECT_DIR"
success "Projektverzeichnis gefunden: $PROJECT_DIR"

if [ ! -d ".git" ]; then
  error "Kein Git-Repository: $PROJECT_DIR"
  exit 1
fi
success "Git-Repository erkannt"

# =========================
# BRANCH INFO
# =========================
section "2. Git / Branch Status"

CURRENT_BRANCH="$(git branch --show-current)"
CURRENT_COMMIT="$(git rev-parse --short HEAD)"
REMOTE_URL="$(git remote get-url origin)"

echo -e "${BOLD}Branch:${NC} $CURRENT_BRANCH"
echo -e "${BOLD}Commit:${NC} $CURRENT_COMMIT"
echo -e "${BOLD}Remote:${NC} $REMOTE_URL"

if [ "$CURRENT_BRANCH" != "main" ]; then
  error "Du bist nicht auf main, sondern auf: $CURRENT_BRANCH"
  exit 1
fi
success "Branch ist korrekt: main"

# =========================
# WORKING TREE CHECK
# =========================
section "3. Working Tree prüfen"

if ! git diff --quiet || ! git diff --cached --quiet; then
  error "Es gibt uncommittete Änderungen"
  echo ""
  git status --short
  echo ""
  warn "Bitte zuerst committen, dann deployen"
  exit 1
fi
success "Keine uncommitteten Änderungen"

# =========================
# VENV + PYTHON CHECK
# =========================
section "4. Python / Venv prüfen"

if [ ! -f "venv/bin/activate" ]; then
  error "Venv nicht gefunden unter: $PROJECT_DIR/venv"
  exit 1
fi

# shellcheck source=/dev/null
source venv/bin/activate
success "Venv aktiviert"

PYTHON_VERSION="$(python --version 2>&1)"
echo -e "${BOLD}Python:${NC} $PYTHON_VERSION"

# =========================
# OPTIONALER SYNTAX-CHECK
# =========================
section "5. Syntax-Check"

if [ -d "openspace" ]; then
  python -m compileall -q openspace
  success "Python Syntax-Check erfolgreich"
else
  warn "Ordner 'openspace' nicht gefunden -> Syntax-Check übersprungen"
fi

# =========================
# GIT STATUS / PUSH
# =========================
section "6. Push zu GitHub"

git status --short
info "Push auf origin/main wird ausgeführt"
git push origin main
success "Push erfolgreich"

# =========================
# REMOTE DEPLOY
# =========================
section "7. Remote Deploy auf VPS"

info "Starte Remote-Deploy auf $REMOTE_HOST"
ssh "${SSH_OPTS[@]}" "$REMOTE_HOST" "$REMOTE_CMD"
success "Remote-Deploy erfolgreich"

REMOTE_COMMIT=$(ssh "${SSH_OPTS[@]}" "$REMOTE_HOST" "cd /home/claude/OpenSpace && git rev-parse --short HEAD")
echo -e "${BOLD}Remote Commit:${NC} $REMOTE_COMMIT"

if [ "$REMOTE_COMMIT" != "$CURRENT_COMMIT" ]; then
  if [[ "$STRICT_DEPLOY" == "1" ]]; then
    error "Commit-Mismatch: lokal=$CURRENT_COMMIT remote=$REMOTE_COMMIT"
    exit 1
  else
    warn "Remote-Commit ($REMOTE_COMMIT) stimmt nicht mit lokalem Commit ($CURRENT_COMMIT) überein"
  fi
fi

# =========================
# ENDE
# =========================
END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))

echo ""
line
echo -e "${BOLD}${GREEN}DEPLOY ERFOLGREICH${NC}"
echo -e "${BOLD}Zeit:${NC}   $(date '+%Y-%m-%d %H:%M:%S')"
echo -e "${BOLD}Dauer:${NC}  ${DURATION}s"
echo -e "${BOLD}Branch:${NC} $CURRENT_BRANCH"
echo -e "${BOLD}Commit:${NC} $CURRENT_COMMIT"
echo -e "${BOLD}Log:${NC}    $LOG_FILE"
line
