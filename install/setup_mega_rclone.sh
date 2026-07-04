#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REMOTE_NAME="mega"
MOUNT_POINT="$HOME/mega"
COMPILED_PATH="FS42_MEDIA/Compiled"
DOWNLOAD_STATE=1
MOUNT_REMOTE=0
RECONFIGURE=0

usage() {
  cat <<'EOF'
Usage: bash install/setup_mega_rclone.sh [options]

Installs rclone/fuse3, configures an rclone MEGA remote, and optionally pulls
FieldStation42 portable state from MEGA.

Options:
  --remote NAME          rclone remote name to create/use (default: mega)
  --mount-point PATH     local MEGA mount point (default: ~/mega)
  --compiled-path PATH   remote compiled state folder (default: FS42_MEDIA/Compiled)
  --mount                mount the MEGA remote after configuration
  --no-download-state    do not download confs/runtime state
  --reconfigure          replace the existing remote config block
  -h, --help             show this help

Environment:
  MEGA_USER              MEGA login email/username
  MEGA_PASS              MEGA password
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --remote)
      REMOTE_NAME="${2:?Missing value for --remote}"
      shift 2
      ;;
    --mount-point)
      MOUNT_POINT="${2:?Missing value for --mount-point}"
      shift 2
      ;;
    --compiled-path)
      COMPILED_PATH="${2:?Missing value for --compiled-path}"
      shift 2
      ;;
    --mount)
      MOUNT_REMOTE=1
      shift
      ;;
    --no-download-state)
      DOWNLOAD_STATE=0
      shift
      ;;
    --reconfigure)
      RECONFIGURE=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 2
      ;;
  esac
done

expand_path() {
  local value="$1"
  if [[ "$value" == "~" ]]; then
    printf '%s\n' "$HOME"
  elif [[ "$value" == ~/* ]]; then
    printf '%s/%s\n' "$HOME" "${value#~/}"
  else
    printf '%s\n' "$value"
  fi
}

install_packages() {
  if command -v rclone >/dev/null 2>&1 && command -v fusermount3 >/dev/null 2>&1; then
    echo "rclone and fuse3 are already installed."
    return
  fi

  if ! command -v sudo >/dev/null 2>&1; then
    echo "sudo is required to install rclone/fuse3." >&2
    exit 1
  fi

  sudo apt-get update
  sudo apt-get install -y rclone fuse3
}

remote_exists() {
  rclone listremotes 2>/dev/null | sed 's/:$//' | grep -Fxq "$REMOTE_NAME"
}

remove_remote_block() {
  local config_file="$1"
  local temp_file
  temp_file="$(mktemp)"
  awk -v section="[$REMOTE_NAME]" '
    /^\[.*\]$/ { skip = ($0 == section) }
    !skip { print }
  ' "$config_file" > "$temp_file"
  mv "$temp_file" "$config_file"
}

configure_remote() {
  local config_dir config_file mega_user mega_pass obscured_pass
  config_dir="${XDG_CONFIG_HOME:-$HOME/.config}/rclone"
  config_file="$config_dir/rclone.conf"
  mkdir -p "$config_dir"
  chmod 700 "$config_dir"
  touch "$config_file"
  chmod 600 "$config_file"

  if remote_exists && [[ "$RECONFIGURE" -eq 0 ]]; then
    echo "rclone remote '$REMOTE_NAME' already exists."
    return
  fi

  mega_user="${MEGA_USER:-}"
  mega_pass="${MEGA_PASS:-}"

  if [[ -z "$mega_user" ]]; then
    read -r -p "MEGA username/email: " mega_user
  fi
  if [[ -z "$mega_pass" ]]; then
    read -r -s -p "MEGA password: " mega_pass
    echo
  fi

  if [[ -z "$mega_user" || -z "$mega_pass" ]]; then
    echo "MEGA username and password are required." >&2
    exit 1
  fi

  cp "$config_file" "$config_file.bak.$(date +%Y%m%d%H%M%S)"
  remove_remote_block "$config_file"
  obscured_pass="$(rclone obscure "$mega_pass")"

  {
    printf '\n[%s]\n' "$REMOTE_NAME"
    printf 'type = mega\n'
    printf 'user = %s\n' "$mega_user"
    printf 'pass = %s\n' "$obscured_pass"
  } >> "$config_file"

  chmod 600 "$config_file"
  echo "Configured rclone remote '$REMOTE_NAME'."
}

test_remote() {
  echo "Testing ${REMOTE_NAME}: ..."
  rclone lsd "${REMOTE_NAME}:" >/dev/null
  echo "MEGA remote test passed."
}

copy_optional() {
  local source="$1"
  local destination="$2"
  local label="$3"
  if rclone copyto "$source" "$destination"; then
    echo "Downloaded $label."
  else
    echo "Warning: could not download $label from $source" >&2
  fi
}

download_state() {
  local remote_base
  remote_base="${REMOTE_NAME}:${COMPILED_PATH}"

  mkdir -p "$ROOT_DIR/confs" "$ROOT_DIR/runtime"

  echo "Downloading station configs from ${remote_base}/confs ..."
  rclone copy "${remote_base}/confs" "$ROOT_DIR/confs" --include '*.json' --max-depth 1

  copy_optional "${remote_base}/runtime/fs42_fluid.db" "$ROOT_DIR/runtime/fs42_fluid.db" "runtime/fs42_fluid.db"
  copy_optional "${remote_base}/compiled_manifest.json" "$ROOT_DIR/runtime/compiled_manifest.json" "runtime/compiled_manifest.json"

  if [[ -x "$ROOT_DIR/env/bin/python" ]]; then
    echo "Recreating catalog symlinks from downloaded configs ..."
    "$ROOT_DIR/env/bin/python" -m fs42.launcher --sync-media-links --no-mount --no-sync-compiled
  else
    echo "Python env not found yet. After bash install.sh, run:"
    echo "  ./launch.sh --sync-media-links --no-mount --no-sync-compiled"
  fi
}

mount_remote() {
  local mount_point
  mount_point="$(expand_path "$MOUNT_POINT")"
  mkdir -p "$mount_point"

  if command -v findmnt >/dev/null 2>&1 && findmnt -M "$mount_point" >/dev/null 2>&1; then
    echo "MEGA is already mounted at $mount_point."
    return
  fi

  echo "Mounting ${REMOTE_NAME}: at $mount_point ..."
  rclone mount "${REMOTE_NAME}:" "$mount_point" \
    --vfs-cache-mode full \
    --vfs-read-ahead 2G \
    --buffer-size 512M \
    --vfs-cache-max-size 50G \
    --vfs-cache-max-age 24h \
    --dir-cache-time 72h \
    --poll-interval 0 \
    --transfers 4 \
    --checkers 8 \
    --daemon
}

main() {
  cd "$ROOT_DIR"
  install_packages
  configure_remote
  test_remote
  [[ "$DOWNLOAD_STATE" -eq 1 ]] && download_state
  [[ "$MOUNT_REMOTE" -eq 1 ]] && mount_remote

  echo
  echo "MEGA/rclone setup complete."
}

main "$@"
