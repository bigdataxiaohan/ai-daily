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

## 部署（推荐：GitHub Actions -> Pages）

1) 新建 GitHub 仓库，把本目录内容推上去。

2) 在 GitHub 仓库设置 Secrets：

- `BRAVE_API_KEY`：Brave Search API Key

（可选）
- `REDDIT_SUBREDDITS`：逗号分隔，如 `LocalLLaMA,MachineLearning,OpenAI,AI_Agents`

3) 开启 Pages：

- Settings -> Pages
- Source: **GitHub Actions**

4) 等待定时任务运行，或手动触发 workflow。

## 本地运行

```bash
cd ai-daily-intel
export BRAVE_API_KEY=...  # 必需
python3 scripts/generate.py
```

生成结果会写入 `docs/`。
