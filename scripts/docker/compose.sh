#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE_DIR="$ROOT/docker/compose"

usage() {
  cat <<'EOF'
Usage:
  scripts/docker/compose.sh inference [docker compose args...]
  scripts/docker/compose.sh dev [docker compose args...]
  scripts/docker/compose.sh admin up|up-auth|down|ps|logs|config|generate-user [args...]
  scripts/docker/compose.sh db up|down|ps|logs|shell|migrate [docker compose args...]
  scripts/docker/compose.sh data bootstrap [-- script args...]
  scripts/docker/compose.sh data index [-- script args...]
  scripts/docker/compose.sh train check|prepare|run|export|verify [-- script args...]
  scripts/docker/compose.sh eval run [-- script args...]

Examples:
  scripts/docker/compose.sh inference up -d
  scripts/docker/compose.sh dev up
  scripts/docker/compose.sh admin up -d
  scripts/docker/compose.sh admin generate-user admin -- --password 'change-me' > docker/admin/users.yml
  scripts/docker/compose.sh admin up-auth -d
  scripts/docker/compose.sh db migrate
  scripts/docker/compose.sh data bootstrap -- --limit 3
  scripts/docker/compose.sh data index
  scripts/docker/compose.sh train run
  scripts/docker/compose.sh eval run -- --limit 5

Override detection with FINEDGAR_DOCKER_TARGET=linux-nvidia or mac-cpu.
EOF
}

detect_target() {
  if [[ -n "${FINEDGAR_DOCKER_TARGET:-}" ]]; then
    echo "$FINEDGAR_DOCKER_TARGET"
    return
  fi

  if [[ "$(uname -s)" == "Linux" ]] && command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
    echo "linux-nvidia"
  else
    echo "mac-cpu"
  fi
}

compose_base() {
  docker compose --project-directory "$ROOT" -f "$COMPOSE_DIR/base.yml" "$@"
}

compose_with() {
  local overlay="$1"
  shift
  docker compose --project-directory "$ROOT" -f "$COMPOSE_DIR/base.yml" -f "$COMPOSE_DIR/$overlay" "$@"
}

compose_with_db() {
  local overlay="$1"
  shift
  docker compose --project-directory "$ROOT" -f "$COMPOSE_DIR/base.yml" -f "$COMPOSE_DIR/db.yml" -f "$COMPOSE_DIR/$overlay" "$@"
}

compose_admin() {
  docker compose --project-directory "$ROOT" -f "$COMPOSE_DIR/admin.yml" "$@"
}

compose_admin_auth() {
  docker compose --project-directory "$ROOT" -f "$COMPOSE_DIR/admin.yml" -f "$COMPOSE_DIR/admin.auth.yml" "$@"
}

strip_separator() {
  if [[ "${1:-}" == "--" ]]; then
    shift
  fi
  printf '%s\n' "$@"
}

require_nvidia() {
  local target="$1"
  if [[ "$target" != "linux-nvidia" ]]; then
    echo "QLoRA training requires Linux NVIDIA/CUDA." >&2
    echo "Detected target: $target" >&2
    exit 2
  fi
}

target="$(detect_target)"
export FINEDGAR_DOCKER_TARGET="$target"

if [[ -z "${FINEDGAR_FORCE_CPU:-}" ]]; then
  if [[ "$target" == "linux-nvidia" ]]; then
    export FINEDGAR_FORCE_CPU=0
  else
    export FINEDGAR_FORCE_CPU=1
  fi
fi

workflow="${1:-}"
if [[ -z "$workflow" || "$workflow" == "-h" || "$workflow" == "--help" ]]; then
  usage
  exit 0
fi
shift

