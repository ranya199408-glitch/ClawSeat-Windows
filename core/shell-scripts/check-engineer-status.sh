#!/bin/bash
# check-engineer-status.sh v9 — 判断工程师状态
# 核心原理：文件状态 + pane 快照 + 最近输出变化
# 重点区分：
# - WORKING: 正在编码/构建/测试/思考推进
# - BLOCKED: 技术性阻塞（缺权限、缺文件、队列、容量、额度/订阅等）
# - DECISION_NEEDED: 等确认、等选择、等 PM 拍板
# - DELIVERED / STALLED / IDLE / CRASHED / DRIFT
#
# 用法: ./check-engineer-status.sh [seat-id...]
#       ./check-engineer-status.sh                           # 默认: $DEFAULT_SESSIONS (from profile)
#       ./check-engineer-status.sh builder-1 reviewer-1      # 检查指定 seat

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

TMUX_BIN=
AGENTCTL="$REPO_ROOT/core/shell-scripts/agentctl.sh"
TASKS_ROOT="${TASKS_ROOT:-$REPO_ROOT/.tasks}"
PATROL="${PATROL_DIR:-$TASKS_ROOT/patrol}"
DEFAULT_SESSIONS="${DEFAULT_SESSIONS:-}"
SESSIONS="${*:-$DEFAULT_SESSIONS}"

if [ -z "${SESSIONS//[[:space:]]/}" ]; then
  echo "check-engineer-status: no sessions specified and DEFAULT_SESSIONS is empty"
  echo "Usage: ./check-engineer-status.sh [seat-id ...] or set DEFAULT_SESSIONS"
  echo "Hint: for iTerm-only, ensure sessions are started before polling status."
  exit 1
fi

mkdir -p "$PATROL"

resolve_tmux_bin() {
  if command -v tmux >/dev/null 2>&1; then
    command -v tmux
    return 0
  fi
  for candidate in /opt/homebrew/bin/tmux /usr/local/bin/tmux /usr/bin/tmux /bin/tmux; do
    if [ -x "$candidate" ]; then
      echo "$candidate"
      return 0
    fi
  done
  return 1
}

TMUX_BIN="$(resolve_tmux_bin || true)"
if [ -z "$TMUX_BIN" ]; then
  echo "check-engineer-status: TMUX_MISSING - cannot resolve tmux binary"
  exit 1
fi

run_tmux_capture() {
  local command_name="$1"
  local target="$2"
  RESULT="$(env -u TMUX "$TMUX_BIN" capture-pane -t "$target" -p 2>&1)"
  local rc=$?
  if [ "$rc" -ne 0 ]; then
    echo "${command_name}: ${target} TMUX_CAPTURE_FAILED rc=$rc output=${RESULT:-no_output} (iTerm-only hard-stop)" >&2
    return 1
  fi
  printf "%s\n" "$RESULT"
}

run_tmux_meta() {
  local target="$1"
  RESULT="$(env -u TMUX "$TMUX_BIN" display-message -p -t "$target" '#{pane_current_command}|#{pane_title}' 2>&1)"
  local rc=$?
  if [ "$rc" -ne 0 ]; then
    echo "${target}: TMUX_META_FAILED rc=$rc output=${RESULT:-no_output} (iTerm-only hard-stop)" >&2
    return 1
  fi
  printf "%s\n" "$RESULT"
}

is_excluded_session() {
  # PM/debug seats excluded by naming convention
  case "$1" in
    *-pm|pm-*) return 0 ;;
    *) return 1 ;;
  esac
}

expects_mailbox() {
  # These seat roles do not maintain a TODO/DELIVERY mailbox
  case "$1" in
    koder|frontstage|monitor) return 1 ;;
    *) return 0 ;;
  esac
}

read_task_id() {
  local file="$1"
  grep '^task_id:' "$file" 2>/dev/null | head -1 | awk '{print $2}'
}

