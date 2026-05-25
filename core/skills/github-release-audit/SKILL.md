---
name: github-release-audit
description: >
  Public GitHub release checklist for ClawSeat-style projects. Use when preparing
  a local working tree for public upload, sanitizing secrets and personal paths,
  creating a clean release repository, handling GitHub permissions, pushing with
  a local HTTP(S) proxy, or verifying the uploaded repository. Never request or
  paste GitHub tokens in chat.
version: 1.0.0
status: stable
---

# GitHub Release Audit

Use this skill before uploading a ClawSeat repository or fork to GitHub.

Core rule: **never publish the active working tree directly**. Create a sanitized
export, audit it, initialize a fresh Git repository, then upload that clean repo.

## 0. Non-Negotiables

- Do not ask the user to paste GitHub tokens, Feishu secrets, app secrets,
  refresh/access tokens, cookies, SSH keys, or private keys into chat.
- Do not force-push or overwrite an upstream `main` branch.
- Do not upload the original `.git` history unless it has been separately audited.
- Do not publish local runtime directories, caches, generated state, or machine
  config.
- Do not keep personal/local path names in public files. Local parent folders such
  as `E:\private-parent` must not appear in committed content.
- Use a new branch or a new repository when upstream write permissions are
  unknown.

## 1. Initial Audit

Run a public-release audit on the source tree before copying. Look for:

- real secrets or token-shaped fake values
- `.env`, credentials, private keys, certificates, service-account files
- Feishu/OpenClaw IDs such as concrete `cli_...`, `oc_...`, `ou_...`, `om_...`,
  or `chat_...` values
- personal paths such as `C:\Users\...`, `/Users/...`, `/home/<name>/...`, and
  project-local parent names
- generated/runtime folders: `.deps/`, `.venv/`, `node_modules/`, `dist/`,
  `build/`, `__pycache__/`, `.pytest_cache/`, `.tasks/`, `.tmp/`, `sessions/`
- local config such as `.config/`, `.claude/settings.json`, machine-specific TOML
- old Git history containing secrets, local paths, or internal work notes

If any finding is uncertain, treat it as publish-blocking until reviewed.

## 2. Create a Sanitized Export

Create a sibling or neutral-path export directory. Prefer a path that itself does
not contain private project context, for example:

```text
<PUBLIC_RELEASE_ROOT>
```

Exclude from the copy:

```text
.git/
.deps/
.venv/
venv/
.pytest_cache/
__pycache__/
.config/
.agent/ops/
.tasks/
.tmp/
docs/superpowers/
logs/
node_modules/
build/
dist/
*.pyc
*.log
```

Sanitize copied text files:

| Input shape | Public replacement |
| --- | --- |
| `<PRIVATE_PARENT>\project` | `<CLAWSEAT_ROOT>` or `X:\fake-home\project` |
| `C:\Users\RealName\...` | `%USERPROFILE%\...` or `C:\Users\<user>\...` |
| `/Users/name/...` | `/Users/<user>/...` or `<HOME>/...` |
| `/home/name/...` | `/home/<user>/...` or `<HOME>/...` |
| concrete `cli_...`, `oc_...`, `ou_...` | `<FEISHU_APP_ID>`, `<FEISHU_GROUP_ID>`, `<FEISHU_OPEN_ID>` |
| token-like fixtures such as `sk-...` | short neutral fixtures like `ark-fixture` |

Avoid placeholder values containing `KEY`, `TOKEN`, `SECRET`, long random-looking
strings, or provider-specific prefixes. Strict scanners may flag them even when
fake.

## 3. Public `.env.example`

A public `.env.example` should be placeholder-only and minimal. Prefer empty or
angle-bracket values:

```dotenv
CLAWSEAT_PROJECT=
CLAWSEAT_ROOT=<path-to-clawseat>
CLAWSEAT_RUNTIME_ROOT=<path-to-runtime>
CLAWSEAT_FEISHU_ENABLED=0
FEISHU_SENDER_MODE=bot-or-user
FEISHU_APP_ID=<FEISHU_APP_ID>
FEISHU_OPEN_ID=<FEISHU_OPEN_ID>
OPENCLAW_HOME=<path-to-openclaw-home>
OPENCLAW_PROJECT=<project-name>
LARK_CLI_HOME=<path-to-lark-cli-home>
```

