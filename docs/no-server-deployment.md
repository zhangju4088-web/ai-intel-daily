# 无服务器、无域名部署方案

## 当前结论

现在没有服务器和域名不影响 MVP。

第一版可以先用平台默认域名：

- GitHub Pages: `https://<username>.github.io/<repo>/`
- Cloudflare Pages: `https://<project>.pages.dev`
- Vercel: `https://<project>.vercel.app`

先验证每日情报质量，再决定是否购买域名和升级团队版。

## 推荐阶段

### 阶段 1：个人自用静态日报

适合现在立即开始。

架构：

```text
GitHub Actions 每天 08:00 抓取
→ 生成 daily-digest.json / daily-digest.html
→ 写入 public/index.html 和 public/archive/YYYY-MM-DD/
→ 提交 public/ 归档到仓库
→ 发布到 GitHub Pages 或 Cloudflare Pages
→ 用平台默认地址访问
```

优点：

- 不需要服务器
- 不需要域名
- 成本低
- 维护简单
- 当前本地生成的 `outputs/daily-digest.html` 可以直接作为页面发布
- 可以保留每日历史归档

限制：

- 不适合放敏感信息
- 账号密码登录不适合纯 GitHub Pages
- 收藏、待写、多人协作等状态管理能力弱

### 阶段 2：团队小范围使用

适合你准备给团队成员看时。

推荐架构：

```text
Vercel 或 Cloudflare Pages
Supabase Postgres
Supabase Auth
Cloudflare Turnstile / hCaptcha 验证码
GitHub Actions 或平台 Cron 每天 08:00 更新
```

优点：

- 仍然不需要自己买服务器
- 平台提供默认访问域名
- 支持账号密码登录
- 支持验证码
- 支持收藏、待写、多人权限
- 后续可以平滑绑定正式域名

## 平台选择

### GitHub Pages

适合只发布静态 HTML。

特点：

- 不需要独立服务器
- 可直接发布 HTML/CSS/JS
- 默认 GitHub 域名可访问
- 不适合做真正的账号密码登录

适合本项目的用途：

```text
先把每天生成的 daily-digest.html 发布出来，自己查看。
```

### Cloudflare Pages

适合静态页面和后续轻量动态能力。

特点：

- 默认 `pages.dev` 地址
- 可从 Git 仓库自动部署
- 可直接上传预构建文件
- 后续可接 Workers 做动态接口
- 后续绑定域名也方便

适合本项目的用途：

```text
发布日报页面，后续升级团队登录和接口。
```

### Vercel

适合 Next.js 前端和团队版后台。

特点：

- 默认 `vercel.app` 地址
- 对 Next.js 友好
- 支持 Serverless API
- 后续接 Supabase Auth/Postgres 方便
- 可绑定正式域名

适合本项目的用途：

```text
做真正的网站前端、登录页、栏目页、搜索页、待写收藏。
```

## 当前最推荐路线

先走两步：

1. 立即发布静态版

```text
GitHub Actions 每天生成 outputs/daily-digest.html
发布到 GitHub Pages 或 Cloudflare Pages
使用默认地址访问
```

2. 等内容质量稳定后升级团队版

```text
Next.js + Supabase + Vercel
账号密码登录 + 验证码
数据库保存事件、来源、阅读链接、收藏状态
```

## 域名什么时候买

不用现在买。

建议满足以下条件后再买：

- 连续 7-14 天日报质量稳定
- 你每天真的会打开看
- 团队成员开始使用
- 已确定网站名称
- 已确定是否未来公开

如果只是内部工具，平台默认域名长期也够用。

## 登录和验证码的现实边界

纯静态页面不能安全地实现账号密码登录。前端里写死密码、用 JS 判断密码，都不安全。

如果要团队账号登录，应该使用：

- Supabase Auth
- NextAuth/Auth.js
- Cloudflare Access
- 自建后端 Session

验证码可以用：

- Cloudflare Turnstile
- hCaptcha
- Supabase Auth CAPTCHA 集成

## 下一步开发任务

短期：

- 增加 `public/` 输出目录
- 让 `daily` 命令把 HTML 输出到可部署目录
- 增加 GitHub Pages 发布 workflow
- 生成 `public/archive/index.html` 历史归档页

中期：

- 建 Next.js 前端
- 接 Supabase Auth
- 接 PostgreSQL schema
- 做栏目页、详情页、收藏/待写
