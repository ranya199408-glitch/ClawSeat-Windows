#!/usr/bin/env bash
# shellcheck shell=bash
# Loaded by scripts/install.sh. Resolve this file with BASH_SOURCE so
# callers may source install.sh from any current working directory.
_CLAWSEAT_INSTALL_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

workspace_render_sha() {
  local path="$1"
  sed -n 's/^<!-- rendered_from_clawseat_sha=\([^ ]*\) .*$/\1/p' "$path" 2>/dev/null | head -1
}

stale_workspace_projects() {
  local new_sha="$1"
  local workspaces_root="$HOME/.agents/workspaces"
  [[ -d "$workspaces_root" ]] || return 0
  find "$workspaces_root" -mindepth 3 -maxdepth 3 \
    \( -name CLAUDE.md -o -name AGENTS.md -o -name GEMINI.md \) -print 2>/dev/null \
    | while IFS= read -r doc; do
        local rendered_sha="" project=""
        rendered_sha="$(workspace_render_sha "$doc")"
        [[ -n "$rendered_sha" && "$rendered_sha" != "$new_sha" ]] || continue
        project="$(basename "$(dirname "$(dirname "$doc")")")"
        [[ -n "$project" ]] && printf '%s\n' "$project"
      done | sort -u
}

prompt_workspace_rerender_after_update() {
  local old_sha="$1" new_sha="$2"
  local -a stale_projects=()
  mapfile -t stale_projects < <(stale_workspace_projects "$new_sha")
  ((${#stale_projects[@]} > 0)) || return 0
  printf '[install] ClawSeat updated %s..%s. %d project(s) have stale workspaces.\n' \
    "$old_sha" "$new_sha" "${#stale_projects[@]}" >&2
  if [[ ! -t 0 ]]; then
    warn "workspace re-render skipped in non-interactive mode; run: agent_admin engineer regenerate-workspace --project <project> --all-seats"
    return 0
  fi
  local answer=""
  read -r -p "Run regenerate-workspace --all-seats now? (Y/n) " answer
  case "${answer:-Y}" in
    Y|y|YES|Yes|yes)
      local project_name=""
      for project_name in "${stale_projects[@]}"; do
        "$PYTHON_BIN" "$AGENT_ADMIN_SCRIPT" engineer regenerate-workspace --project "$project_name" --all-seats --yes \
          || warn "workspace re-render failed for $project_name (non-fatal)"
      done
      ;;
    *)
      warn "workspace re-render skipped; run later: agent_admin engineer regenerate-workspace --project <project> --all-seats"
      ;;
  esac
}

self_update_check() {
  if ! git -C "$REPO_ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    note "[install] $REPO_ROOT is not a git worktree, skip self-update"
    return 0
  fi

  local current=""
  current="$(git -C "$REPO_ROOT" symbolic-ref --short HEAD 2>/dev/null || printf 'DETACHED')"
  if [[ "$current" != "main" ]]; then
    note "[install] non-main branch ($current), skip self-update"
    return 0
  fi

  if ! git -C "$REPO_ROOT" diff --quiet || ! git -C "$REPO_ROOT" diff --cached --quiet; then
    note "[install] dirty tree, skip self-update"
    return 0
  fi

  if ! git -C "$REPO_ROOT" remote get-url clawseat >/dev/null 2>&1; then
    note "[install] no clawseat remote, skip self-update"
    return 0
  fi

  if ! git -C "$REPO_ROOT" fetch clawseat main --quiet 2>/dev/null; then
    note "[install] fetch failed, skip self-update"
    return 0
  fi

  local local_sha="" remote_sha=""
  local_sha="$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null || true)"
  remote_sha="$(git -C "$REPO_ROOT" rev-parse clawseat/main 2>/dev/null || true)"
  [[ -n "$local_sha" && -n "$remote_sha" ]] || return 0

  if [[ "$local_sha" != "$remote_sha" ]]; then
    note "[install] updating $REPO_ROOT to clawseat/main..."
    git -C "$REPO_ROOT" reset --hard clawseat/main
    note "[install] $local_sha -> $remote_sha"
    prompt_workspace_rerender_after_update "$local_sha" "$remote_sha" || warn "workspace re-render prompt failed (non-fatal)"
    note "[install] re-executing install.sh with new code..."
    exec "$0" "$@"
  fi
}

prompt_autoupdate_optin() {
  [[ "$DRY_RUN" == "1" ]] && return 0
  [[ "$(uname -s)" == "Darwin" ]] || return 0
  command -v launchctl >/dev/null 2>&1 || return 0
  [[ -t 0 && -t 1 ]] || {
    note "[install] non-interactive terminal, skip LaunchAgent autoupdate prompt"
    return 0
  }

  if launchctl list 2>/dev/null | grep -q 'com.clawseat.autoupdate'; then
    note "[install] LaunchAgent autoupdate already installed"
    return 0
  fi

  cat <<'EOF'

----- ClawSeat 自动更新（可选） -----

ClawSeat 频繁更新。我们可以装一个后台 LaunchAgent
每天凌晨 3:00 自动同步 ~/ClawSeat 到最新 main 分支：

  - 仅在 main 分支 + 工作树 clean 时同步
  - 失败/异常时静默跳过（不影响其他流程）
  - 日志写到 ~/.clawseat/auto-update.log

是否启用？(y/N)
EOF

  local answer=""
  read -r answer
  if [[ "$answer" =~ ^[Yy]$ ]]; then
    "$PYTHON_BIN" "$CLAWSEAT_AUTOUPDATE_INSTALLER" install --repo "$REPO_ROOT"
    note "[install] LaunchAgent installed"
  else
    note "[install] LaunchAgent skipped (run scripts/install_clawseat_autoupdate.py install later if needed)"
  fi
}