check_mailbox() {
  local seat="$1"
  local todo="$TASKS_ROOT/$seat/TODO.md"
  local delivery="$TASKS_ROOT/$seat/DELIVERY.md"
  local todo_id=""
  local delivery_id=""

  [ -f "$todo" ] && todo_id=$(read_task_id "$todo")
  [ -f "$delivery" ] && delivery_id=$(read_task_id "$delivery")

  if [ -f "$todo" ] && [ -f "$delivery" ]; then
    if [ -n "$todo_id" ] && [ "$todo_id" = "$delivery_id" ]; then
      echo "DELIVERED:${todo_id}"
    else
      echo "ACTIVE:${todo_id}:${delivery_id}"
    fi
  elif [ -f "$delivery" ]; then
    echo "DELIVERED:${delivery_id}"
  elif [ -f "$todo" ]; then
    echo "HAS_TODO:${todo_id}"
  else
    echo "EMPTY"
  fi
}

todo_file_for_session() {
  local seat="$1"
  echo "$TASKS_ROOT/$seat/TODO.md"
}

for s in $SESSIONS; do
  LAST_LINE=""
  SNAP=""
  if is_excluded_session "$s"; then
    echo "$s: SKIPPED (PM session excluded)"
    continue
  fi

  if [ -n "${AGENT_PROJECT:-}" ]; then
    SESSION_NAME="$("$AGENTCTL" session-name --project "$AGENT_PROJECT" "$s")"
  else
    SESSION_NAME="$("$AGENTCTL" session-name "$s")"
  fi
  if [ -z "$SESSION_NAME" ]; then
    # Fallback: if agentctl resolution fails but $s is already a valid tmux session, use it directly.
    # This handles unregistered seats or direct tmux session name usage.
    if env -u TMUX "$TMUX_BIN" has-session -t "$s" 2>/dev/null; then
      SESSION_NAME="$s"
    else
      echo "$s: SESSION_NOT_FOUND (name unresolved)"
      continue
    fi
  fi
  if ! RAW="$(run_tmux_capture "capture" "$SESSION_NAME")"; then
    echo "$s: SESSION_CAPTURE_FAILED (tmux command unavailable or session missing)"
    continue
  fi
  if [ -z "$RAW" ]; then
    echo "$s: SESSION_NOT_FOUND (empty capture)"
    continue
  fi
  MAILBOX=$(check_mailbox "$s")
  TODO_FILE=$(todo_file_for_session "$s")
  if ! META="$(run_tmux_meta "$SESSION_NAME")"; then
    echo "$s: SESSION_META_FAILED"
    continue
  fi
  PANE_CMD="${META%%|*}"
  PANE_TITLE="${META#*|}"
  RAW_TAIL5=$(printf '%s\n' "$RAW" | tail -5)
  RAW_TAIL20=$(printf '%s\n' "$RAW" | tail -20)
  RAW_TAIL40=$(printf '%s\n' "$RAW" | tail -40)
  ACTIVE_TODO_ID=""
  LAST_DELIVERY_ID=""

  # 输入框经验位（不换行时更稳定）
  THIRD_FROM_LAST=$(printf '%s\n' "$RAW" | tail -3 | head -1)
  SECOND_FROM_LAST=$(printf '%s\n' "$RAW" | tail -2 | head -1)

  case "$MAILBOX" in
    ACTIVE:*)
      ACTIVE_TODO_ID=$(echo "$MAILBOX" | cut -d: -f2)
      LAST_DELIVERY_ID=$(echo "$MAILBOX" | cut -d: -f3)
      ;;
    HAS_TODO:*)
      ACTIVE_TODO_ID="${MAILBOX#HAS_TODO:}"
      ;;
  esac

  # === 1. context 满 ===
  CTX=$(printf '%s\n' "$RAW" | grep -oE "[0-9]+% until auto-compact" | head -1)
  if [ -n "$CTX" ]; then
    PCT=$(echo "$CTX" | grep -oE "^[0-9]+")
    if [ "$PCT" -le 1 ]; then
      echo "$s: CONTEXT_FULL ($CTX)"
      continue
    fi
  fi

  # === 2. pane title 快速识别（优先修正 Gemini / 交付态误判）===
  if echo "$PANE_TITLE" | grep -q "Working"; then
    case "$MAILBOX" in
      EMPTY)
        if expects_mailbox "$s"; then
          echo "$s: DRIFT (working title, no TODO)"
        else
          echo "$s: WORKING (title)"
        fi
        ;;
      *) echo "$s: WORKING (title)" ;;
    esac
    continue
  fi

  if echo "$PANE_TITLE" | grep -q "Ready"; then
    case "$MAILBOX" in
      DELIVERED:*) echo "$s: DELIVERED (${MAILBOX#DELIVERED:})" ;;
      HAS_TODO:*|ACTIVE:*) echo "$s: STALLED (ready, has TODO=${ACTIVE_TODO_ID})" ;;
      EMPTY) echo "$s: IDLE (ready, no task)" ;;
    esac
    continue
  fi

  # === 2.5. 工具执行指示器（先于底部 prompt 检测，覆盖三个 harness 的 WORKING 误判）===
  # 根因：❯ / › / "Type your message" 在工具运行中也会出现在底部；
  # 下列指示器更能代表"正在执行"，先行检测可防止 IDLE/STALLED 误判。

  # Claude Code — ⏺ tool-call bullet（每次工具调用输出前出现）
  if printf '%s\n' "$RAW_TAIL20" | grep -qF '⏺'; then
    echo "$s: WORKING (tool indicator)"
    continue
  fi

  # Claude Code — ✶ ✻ ✢ ✳ ✽ 活动 spinner（模型推理阶段，区别于 braille spinner）
  if printf '%s\n' "$RAW_TAIL20" | grep -qE '✶|✻|✢|✳|✽'; then
    echo "$s: WORKING (cc spinner)"
    continue
  fi

  # 扩展 esc to interrupt 搜索范围：tail-20 ⊃ tail-10；
  # 长输出或多工具调用时 interrupt 提示可能被推出原来的 tail-10 窗口。
  if printf '%s\n' "$RAW_TAIL20" | grep -q "esc to interrupt"; then
    TIMER=$(printf '%s\n' "$RAW_TAIL5" | grep -oE "([0-9]+h )?[0-9]+m [0-9]+s|[0-9]+s · " | tail -1 | sed 's/ · $//')
    if [ -n "$TIMER" ]; then
      echo "$s: WORKING ($TIMER)"
    else
      echo "$s: WORKING (esc-extended)"
    fi
    continue
  fi

  # Codex — │ 行前缀（工具输出框；出现在 › prompt 仍在底部时）
  if printf '%s\n' "$RAW_TAIL20" | grep -qE '^[[:space:]]*│ .'; then
    echo "$s: WORKING (codex tool)"
    continue
  fi

  # Gemini — 生成中间态文本（pane title 未及更新时的兜底）
  if printf '%s\n' "$RAW_TAIL20" | grep -qiE 'Generating\.\.\.|Gemini is (working|thinking)'; then
    echo "$s: WORKING (gemini active)"
    continue
  fi

  # === 3. plan mode / decision-needed ===
  if printf '%s\n' "$RAW_TAIL5" | grep -q "plan mode on"; then
    CTX_INFO=""
    [ -n "$CTX" ] && CTX_INFO=", $CTX"
    echo "$s: DECISION_NEEDED (plan mode${CTX_INFO})"
    continue
  fi

  # === 4. 工作状态检测 ===
  # 规则：esc to interrupt 是地面真相，优先级最高。
  # 历史 timer 文本会残留在滚动区，不可信——只在确认 esc to interrupt 存在后才用 timer 提取时间。
  # 检测范围：esc to interrupt 查最后 10 行（Codex 底部有空行/建议会挤开）；timer 只查最后 5 行。

  RAW_TAIL10=$(printf '%s\n' "$RAW" | tail -10)
  HAS_ESC=""
  echo "$RAW_TAIL10" | grep -q "esc to interrupt" && HAS_ESC=1

  if [ -n "$HAS_ESC" ]; then
    # 确认在工作，尝试从最后 5 行提取 timer 显示
    TIMER=$(echo "$RAW_TAIL5" | grep -oE "([0-9]+h )?[0-9]+m [0-9]+s|[0-9]+s · " | tail -1 | sed 's/ · $//')
    if [ -n "$TIMER" ]; then
      echo "$s: WORKING ($TIMER)"
    else
      echo "$s: WORKING (active)"
    fi
    continue
  fi

  # 没有 esc to interrupt — 只查最后 5 行的 timer（避免历史残留误判）
  TIMER=$(echo "$RAW_TAIL5" | grep -oE "([0-9]+h )?[0-9]+m [0-9]+s|[0-9]+s · " | tail -1 | sed 's/ · $//')
  if [ -n "$TIMER" ]; then
    if expects_mailbox "$s" && [ "$MAILBOX" = "EMPTY" ]; then
      echo "$s: DRIFT (active timer, no TODO)"
      continue
    fi
    echo "$s: WORKING ($TIMER)"
    continue
  fi

  # === 5. 阻塞检测 ===
  if echo "$RAW_TAIL20" | grep -qE "Would you like to proceed|Yes, and bypass"; then
    echo "$s: DECISION_NEEDED (plan approval)"
    continue
  fi
  if echo "$RAW_TAIL20" | grep -qE "Action Required|Do you want to create"; then
    echo "$s: DECISION_NEEDED (needs confirmation)"
    continue
  fi
  if echo "$RAW_TAIL20" | grep -qE "Press up to edit queued messages|Queued \(press ↑ to edit\)"; then
    echo "$s: BLOCKED (queued messages)"
    continue
  fi
  if echo "$RAW_TAIL40" | grep -qiE "You've hit your usage limit|Try again later|insufficient_quota|rate limit|rate_limit|no active subscription|Too Many Requests|429|exceeded retry limit|额度不足|订阅额度不足"; then
    echo "$s: BLOCKED (usage_limit)"
    continue
  fi
  if echo "$RAW_TAIL40" | grep -qE "AT CAPACITY|quota exceeded"; then
    echo "$s: BLOCKED (capacity)"
    continue
  fi
  # Claude 评分对话框: "1: Bad  2: Fine  3: Good  0: Dismiss"
  if echo "$RAW_TAIL20" | grep -qE "^[[:space:]]*[0-9]+: [A-Za-z]"; then
    echo "$s: DECISION_NEEDED (rating dialog)"
    continue
  fi
  # 连续数字编号选项 = 等待用户选择（只查最后 20 行）
  if echo "$RAW_TAIL20" | grep -qE "^[[:space:]]*[❯●]?[[:space:]]*[1-4]\. "; then
    echo "$s: DECISION_NEEDED (awaiting selection)"
    continue
  fi

  # === 5.5 派工已提醒但未消费 ===
  if [ -n "$ACTIVE_TODO_ID" ]; then
    if [ -n "$TODO_FILE" ] && echo "$RAW_TAIL20" | grep -qF "$TODO_FILE"; then
      echo "$s: NOTIFIED (TODO=${ACTIVE_TODO_ID})"
      continue
    fi
  fi

  # === 6. 检测是否退出到了 shell（CLI 崩溃/退出）===
  if echo "$PANE_CMD" | grep -qE "bash|zsh|sh|fish"; then
    case "$MAILBOX" in
      HAS_TODO:*|ACTIVE:*)
        echo "$s: CRASHED (shell with active TODO=${ACTIVE_TODO_ID})"
        continue
        ;;
      EMPTY)
        echo "$s: IDLE (shell, no task)"
        continue
        ;;
    esac
  fi
  if printf '%s\n' "$RAW" | grep -qE "zsh: no such file|bash-[0-9]"; then
    echo "$s: CRASHED (exited to shell)"
    continue
  fi

  # === 7. thinking / spinner 中间态（掉到 diff 之前先捕获）===
  # Codex thinking / processing
  if echo "$RAW_TAIL20" | grep -qE "Topsy-turvying|Thinking|Working on it|alyzing|evising|Processing"; then
    echo "$s: WORKING (thinking)"
    continue
  fi

  # npm / spinner 进度
  if printf '%s\n' "$RAW" | grep -q "⠋\|⠙\|⠹\|⠸\|⠼\|⠴\|⠦\|⠧"; then
    echo "$s: WORKING (spinner)"
    continue
  fi

  # === 8. idle prompt 检测（优先于 diff fallback）===
  # Codex idle variant with trailing suggestion
  if echo "$RAW_TAIL20" | grep -q "› Improve documentation" || echo "$SECOND_FROM_LAST" | grep -q "^›"; then
    case "$MAILBOX" in
      DELIVERED:*) echo "$s: DELIVERED (${MAILBOX#DELIVERED:})" ;;
      HAS_TODO:*|ACTIVE:*) echo "$s: STALLED (Codex idle, has TODO=${ACTIVE_TODO_ID})" ;;
      EMPTY) echo "$s: IDLE (no task)" ;;
    esac
    continue
  fi

  # Gemini 空闲
  if echo "$RAW_TAIL5" | grep -q "Type your message" || echo "$THIRD_FROM_LAST" | grep -q "Type your message"; then
    case "$MAILBOX" in
      DELIVERED:*) echo "$s: DELIVERED (${MAILBOX#DELIVERED:})" ;;
      HAS_TODO:*|ACTIVE:*) echo "$s: STALLED (Gemini idle, has TODO=${ACTIVE_TODO_ID})" ;;
      EMPTY) echo "$s: IDLE (no task)" ;;
    esac
    continue
  fi

  # === 8.7 Claude Code 空闲：过滤噪音后最后一行是 ❯
  SNAP=$(printf '%s\n' "$RAW" | grep -v "\[°°\]" | grep -v "Pickle" | grep -v "bypass permissions" | grep -v "accept edits" | grep -v "─────" | grep -v "^[[:space:]]*$" | grep -v "ctrl+t to hide" | grep -v "● high")
  LAST_LINE=$(echo "$SNAP" | tail -1)
  # Codex idle prompt — 纯 prompt，无其他输出（需在 LAST_LINE 赋值后检测）
  if echo "$LAST_LINE" | grep -qE "^› "; then
    case "$MAILBOX" in
      DELIVERED:*) echo "$s: DELIVERED (${MAILBOX#DELIVERED:})" ;;
      HAS_TODO:*|ACTIVE:*) echo "$s: STALLED (idle prompt, has TODO=${ACTIVE_TODO_ID})" ;;
      EMPTY) echo "$s: IDLE (no task)" ;;
    esac
    continue
  fi
  if echo "$LAST_LINE" | grep -qE "^❯"; then
    case "$MAILBOX" in
      DELIVERED:*) echo "$s: DELIVERED (${MAILBOX#DELIVERED:})" ;;
      HAS_TODO:*|ACTIVE:*) echo "$s: STALLED (idle, has TODO=${ACTIVE_TODO_ID})" ;;
      EMPTY) echo "$s: IDLE (no task)" ;;
    esac
    continue
  fi

  # === 9. 空 pane（SNAP 完全空）===
  if [ -z "$SNAP" ]; then
    case "$MAILBOX" in
      DELIVERED:*) echo "$s: IDLE (empty pane, last delivered=${MAILBOX#DELIVERED:})" ;;
      HAS_TODO:*|ACTIVE:*) echo "$s: IDLE (empty pane, last todo=${ACTIVE_TODO_ID})" ;;
      EMPTY) echo "$s: IDLE (empty pane)" ;;
    esac
    continue
  fi

  # === 10. 无法判断 — 用 diff ===
  CURR="$PATROL/${s}_current.txt"
  PREV="$PATROL/${s}_previous.txt"
  echo "$SNAP" > "$CURR"

  if [ -f "$PREV" ]; then
    if diff -q "$PREV" "$CURR" >/dev/null 2>&1; then
      case "$MAILBOX" in
        DELIVERED:*) echo "$s: DELIVERED (${MAILBOX#DELIVERED:})" ;;
        EMPTY)
          if expects_mailbox "$s"; then
            echo "$s: IDLE (no task)"
          else
            echo "$s: UNKNOWN (unchanged)"
          fi
          ;;
        *) echo "$s: UNKNOWN (unchanged)" ;;
      esac
    else
      case "$MAILBOX" in
        DELIVERED:*) echo "$s: DELIVERED (${MAILBOX#DELIVERED:})" ;;
        EMPTY)
          if expects_mailbox "$s"; then
            echo "$s: DRIFT (output changed, no TODO)"
          else
            echo "$s: WORKING (output changed)"
          fi
          ;;
        *) echo "$s: WORKING (output changed)" ;;
      esac
    fi
  else
    case "$MAILBOX" in
      DELIVERED:*) echo "$s: DELIVERED (${MAILBOX#DELIVERED:})" ;;
      EMPTY)
        if expects_mailbox "$s"; then
          echo "$s: IDLE (no task)"
        else
          echo "$s: UNKNOWN (first run)"
        fi
        ;;
      *) echo "$s: UNKNOWN (first run)" ;;
    esac
  fi

  cp "$CURR" "$PREV" 2>/dev/null
done
