# 站点登录与即时抓取配置

当前站点发布在 GitHub Pages，本质是静态网页。静态模式只能做页面登录门禁；如果要“管理员新增用户、普通用户修改密码、按钮即时抓取”，需要接入 `workers/auth-refresh/` 里的 Cloudflare Worker 后端。

## 配置账号密码

在 GitHub 仓库进入 `Settings` -> `Secrets and variables` -> `Actions`。

新增 Variable：

- `SITE_AUTH_USERNAME`：登录账号，例如 `admin`

新增 Secret：

- `SITE_AUTH_PASSWORD_SHA256`：密码的 SHA-256 值

本地生成密码哈希：

```bash
python3 - <<'PY'
import hashlib, getpass
password = getpass.getpass('Password: ')
print(hashlib.sha256(password.encode('utf-8')).hexdigest())
PY
```

保存后，重新运行 `Publish Daily Digest to GitHub Pages` workflow，页面就会出现登录框。

## 多用户模式

多用户模式能力：

- `admin` 高级管理员：新增用户、设置新用户初始密码、选择普通用户/高级管理员角色
- 普通用户：登录后可以修改自己的密码
- 登录用户：可以点击“即时抓取”触发 GitHub Actions 更新日报

## 部署 Cloudflare Worker

Worker 代码在：

```text
workers/auth-refresh/
```

准备工作：

1. 注册/登录 Cloudflare。
2. 安装 Wrangler：

```bash
npm install -g wrangler
wrangler login
```

3. 创建 KV：

```bash
cd workers/auth-refresh
wrangler kv namespace create AUTH_KV
```

4. 把命令输出的 KV `id` 填进 `workers/auth-refresh/wrangler.toml`：

```toml
kv_namespaces = [
  { binding = "AUTH_KV", id = "你的 KV id" }
]
```

5. 设置 Worker Secret：

```bash
wrangler secret put ADMIN_PASSWORD
wrangler secret put GITHUB_TOKEN
```

`ADMIN_PASSWORD` 是初始高级管理员密码。首次访问 Worker 时，如果 KV 里还没有 admin 用户，会自动创建。

`GITHUB_TOKEN` 需要 GitHub fine-grained token，至少给这个仓库 `Actions: write` 权限，用于触发 `pages-digest.yml`。

6. 部署 Worker：

```bash
wrangler deploy
```

部署后会得到类似：

```text
https://ai-intel-auth-refresh.<你的账号>.workers.dev
```

## 让网站启用多用户模式

在 GitHub 仓库进入 `Settings` -> `Secrets and variables` -> `Actions`。

新增 Variable：

- `SITE_AUTH_API_URL`：你的 Worker URL，例如 `https://ai-intel-auth-refresh.xxx.workers.dev`

然后重新运行 `Publish Daily Digest to GitHub Pages` workflow。

启用后，页面会自动从静态登录切换到 Worker 登录：

- 登录走 `/login`
- 读取当前用户走 `/me`
- 管理员新增用户走 `/admin/users`
- 用户修改自己密码走 `/password`
- 即时抓取走 `/refresh`

不要把 GitHub Token 写进网页前端。网页源码对访问者可见，Token 会泄露。
