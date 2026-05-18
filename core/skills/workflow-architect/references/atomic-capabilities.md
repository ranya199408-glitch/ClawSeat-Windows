# Atomic Capabilities

当前系统中所有可用的 seat / skill / tool 原子能力清单，供 workflow-architect Phase 2 映射使用。

---

## koder
Role: 通用技术执行与前台协调
Capabilities:
- 执行代码、配置修改、修 bug、重构
- 读/写文件、调用 API、运行测试
- 接收 clawseat-intake 的 brief，向下游 dispatch
- 作为 OpenClaw 前台接受用户输入、转达结果

## planner
Role: 任务规划与跨席位编排
Capabilities:
- 分解用户需求为子任务
- 向 builder / reviewer / patrol 等席位 dispatch 任务
- 验收子任务返回结果，决定下一步路由
- 调用 workflow-architect 设计可执行工作流

## builder-1
Role: 代码实现
Capabilities:
- 写代码、修 bug、重构
- 读/写文件、调用外部 API
- 运行测试、语法验证
- 不做用户访谈，不做代码审查

## reviewer-1
Role: 代码审查
Capabilities:
- 审查代码变更（diff / 文件列表）
- 输出 Verdict: APPROVED / APPROVED_WITH_NITS / CHANGES_REQUESTED / BLOCKED
- 不执行代码，不部署

## designer (Gemini)
Role: 创意参数填充
Capabilities:
- 填充视觉 prompt（角色描述、场景、风格词）
- 选择 AI 模型参数（temperature、style seed、aspect ratio）
- 设计创意方案，不直接执行生成工具

---

## Skills（通过 koder 调用）

## cartooner-video (via koder)
Skill: cartooner-video
Capabilities:
- 8 阶段视频工作流：脚本 → 分镜 → 配音 → 图像 → 口型同步 → 剪辑 → 交付
- 基于 `~/.openclaw/cartooner-video/workflows/index.yaml` 中的模板执行
- 输出：MP4 视频文件 + 分镜 manifest

## claw-image (via koder)
Skill: claw-image
Capabilities:
- 从零生成图片（文字 prompt → 图片）
- 改现有图片（参考图编辑 / 重绘）
- 批量出变体（同主题多版本）
- 支持写实、卡通/概念、赛博/蒸汽风格

## storyboard-forge (via koder)
Skill: storyboard-forge
Capabilities:
- 分镜执行 pipeline：脚本 → 分镜帧 + manifest.json
- 支持 6 / 12 帧或按场景自动切割
- 输出：`storyboard/manifest.json` + 帧图片

## minimax-speech (via koder)
Skill: minimax-speech
Capabilities:
- MiniMax 语音克隆（voice_id 生成）
- 文本转语音（TTS，支持中/英/中英混合）
- 输出：MP3 音频文件

## dashscope-video-fx (via koder)
Skill: dashscope-video-fx
Capabilities:
- 口型同步（lip-sync）：视频 + 音频 → 对齐嘴型
- 数字人口播：静态图 + 音频 → 说话视频
- 换脸 / 动作迁移

## script-writing-expert (via koder)
Skill: script-writing-expert
Capabilities:
- 广告/短视频脚本、短片剧本、系列大纲
- 输出 Fountain 格式或 Markdown 脚本文件

## frontend-slides (via koder)
Skill: frontend-slides
Capabilities:
- 动画 HTML / PPTX 演示文稿生成
- 支持路演、教学、内部汇报场景

## clawseat-intake (via koder)
Skill: clawseat-intake
Capabilities:
- 与用户 Socratic 式问答澄清需求
- 输出 summary_contract（结构化需求 brief）
- 不执行任务，只产出 brief

---

## 未知 / 待扩展

当无法匹配上述任何能力时，在 spec 的 `unknown_steps` 标记该步骤，并注明：
- 用户原始描述
- 初步判断缺少哪类 seat 或 skill
- 建议决策选项（新建 seat / 找现有工具 / 手工处理）
