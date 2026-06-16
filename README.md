# Natural Comment Generator

面向公众号 AI 垂直领域文章的自然评论生成工具。输入一篇文章，输出 20 条风格不同、长度不同、观点不同的候选评论，适合用于选题反馈、评论区冷启动文案草稿、运营内部备选素材。

> 建议把输出当作“候选草稿”使用，由人工筛选和改写后发布。不要冒充真实用户或制造误导性互动。

## 功能

- 每篇文章生成默认 20 条评论
- 覆盖不同读者身份：AI 从业者、产品经理、创业者、普通用户、学生、投资观察者等
- 覆盖不同评论角度：共鸣、追问、补充、轻微质疑、案例联想、收藏转发型
- 支持 OpenAI 兼容的 Chat Completions 接口
- 没有 API Key 时自动使用本地 demo 生成器，方便先跑通流程
- 输出 Markdown 和 JSON 两种格式

## 快速开始

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
cp .env.example .env
```

把文章正文保存成文本文件，例如：

```bash
mkdir -p articles
cat > articles/sample.md <<'EOF'
# AI Agent 不是万能员工

过去一年，很多团队把 Agent 当成自动化员工来理解，但真正落地时会发现，Agent 更像是一个需要清晰上下文、明确边界和可验证反馈的协作系统。
EOF
```

生成评论：

```bash
commentgen articles/sample.md --count 20 --out outputs/sample-comments.md
```

如果 `.env` 中配置了 `OPENAI_API_KEY`，会调用模型；否则使用本地 demo 模板。

## 配置

复制 `.env.example` 为 `.env` 后按需修改：

```bash
OPENAI_API_KEY=你的_key
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4.1-mini
```

也可以使用其他 OpenAI 兼容服务，只要它支持 `/chat/completions`。

## 输出示例

```markdown
1. 做 AI 产品半年了，最认同“边界”这一点，很多失败其实不是模型不行。
2. 这篇适合发给老板看，别再一句“上 Agent”就想解决所有流程问题了。
3. 想追问一下：你觉得中小团队第一步该先做知识库，还是先改工作流？
```

## 运营建议

- 不要一次性发布全部 20 条，优先挑 3-5 条自然、具体、和文章强相关的
- 评论区要混合“短共鸣”和“有信息量的追问”，不要全部像读后感
- 适当保留轻微不同意见，评论区会更真实
- 对涉及商业结论、政策、医疗、金融等内容的评论，务必人工复核

## AI 情报网站 MVP

本仓库也开始沉淀一个面向公众号选题的 AI 情报网站 MVP。设计文档在：

- `docs/ai-intel-mvp.md`
- `docs/database-schema.sql`
- `docs/deepseek-prompts.md`
- `docs/no-server-deployment.md`
- `config/sources.yaml`

查看信源配置：

```bash
python -m intelhub.cli sources
```

抓取 RSS/公开网页候选内容预览：

```bash
python -m intelhub.cli fetch-preview \
  --source openai_news \
  --source nvidia_blog \
  --per-source 3 \
  --out outputs/intel-preview.json
```

生成本地每日情报日报：

```bash
python -m intelhub.cli daily \
  --source openai_news \
  --source nvidia_blog \
  --per-source 3 \
  --date 2026-06-15 \
  --out-json outputs/daily-digest.json \
  --out-html outputs/daily-digest.html
```

生成可直接发布的静态首页：

```bash
python -m intelhub.cli daily \
  --source openai_news \
  --source nvidia_blog \
  --per-source 3 \
  --site-dir public
```

本地预览：

```bash
python -m http.server 8765 --directory public
```

然后打开 `http://127.0.0.1:8765/`。静态页面支持搜索、Top 10、选题池、四大栏目和多个阅读原文链接。

生产环境可以去掉 `--source`，让系统按 `config/sources.yaml` 跑全部启用信源。需要让 DeepSeek 阅读正文时，增加：

```bash
python -m intelhub.cli daily \
  --extract-text \
  --summarize-with deepseek \
  --out-json outputs/daily-digest.json \
  --out-html outputs/daily-digest.html
```

GitHub Actions 自动更新草案在 `.github/workflows/daily-intel.yml`。它会在北京时间每天 08:00 运行；如果仓库配置了 `DEEPSEEK_API_KEY` secret，就提取正文并调用 DeepSeek，否则使用本地摘要兜底，产物会作为 workflow artifact 上传。

如果你还没有服务器和域名，可以先用 `.github/workflows/pages-digest.yml` 发布到 GitHub Pages。它同样每天北京时间 08:00 运行，并把日报发布成静态页面 `public/index.html`，访问地址会是 GitHub Pages 默认域名。它还会写入 `public/archive/YYYY-MM-DD/` 并提交回仓库，用来保留历史日报。

手动加入公众号公开文章链接：

```bash
python -m intelhub.cli add-manual-link \
  --source-id wx_qbitai \
  --title "文章标题" \
  --url "https://mp.weixin.qq.com/s/xxx"
```

提取公开 URL 正文：

```bash
python -m intelhub.cli extract-url \
  "https://blogs.nvidia.com/blog/nvidia-blackwell-agentperf-artificial-analysis/" \
  --out outputs/extracted-article.txt
```

使用 DeepSeek 总结本地正文文件：

```bash
python -m intelhub.cli summarize-file outputs/extracted-article.txt \
  --title "文章标题" \
  --source-name "NVIDIA Blog" \
  --source-type official \
  --url "https://example.com/article" \
  --out outputs/intel-summary.json
```

DeepSeek 环境变量：

```bash
DEEPSEEK_API_KEY=你的_key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-pro
```
