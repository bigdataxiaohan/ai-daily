# AI 日报 + 情报监控（GitHub Pages）

目标：自动抓取全球 AI 动态 + Reddit 热门话题，筛选高信号信息生成结构化日报，并部署到 GitHub Pages 随时查看。

## 功能

- 每天自动生成：
  - 产品发布 / 模型更新
  - 开源爆款（GitHub/HF 趋势）
  - 融资/商业
  - 研究/论文
  - 监管/政策
  - 安全/事故
  - Reddit 热门（可配置 subreddits）
- 输出：
  - `docs/index.html`（最新一期）
  - `docs/d/YYYY-MM-DD.html`（归档）
  - `docs/data/YYYY-MM-DD.json`（结构化数据，适合二次加工做素材）

## 部署（两种方式二选一）

### 方式 A：本机定时生成 + git push（不依赖 GitHub Actions）

1) 在服务器上保证 `BRAVE_API_KEY` 可用（推荐放到 `~/.openclaw/.env`）。

2) GitHub Pages 设置：
- Settings -> Pages
- Source 选 **Deploy from a branch**
- Branch 选 `main`，Folder 选 `/docs`

3) 在服务器上加 crontab（每天 08:00 北京时间跑一次）：

```bash
0 8 * * * bash -lc '/root/.openclaw/workspace/ai-daily-intel/scripts/run_and_push.sh' >>/root/.openclaw/workspace/ai-daily-intel/logs/cron.log 2>&1
```

### 方式 B：GitHub Actions -> Pages（不依赖服务器常驻任务）

1) 在 GitHub 仓库设置 Secrets：
- `BRAVE_API_KEY`：Brave Search API Key
（可选）`REDDIT_SUBREDDITS`

2) Settings -> Pages
- Source: **GitHub Actions**

3) 触发 workflow。

## 本地运行

```bash
cd ai-daily-intel
export BRAVE_API_KEY=...  # 必需
python3 scripts/generate.py
```

生成结果会写入 `docs/`。
