# Workflow Spec Schema

workflow-architect Phase 3 输出的 YAML schema 定义与示例。

---

## 完整 Schema

```yaml
workflow_id: <slug>               # 必填。小写字母 + 连字符，如 video-production-pipeline-v1
name: <string>                    # 必填。人类可读名称
description: <string>             # 必填。一句话描述用户的原始操作流程
reuse_goal: one-time | template   # 必填。template 时写入 workflows 目录
created_at: <YYYY-MM-DD>          # 必填
steps:
  - step_index: <int>             # 必填，从 1 开始
    name: <string>                # 必填。步骤名称
    executor: <seat_id>           # 必填。负责执行该步骤的席位 ID
    skill: <skill_name>           # 可选。executor 使用的 skill（可含 → 链式）
    inputs:                       # 可选。该步骤的输入列表
      - <key>: <value_or_ref>     # value 可以是字面值或 "outputs of step N"
    outputs:                      # 可选。该步骤的输出列表
      - <key>: <file_path>        # 约定路径格式：/tmp/workflow/{workflow_id}/...
    notes: <string>               # 可选。补充说明
unknown_steps:                    # 必填（无未知步骤时为空列表 []）
  - step_description: <string>    # 用户原始描述
    reason: <string>              # 无法映射的原因
    suggestion: <string>          # 建议决策选项
```

---

## 字段说明

| 字段 | 必填 | 说明 |
|------|------|------|
| `workflow_id` | 是 | Slug 格式，全局唯一，建议含版本号（`-v1`） |
| `name` | 是 | 人类可读名称 |
| `description` | 是 | 用户原始操作流程的一句话描述 |
| `reuse_goal` | 是 | `one-time`：单次执行；`template`：沉淀为可复用模板 |
| `created_at` | 是 | ISO 8601 日期 |
| `steps[].step_index` | 是 | 从 1 起步，严格递增 |
| `steps[].executor` | 是 | 对应 workflow 中定义的 seat ID |
| `steps[].skill` | 否 | executor 使用的 skill；多 skill 链用 `→` 分隔 |
| `steps[].inputs` | 否 | key-value 列表；跨步引用写 `outputs of step N` |
| `steps[].outputs` | 否 | key-value 列表；路径建议放在 `/tmp/workflow/{workflow_id}/` |
| `unknown_steps` | 是 | 空列表 `[]` 或含 `step_description` / `reason` / `suggestion` |

---

## 示例：视频制作流水线

```yaml
workflow_id: video-production-pipeline-v1
name: 视频制作流水线
description: 用户原有手动流程：选题→写稿→分镜→配音→配图→剪辑→发布
reuse_goal: template
created_at: 2026-04-16
steps:
  - step_index: 1
    name: 选题与脚本撰写
    executor: koder
    skill: clawseat-intake → script-writing-expert
    inputs:
      - topic: 用户输入
    outputs:
      - script_file: /tmp/workflow/video-production-pipeline-v1/script.md

  - step_index: 2
    name: 分镜设计
    executor: koder
    skill: storyboard-forge
    inputs:
      - script_file: outputs of step 1
    outputs:
      - storyboard_manifest: /tmp/workflow/video-production-pipeline-v1/storyboard/manifest.json

  - step_index: 3
    name: 配音生成
    executor: koder
    skill: minimax-speech
    inputs:
      - script_file: outputs of step 1
    outputs:
      - audio_file: /tmp/workflow/video-production-pipeline-v1/audio.mp3

  - step_index: 4
    name: 图像生成（分镜帧）
    executor: koder
    skill: claw-image
    inputs:
      - storyboard_manifest: outputs of step 2
    outputs:
      - frames_dir: /tmp/workflow/video-production-pipeline-v1/frames/

  - step_index: 5
    name: 口型同步 + 剪辑
    executor: koder
    skill: dashscope-video-fx → cartooner-video
    inputs:
      - audio_file: outputs of step 3
      - frames_dir: outputs of step 4
    outputs:
      - final_video: /tmp/workflow/video-production-pipeline-v1/final.mp4

unknown_steps: []
```

---

## 示例：代码功能实现（含审查）

```yaml
workflow_id: feature-impl-with-review-v1
name: 功能实现 + 代码审查流水线
description: 用户需求 → 实现 → 审查 → 交付
reuse_goal: one-time
created_at: 2026-04-16
steps:
  - step_index: 1
    name: 需求澄清
    executor: koder
    skill: clawseat-intake
    inputs:
      - user_request: 用户输入
    outputs:
      - brief: /tmp/workflow/feature-impl-with-review-v1/brief.md

  - step_index: 2
    name: 代码实现
    executor: builder-1
    inputs:
      - brief: outputs of step 1
    outputs:
      - code_changes: target codebase

  - step_index: 3
    name: 代码审查
    executor: reviewer-1
    inputs:
      - code_changes: outputs of step 2
    outputs:
      - verdict: APPROVED | CHANGES_REQUESTED

unknown_steps: []
```

---

## 模板存储路径

当 `reuse_goal: template` 时，写入：

```
~/.agents/tasks/{project}/workflows/{workflow_id}.yaml
```

例：`~/.agents/tasks/install/workflows/video-production-pipeline-v1.yaml`

---

## 与 ACP Progress File Protocol 的兼容性

每个 step 的执行进度通过 `progress.jsonl` 上报，格式遵循 `hierarchical-acp-delegation` skill 中的 ACP Progress File Protocol。不在此重复定义，引用该 skill 即可。

每个 step 对应的结果文件路径约定：
```
/tmp/workflow/{workflow_id}/step_{step_index}/result.json
/tmp/workflow/{workflow_id}/step_{step_index}/progress.jsonl
```
