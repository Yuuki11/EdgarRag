#!/usr/bin/env bash
# End-to-end build + train + eval runner.
#
# Assumes all source files under backend/, model/, and scripts/ already
# exist (the agent-generation waves this script used to run have been
# removed — the code they produced is now committed).
#
# What this script does, in order:
#   Phase 0: verify GPU + environment
#   Gate G1: run pytest, smoke-test data bootstrap, verify XBRL fetch
#   Phase R: full data bootstrap (can take 30-60 min, SEC rate-limited)
#   Gate G2: generate + validate training data
#   Gate G3: train, export to GGUF, register with Ollama, verify

set -euo pipefail

# Adjust these two for your machine:
export PROJECT_ROOT="${PROJECT_ROOT:-/home/perseusdg/Development/edgar_rag}"
PY="${PY:-/home/perseusdg/miniconda3/envs/finedgar/bin/python}"

cd "$PROJECT_ROOT"

log() { echo "[$(date +%H:%M:%S)] $*"; }
die() { echo "FATAL: $*" >&2; exit 1; }

# ── Phase 0: Verify Setup ──
log "Phase 0: Verifying environment"
$PY -c "import torch; assert torch.cuda.is_available(); print('GPU OK:', torch.cuda.get_device_name(0))"
log "Phase 0 done"

# ── Gate G1: Verify data pipeline ──
log "Gate G1: Running pytest + data pipeline smoke tests"
$PY -m pytest backend/tests/test_data_pipeline.py -v || die "Tests failed"
$PY scripts/bootstrap_data.py --limit 3 || die "Bootstrap smoke test failed"
$PY -c "
from backend.data.xbrl_fetcher import get_metric
fact = get_metric('AAPL', 'Revenues', 2023)
assert fact is not None and fact.value > 300_000_000_000
print(f'Apple Revenue: \${fact.value:,.0f} — GATE G1 PASSED')
" || die "XBRL verification failed"
log "Gate G1 PASSED"

# ── Phase R: Full data bootstrap ──
log "Phase R: Full bootstrap (background)"
$PY scripts/bootstrap_data.py &
BOOT=$!
wait $BOOT || die "Full bootstrap failed"
log "Phase R complete"

# ── Gate G2: Generate + validate training data ──
log "Gate G2: Generating training data"
$PY model/training/prepare_data.py --sources convfinqa,phrasebank
$PY model/training/prepare_data.py --sources xbrl_qa
$PY model/training/prepare_data.py --sources diff_summaries
$PY model/training/bootstrap_diffs.py || log "WARNING: bootstrap_diffs may need Ollama running"

echo ""
echo "══════════════════════════════════════════════════════════════"
echo "MANUAL STEP: Review data/training/diff_review_queue.jsonl"
echo "Keep good examples, fix or delete bad ones."
echo "Then press Enter to continue."
echo "══════════════════════════════════════════════════════════════"
read -r

$PY model/training/prepare_data.py --combine
$PY model/training/prepare_data.py --validate || die "Dataset validation failed"
log "Gate G2 PASSED"

# ── Gate G3: Train, Export, Verify ──
log "Gate G3: Starting training (~2-3 hours on RTX 4070)"
$PY model/training/train.py

log "Training complete. Checking LoRA adapters..."
ls outputs/finedgar-gemma4-e4b/lora-final/ || die "LoRA adapters not found"

log "Exporting to GGUF..."
$PY model/training/export.py
ls model/gguf/unsloth.Q4_K_M.gguf || die "GGUF not found"

log "Registering with Ollama..."
cd model && ollama create finedgar -f Modelfile && cd "$PROJECT_ROOT"

log "Verifying model..."
$PY model/training/verify_model.py || die "Model verification failed"

echo ""
echo "══════════════════════════════════════════════════════════════"
echo "ALL PHASES COMPLETE!"
echo ""
echo "Artifacts produced:"
echo "  - Training data: data/training/finedgar_train.jsonl"
echo "  - GGUF model: model/gguf/unsloth.Q4_K_M.gguf"
echo "  - Ollama model: finedgar"
echo ""
echo "Next: run scripts/run_financebench_eval.py for scored evaluation."
echo "══════════════════════════════════════════════════════════════"