case "$workflow" in
  inference)
    if [[ $# -eq 0 ]]; then
      set -- up
    fi
    compose_with_db inference.yml "$@"
    ;;

  dev)
    if [[ $# -eq 0 ]]; then
      set -- up
    fi
    compose_with_db dev.yml "$@"
    ;;

  admin)
    action="${1:-}"
    [[ -n "$action" ]] || { usage; exit 1; }
    shift
    case "$action" in
      up)
        compose_admin up "$@"
        ;;
      up-auth)
        if [[ ! -f "$ROOT/docker/admin/users.yml" ]]; then
          echo "Missing docker/admin/users.yml." >&2
          echo "Generate one with:" >&2
          echo "  scripts/docker/compose.sh admin generate-user admin -- --password '<strong-password>' > docker/admin/users.yml" >&2
          exit 1
        fi
        compose_admin_auth up "$@"
        ;;
      down)
        compose_admin down "$@"
        ;;
      ps)
        compose_admin ps "$@"
        ;;
      logs)
        compose_admin logs admin-console "$@"
        ;;
      config)
        compose_admin config "$@"
        ;;
      generate-user)
        username="${1:-admin}"
        if [[ $# -gt 0 ]]; then
          shift
        fi
        mapfile -t args < <(strip_separator "$@")
        image="amir20/dozzle:${DOZZLE_VERSION:-latest}"
        if ! docker image inspect "$image" >/dev/null 2>&1; then
          docker pull "$image" >&2
        fi
        docker run --rm --pull never "$image" generate "$username" "${args[@]}"
        ;;
      *)
        echo "Unknown admin action: $action" >&2
        usage
        exit 1
        ;;
    esac
    ;;

  db)
    action="${1:-}"
    [[ -n "$action" ]] || { usage; exit 1; }
    shift
    case "$action" in
      up)
        compose_with db.yml up -d postgres "$@"
        ;;
      down)
        compose_with db.yml stop postgres "$@"
        compose_with db.yml rm -f postgres
        ;;
      ps)
        compose_with db.yml ps "$@"
        ;;
      logs)
        compose_with db.yml logs postgres "$@"
        ;;
      shell)
        compose_with db.yml exec postgres psql -U "${POSTGRES_USER:-finedgar}" -d "${POSTGRES_DB:-finedgar}" "$@"
        ;;
      migrate)
        compose_with db.yml run --rm db-migrate "$@"
        ;;
      *)
        echo "Unknown db action: $action" >&2
        usage
        exit 1
        ;;
    esac
    ;;

  data)
    action="${1:-}"
    [[ -n "$action" ]] || { usage; exit 1; }
    shift
    mapfile -t args < <(strip_separator "$@")
    case "$action" in
      bootstrap)
        compose_with data.yml run --rm data-bootstrap python scripts/bootstrap_data.py "${args[@]}"
        ;;
      index)
        compose_with data.yml run --rm index-builder python scripts/build_vector_index.py "${args[@]}"
        ;;
      *)
        echo "Unknown data action: $action" >&2
        usage
        exit 1
        ;;
    esac
    ;;

  train)
    require_nvidia "$target"
    action="${1:-}"
    [[ -n "$action" ]] || { usage; exit 1; }
    shift
    mapfile -t args < <(strip_separator "$@")
    case "$action" in
      check)
        compose_with train.nvidia.yml run --rm train-check "${args[@]}"
        ;;
      prepare)
        if [[ ${#args[@]} -eq 0 ]]; then
          compose_with train.nvidia.yml run --rm train-prepare
        else
          compose_with train.nvidia.yml run --rm train-prepare sh -c "${args[*]}"
        fi
        ;;
      run)
        compose_with train.nvidia.yml run --rm trainer python model/training/train.py --config model/configs/qlora_e4b.yaml "${args[@]}"
        ;;
      export)
        compose_with train.nvidia.yml run --rm train-export python model/training/export.py "${args[@]}"
        ;;
      verify)
        compose_with train.nvidia.yml run --rm train-verify python model/training/verify_model.py --model "${OLLAMA_MODEL:-finedgar}" "${args[@]}"
        ;;
      *)
        echo "Unknown train action: $action" >&2
        usage
        exit 1
        ;;
    esac
    ;;

  eval)
    action="${1:-run}"
    shift || true
    mapfile -t args < <(strip_separator "$@")
    case "$action" in
      run)
        if [[ ${#args[@]} -eq 0 ]]; then
          compose_with eval.yml run --rm eval
        else
          compose_with eval.yml run --rm eval python scripts/run_financebench_eval.py "${args[@]}"
        fi
        ;;
      *)
        echo "Unknown eval action: $action" >&2
        usage
        exit 1
        ;;
    esac
    ;;

  compose)
    compose_base "$@"
    ;;

  *)
    echo "Unknown workflow: $workflow" >&2
    usage
    exit 1
    ;;
esac
