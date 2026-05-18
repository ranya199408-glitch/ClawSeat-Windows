# V2 词汇漂移审计 (2026-04-26)

> **目的**: 把 v1 → v2 重构期间未同步的代码、文档、配置漂移点列成总账，等批次 1 完成后统一派单清扫（issue #15）。
>
> **范围**: `clawseat-v2` worktree 全仓（不含 `.agent/ops/install-nonint/` 历史归档与 `tests/` 内部用例）。
>
> **方法**: 6 类关键词 grep；不是 hot-fix 列表，是 **vocab refresh** roadmap。

---

## 漂移分类速览

| 类别 | 典型关键词 | 影响 | 严重度 |
|------|-----------|------|--------|
| A. [DONE] 全局 memory 单例 | `machine-memory-claude` | v2 已无全局 memory（每项目自带） | 🟡 MEDIUM (M4 才删) |
| B. [DONE] 单窗 6-pane 心智 | `六宫格`, `6-pane`, `six-pane` | v2 是 workers + memories 双窗 | 🟠 HIGH (心智混乱) |
| C. [DONE] ancestor 命名 | `ancestor`（应为 `memory` seat） | v2 RFC §1 始祖 = memory seat | 🟠 HIGH (大量文档/skill 漂移) |
| D. [PARTIAL] v1 配置物件 | `PROJECT_BINDING.toml`, `WORKSPACE_CONTRACT.toml` | v2 用 `project.toml` + `project-local.toml` | 🟡 MEDIUM |
| E. [DONE] verification roster | `planner/builder/reviewer/patrol/designer` | v2 minimal 是 template-driven；verification seat 统一为 `patrol` | 🟢 CLOSED |
| F. [DONE] install-ancestor 硬编码 | `install-ancestor`, `install_ancestor` | v2 是 `install-memory` | 🟡 MEDIUM (issue #3/#12 部分覆盖) |

---

## A. [DONE] 全局 `machine-memory-claude` 引用（待 M4 删）

**v2 决议**: 每项目自带 memory seat（`<project>-memory`），全局 `machine-memory-claude` 在 M4 删除。当前是 **legacy compat**，不是要保留的设计。

**核心代码**（运行时实际读到）:
- `core/scripts/agent_admin_window.py:249-258` `build_memory_payload()` — v1 单窗 memory pane
- `core/scripts/agent_admin_window.py:254-255` 把 machine-memory-claude 加进 grid（issue #13 漂移点 5 已记录）
- `core/tui/machine_view.py` — TUI 视图字段
- `scripts/install.sh:1989` `memory_payload()` 函数 + `:2028-2044` Step 8 ensure singleton
- `scripts/hooks/memory-stop-hook.sh`

**文档**:
- `docs/INSTALL.md:298, 363` — install 流程文档
- `docs/rfc/SESSION-HANDOFF-2026-04-26.md` — handoff 快照（保留作历史，不改）
- `docs/schemas/memory-bootstrap-brief.md`
- `docs/rfc/RFC-001-self-contained-project-architecture.md` — 提到 M4 删除（保留作设计依据）
- `core/templates/memory-bootstrap.template.md` — brief 模板

**skill**:
- `core/skills/clawseat-ancestor/SKILL.md` — Phase-A B2 检查 machine-memory-claude alive

**M4 清扫策略**: 一次性删除 `build_memory_payload()` + `memory_payload()` + Step 8 + brief B2；docs 全部 strikethrough。

---

## B. [DONE] 单窗 6-pane 心智漂移（应改 v2 双窗）

**v2 决议**: workers 窗口（per project） + memories 窗口（共享）。"六宫格" 已不适用。

**代码**:
- `scripts/install.sh` 注释多处 "六宫格"
- `scripts/recover-grid.sh:53-74` — recover 路径调 `agent_admin window open-grid`，落入 v1 build_grid_payload（issue #13 漂移点 3）
- `core/scripts/agent_admin_session.py:683` — comment 提 install-ancestor

**文档**:
- `docs/ARCHITECTURE.md`
- `docs/INSTALL.md`
- `docs/ITERM_TMUX_REFERENCE.md:72,84` — recovery 文档
- `templates/README.md`

**skill**（最严重）:
- `core/skills/clawseat-ancestor/SKILL.md:229` 默认六宫格位置固定为 `Row1-Col1=ancestor / Row1-Col2=planner / ...` ← v2 不存在这个布局
- `core/skills/clawseat/SKILL.md`
- `core/skills/clawseat-install/SKILL.md`

**清扫策略**:
- skill 里"六宫格位置"全段删除，改 "v2 workers window: planner main left + N-1 right grid; memories window: tabs per project（issue #4 落地后）"
- recover-grid.sh 不需要改（issue #13 修 Python 后自动走对路径）

---

## C. [DONE-fully] ancestor 命名漂移（核心心智问题）

**v2 决议**: 始祖 = SEAT 类型，每项目 1 个；tmux 名 `<project>-memory`（不是 `<project>-ancestor`）。`ancestor` 一词只用于设计文档说明"始祖角色"，**实际文件/变量/seat id 都用 `memory`**。

**核心代码**:
- `core/scripts/agent_admin_window.py:39` — `_PRIMARY_SEAT_IDS = frozenset({"ancestor", "memory"})` 双识别（已修）
- `core/scripts/agent_admin_session.py` — 同款双识别（已修）
- `core/lib/profile_validator.py:35` — `LEGAL_SEATS` 接受 `memory` v2 primary 与 `ancestor` v1 alias
- 历史 `migrate_profile_to_v2.py` 已删除；v0.7→v2 migration 已完成，operator 需要恢复时走 `scripts/install.sh --reinstall`
- `core/scripts/seat_skill_mapping.py` — seat id → skill 映射，需检查
- `core/launchers/agent-launcher.sh` — launcher 接受 seat id

**模板/skill**:
- `core/templates/memory-bootstrap.template.md` — 主路径已改 memory，旧路径由 migration alias 兼容
- `core/templates/ancestor-engineer.toml` — 已删除 v0.7 残留
- `core/skills/clawseat-ancestor/SKILL.md` — 整个 skill 名 + 自称（建议改名 `clawseat-memory` 或加显式 alias）
- `core/skills/clawseat/SKILL.md`
- `core/skills/clawseat-koder/SKILL.md`
- `core/skills/planner/SKILL.md` — 提到 ancestor 的部分
- `core/skills/reviewer/SKILL.md` / `designer/SKILL.md`
- `core/skills/cs/SKILL.md`
- `core/skills/gstack-harness/SKILL.md` + `scripts/_common.py` + `scripts/_utils.py` + `scripts/complete_handoff.py`

**文档**:
- `README.md` (顶层)
- `CHANGELOG.md`
- `core/launchers/README.md`

**完成口径**（**不是简单 sed 替换**）:
- "始祖" 一词作为**架构概念**保留（描述项目级 singleton seat 的角色）
- "ancestor" 作为 **seat id / 文件名** 全部改 "memory"（保留 v1 legacy alias 双识别 ≥ 1 个 milestone）
- skill `clawseat-ancestor` → 重命名 `clawseat-memory` + 加 frontmatter `aliases: [clawseat-ancestor]`
- 自称 "我是 ancestor" → "我是 ${PROJECT}-memory（始祖 seat）"
- H' 已完成主路径文件/变量 rename；概念层文档可保留 ancestor 作为 v1/v2 历史术语。

---

## D. [PARTIAL] v1 配置物件 `PROJECT_BINDING.toml` / `WORKSPACE_CONTRACT.toml`

> **2026-05-12 audit**: 实际代码仍以 `PROJECT_BINDING.toml` 为 SSOT（`core/lib/project_binding.py::BINDING_FILE_NAME`），未完成迁移；本条目状态保留待统一决策。见 `docs/rfc/AUDIT-2026-05-12-CODE-QUALITY.md` §6 / §10.7。

**v2 决议**: 项目配置在 `~/.agents/projects/<project>/project.toml` + `project-local.toml`；不再用 PROJECT_BINDING / WORKSPACE_CONTRACT。

**代码**:
- `core/lib/project_binding.py` — 整个文件可能要废弃
- `core/lib/seat_resolver.py` — seat 解析读 binding
- `core/lib/state.py` — state 模型
- `core/lib/machine_config.py` — machine 层
- `core/scripts/agent_admin_template.py` / `agent_admin_layered.py` / `agent_admin_crud.py` / `agent_admin_parser.py`
- `core/scripts/heartbeat_config.py`
- 历史 `migrate_profile_to_v2.py` — 已删除；v0.7→v2 migration 完成后不再保留反向 mutation 工具
- `core/shell-scripts/send-and-verify.sh` — 通信脚本

**文档**: `README.md`, `core/templates/shared/TOOLS/feishu.md`

**清扫策略**: 先确认 v2 是否真的不需要这两个 toml；如果完全不用，整套 module 标 deprecated。**这个清扫先不动**，等 install team 跑通多项目验证（运行时是否真不读）。

---

## E. [DONE-fully] verification roster 漂移（HH 2026-04-29 清扫）

**v2 决议**: minimal = template-driven；engineering 模板可以保留更多 specialist。verification seat 的唯一 canonical id 是 `patrol`；旧 verification-seat 别名于 2026-04-29 移除。

**2026-04-29 已落地**:
- `core/scripts/patrol_alias.py` 删除；`agent_admin_resolve.py` 不再做 verification-seat alias resolve。
- `core/lib/profile_validator.py` 删除旧 verification seat 与编号形式；fan-out 只允许 `builder/reviewer/patrol`。
- `agent-admin session rename --project <project> --from <old> --to patrol` 提供一次性迁移入口。
- `scripts/migrate-qa-to-patrol.sh` 覆盖 install/cartooner/arena/lotus-radar/koder 的 project/profile/secret 迁移。
- install 侧 `patrol` LaunchAgent 模板与 label 已改为 `patrol.plist.in` / `com.clawseat.<project>.patrol`。

**保留口径**:
- `gstack-qa` / `gstack-qa-only` 是外部 skill 名与 QA testing 业务术语，不是 seat id。
- 历史 RFC / changelog 可保留旧词作为历史记录。

**验收 grep**: active runtime code may mention the removed literal only in explicit rejection messages and the migration script that rewrites legacy state to `patrol`.

---

## F. [DONE-fully] `install-ancestor` 硬编码（issue #3/#12 部分覆盖）

**已记录**: issue #3 (banner 文案)、#12 (recover-grid.sh + grid-recovery)、#13 (Python module)。

**本审计补充清单**（除 #3/#12/#13 外）:
- `docs/INSTALL.md:272, 298, 363, 550` — INSTALL 文档全程用 install-ancestor
- `docs/schemas/memory-bootstrap-brief.md:60` — schema 例子
- `docs/schemas/v0.4-layered-model.md:379` — comment
- `docs/ITERM_TMUX_REFERENCE.md:72, 84` — recovery 文档
- `core/scripts/agent_admin_session.py:683` — comment
- `scripts/install.sh:477, 1198` — `uninstall_ancestor_patrol_plist*` 函数名

**清扫策略**: 跟 #3/#12/#13 同批；函数名 `*_ancestor_patrol_*` 保留；plist 文件名/label 已在 HH 改为 patrol-only。

---

## 跨类别共性

1. **测试文件**（`tests/test_*`）大量含 v1 vocab：保留，因为测的是 v1 fixture；v2 tests 应另起一套。
2. **`.agent/ops/install-nonint/` 历史归档**：不动，全是历史决策记录。
3. **`docs/rfc/SESSION-HANDOFF-*.md`**：不动，是 ancestor 跨会话 reload 的快照。
4. **CHANGELOG.md**：不动，是历史 changelog。

---

## 落地策略

**不在批次 1 修**: 这套 vocab 漂移是大批量低紧急度清扫，会跟 install team 当前 packages A/B/C/D 抢资源。建议:

- **批次 2 (#15)**: ancestor → memory seat id 重命名 + skill rename + brief 自称 + planner SKILL roster 解耦
- **批次 3 (#15.b)**: README + ARCHITECTURE + INSTALL.md + ITERM_TMUX_REFERENCE.md 文档 vocab refresh
- **M4**: 全局 machine-memory-claude 删除 + PROJECT_BINDING.toml 废弃确认

**Owner**: builder-codex 实施 + planner-claude review + memory（我）做 vocab 词典 + 验收

**验收标准**:
- `grep -r "ancestor" core/ scripts/` 只出现在：兼容性 alias、migration 工具、CHANGELOG/RFC/handoff（历史性文档）
- `grep -r "六宫格\|six-pane" docs/ core/skills/` 返回 0 行
- `grep -r "machine-memory-claude" core/ scripts/` 只出现在：M4 删除前的 legacy compat 路径，且每处都有 `# v1 LEGACY (M4 remove)` 注释

---

*维护人*: memory（每次 install team 完成 vocab 批次后更新本文件勾消项）