Do not include generic `API_KEY=replace-with-your-own-key`; scanner regexes often
flag it. If API keys are user-facing, document them by variable name with an empty
value.

## 4. Public `.gitignore`

Ensure the release repo ignores:

```gitignore
.env
.env.*
!.env.example
*.pem
*.key
*.p12
*.pfx
*.jks
*.map
credentials.json
service-account*.json
machine.toml
.deps/
.venv/
venv/
node_modules/
build/
dist/
__pycache__/
.pytest_cache/
*.pyc
*.log
sessions/
private-config/
.claude/settings.json
```

Use neutral names like `private-config/` instead of secret-shaped ignore paths if
strict sanitizers flag the ignore rule itself.

## 5. Repeat Audits Until Clean

Run a second audit on the sanitized export. Required pass conditions:

- no real secrets or scanner-triggering fake values
- no concrete Feishu/OpenClaw IDs
- no personal/internal paths
- no runtime/generated directories or cache files
- only `.env.example`; no real `.env` files
- `.gitignore` covers private/generated artifacts

If the audit reports only reviewed false positives such as env variable names,
record them as warnings, not blockers.

## 6. Initialize a Clean Git Repository

Only after the sanitized export passes file-tree audit:

```bash
git init -b main
git status --short
```

Before the first commit, run one more audit. Then commit with a neutral identity if
Git user identity is not configured; do not change global Git config just to make a
commit.

```bash
GIT_AUTHOR_NAME="ClawSeat Release" \
GIT_AUTHOR_EMAIL="noreply@example.com" \
GIT_COMMITTER_NAME="ClawSeat Release" \
GIT_COMMITTER_EMAIL="noreply@example.com" \
git commit -m "chore: initial sanitized public release"
```

Expected shape:

```text
one or a few clean commits
working tree clean
no source-tree history from the private working tree
```

## 7. GitHub Authentication and Permissions

Check authentication without exposing tokens:

```bash
gh auth status
```

If `gh` shows a masked token, do not print or copy the real value. If push fails
with `403`, the active account does not have write permission to that repository.
Do not ask for a token in chat. Use one of these paths:

1. Ask the upstream owner to add the active account as collaborator.
2. Create a repository under the active account and push there.
3. Push to a fork, then open a pull request.

## 8. Safe Remote Strategy

For upstream projects, preserve upstream separately and use a writable origin:

```bash
git remote rename origin upstream
git remote add origin https://github.com/<user>/<repo>.git
```

For a new repo:

```bash
gh repo create <user>/<repo> --public --description "Sanitized public release"
```

Verify:

```bash
git remote -v
git status --short
git log --oneline --max-count=3
```

## 9. Proxy-Aware Push

If normal GitHub HTTPS push fails with connection reset or port 443 timeout, and
the user provides a local HTTP(S) proxy port, use it only for that command. Do not
write global Git proxy config.

Example for local proxy port `<proxy-port>`:

```bash
HTTPS_PROXY="http://127.0.0.1:<proxy-port>" \
HTTP_PROXY="http://127.0.0.1:<proxy-port>" \
ALL_PROXY="http://127.0.0.1:<proxy-port>" \
git push -u origin main
```

If pushing to upstream directly, prefer a new branch:

```bash
git push -u upstream main:refs/heads/<user>/sanitized-release
```

Never force-push unless the user explicitly authorizes it and the target branch is
not shared or protected.

## 10. Post-Push Verification

After push, verify with GitHub CLI and local Git:

```bash
gh repo view <user>/<repo> --json nameWithOwner,url,visibility,isEmpty,defaultBranchRef
git status --short
git log --oneline --max-count=3
```

Expected:

```text
visibility is as intended
isEmpty=false
default branch is main or expected branch
working tree clean
remote branch tracks local branch
```

Run a final post-commit/post-push audit. Acceptable warnings include:

- `.env.example` is intentionally minimal
- broad scanners flag env variable names, not values
- `.gitignore` contains protective ignore rules

## 11. What to Tell the User

Report clearly:

- public repository URL
- local sanitized repository path
- branch pushed
- whether push used a temporary proxy
- whether upstream was preserved as `upstream`
- audit verdict and remaining non-blocking warnings

Do not include tokens, secrets, complete auth status token values, or private local
paths beyond the sanitized repo path the user asked to use.
