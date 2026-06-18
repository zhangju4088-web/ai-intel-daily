# 站点登录与即时抓取配置

当前站点发布在 GitHub Pages，本质是静态网页。它可以做页面登录门禁，但这不是银行级安全：HTML 和 JSON 仍然是静态资源。真正的私密团队站点，后续建议迁到 Cloudflare Access、Vercel/Next.js、Supabase Auth 或自建服务器。

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

## 即时抓取按钮

页面顶部的“即时抓取”按钮有两种模式：

1. 未配置接口时：打开 GitHub Actions 的手动运行页面，你登录 GitHub 后点 `Run workflow`。
2. 配置接口后：按钮会向接口发送 `POST` 请求，由接口代为触发 GitHub Actions。

不要把 GitHub Token 写进网页前端。网页源码对访问者可见，Token 会泄露。

## 推荐的免费接口方案

可以用 Cloudflare Worker 做一个很小的触发器：

- Worker 保存 `GITHUB_TOKEN` secret
- Worker 接收站点按钮的 `POST`
- Worker 调 GitHub API 触发 `pages-digest.yml`

Worker 部署好后，在 GitHub Actions Variables 里新增：

- `SITE_REFRESH_WEBHOOK_URL`：Worker 的 HTTPS 地址

然后重新运行 `Publish Daily Digest to GitHub Pages` workflow。

## Worker 触发 GitHub Actions 的核心逻辑

```js
export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") {
      return new Response(null, { headers: corsHeaders() });
    }
    if (request.method !== "POST") {
      return json({ error: "method_not_allowed" }, 405);
    }

    const body = await request.json().catch(() => ({}));
    const digestDate = body.digest_date || new Date().toISOString().slice(0, 10);
    const response = await fetch(
      "https://api.github.com/repos/zhangju4088-web/ai-intel-daily/actions/workflows/pages-digest.yml/dispatches",
      {
        method: "POST",
        headers: {
          "authorization": `Bearer ${env.GITHUB_TOKEN}`,
          "accept": "application/vnd.github+json",
          "content-type": "application/json",
          "user-agent": "ai-intel-refresh-worker",
        },
        body: JSON.stringify({
          ref: "main",
          inputs: {
            digest_date: digestDate,
            extract_limit: "16",
          },
        }),
      }
    );

    if (!response.ok) {
      return json({ error: "github_dispatch_failed", status: response.status }, 502);
    }
    return json({ ok: true, digest_date: digestDate });
  },
};

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      "content-type": "application/json",
      ...corsHeaders(),
    },
  });
}

function corsHeaders() {
  return {
    "access-control-allow-origin": "https://zhangju4088-web.github.io",
    "access-control-allow-methods": "POST, OPTIONS",
    "access-control-allow-headers": "content-type",
  };
}
```
