# Feishu 群组无需 @mention 配置方法

## 背景

项目面向前台的 koder 账号在飞书群中默认需要 @mention 机器人才能接收消息。通过配置 `requireMention: false`，可以让它在群中无需被 @ 就能看到所有消息。可选的系统 seat（例如显式部署的 `warden`）也可以按同样方式配置，但不再属于默认安装主链。

> 参考：v0.5 安装契约 — main agent 在群里保持 `requireMention=true`；项目面向前台的 koder 账号在群里设置 `requireMention=false`

## 配置位置

`~/.openclaw/openclaw.json` → `channels.feishu.accounts.<account_name>.groups`

## 配置方法

### 方法一：为特定群组设置

```json
"channels": {
  "feishu": {
    "accounts": {
      "<account_name>": {        // 如 "koder", "donk"；可选系统 seat 需显式部署
        "groups": {
          "<group_id>": {        // 如 "<FEISHU_GROUP_ID>"
            "requireMention": false,
            "tools": {
              "allow": ["group:openclaw"]
            }
          }
        }
      }
    }
  }
}
```

### 方法二：通配符（该账号所有群都无需 @）

```json
"channels": {
  "feishu": {
    "accounts": {
      "<account_name>": {
        "groups": {
          "*": {
            "requireMention": false,
            "tools": {
              "allow": ["group:openclaw", "group:runtime"]
            }
          }
        }
      }
    }
  }
}
```

## 操作步骤

1. **让 agent 加入群组**
   - 在飞书管理后台，将对应机器人的 App（appId）添加到目标群组
   - 等待 agent 与群建立会话

2. **确认会话已建立**
   ```bash
   python3 -c "
   import json
   import os
   openclaw_home = os.environ.get('OPENCLAW_HOME', os.path.expanduser('~/.openclaw'))
   with open(f'{openclaw_home}/agents/<account>/sessions/sessions.json') as f:
       d = json.load(f)
   for k in d.keys():
       if '<group_id>' in k:
           print('FOUND:', k)
           break
   "
   ```

3. **编辑配置**
   在 `~/.openclaw/openclaw.json` 的 `channels.feishu.accounts.<account>.groups` 中添加群组条目，设置 `requireMention: false`

4. **重启 gateway**
   ```bash
   openclaw gateway restart
   ```

## 查找群组 ID

- 在飞书开放平台群管理页面查看
- 或从 sessions.json 中查找前缀为 `group:` 的 key
- key 格式示例：`agent:koder:feishu:group:<FEISHU_GROUP_ID>`

## 相关配置项说明

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `requireMention` | `true` | `false` 时无需 @ 即可接收消息 |
| `groupPolicy` | `"open"` | 群组访问策略 |
| `groupAllowFrom` | `["*"]` | 允许的发送者 |
| `tools.allow` | `["group:openclaw"]` | 允许的工具组 |

## 注意事项

- `requireMention` 是 OpenClaw 层配置，与飞书开放平台的权限是独立的
- 需要确认机器人在飞书开放平台已有 `im:message:receive` 等权限
- 修改配置后需要重启 gateway 才能生效
