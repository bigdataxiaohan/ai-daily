#!/usr/bin/env python3
"""Generate AI daily intelligence report and write to docs/ for GitHub Pages.

Inputs
- BRAVE_API_KEY (required)
- REDDIT_SUBREDDITS (optional, comma-separated)

Outputs
- docs/index.html (latest run)
- docs/d/YYYY-MM-DD_HHMM.html (archive snapshots)
- docs/data/YYYY-MM-DD_HHMM.json (structured snapshots)
- docs/archive.html (archive index)

Notes
- This is heuristic news triage based on headline+snippet (no full-article parsing).
- Keep output clean: no raw URLs/domains shown; use a single "打开链接" button.
"""

from __future__ import annotations

import html
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from zoneinfo import ZoneInfo

BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"

TZ = ZoneInfo("Asia/Shanghai")

CATEGORY_QUERIES: dict[str, list[str]] = {
    # Prefer Chinese discovery (zh/CN) while keeping a few global queries.
    "产品发布/模型更新": [
        "大模型 发布 更新 版本",
        "OpenAI 发布 更新 announcement",
        "Claude 发布 更新 Anthropic",
        "Gemini 发布 更新 Google",
        "Meta AI 发布 更新",
        "NVIDIA AI 芯片 发布",
    ],
    "开源/工具爆款": [
        "GitHub Trending AI 开源",
        "Hugging Face trending 模型",
        "开源 AI Agent 框架 发布",
        "RAG 框架 开源 发布",
        "MCP server 开源 发布",
    ],
    "融资/商业": [
        "AI 融资 种子 轮 A 轮 B 轮",
        "AI 初创 收购 并购",
        "AI 产品 发布 商业化",
    ],
    "研究/论文": [
        "site:arxiv.org 大语言模型 方法",
        "多模态 论文 arXiv",
        "diffusion language model SOAR arXiv",
    ],
    "监管/政策": [
        "人工智能 监管 政策 最新",
        "欧盟 AI 法案 最新",
        "中国 人工智能 管理 办法",
        "AI 芯片 出口管制 政策",
    ],
    "安全/事故": [
        "大模型 数据泄露 事件",
        "LLM 越狱 漏洞 jailbreak",
        "AI 安全 漏洞 事件",
        "训练数据 泄露 大模型",
    ],
}

# Email/preview-card sensitive sites (we keep the web output clean too).
BLOCK_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "youtu.be",
    "news.ycombinator.com",
    "reddit.com",
    "www.reddit.com",
}

PREFERRED_HOSTS = {
    "reuters.com",
    "www.reuters.com",
    "ft.com",
    "www.ft.com",
    "bloomberg.com",
    "www.bloomberg.com",
    "cnbc.com",
    "www.cnbc.com",
    "techcrunch.com",
    "www.techcrunch.com",
    "theverge.com",
    "www.theverge.com",
    "wired.com",
    "www.wired.com",
    "nytimes.com",
    "www.nytimes.com",
    "wsj.com",
    "www.wsj.com",
    "openai.com",
    "www.openai.com",
    "anthropic.com",
    "www.anthropic.com",
    "blog.google",
    "ai.google",
    "deepmind.google",
    "www.nvidia.com",

    # Chinese high-signal outlets / portals
    "36kr.com",
    "www.36kr.com",
    "jiqizhixin.com",
    "www.jiqizhixin.com",
    "qbitai.com",
    "www.qbitai.com",
    "leiphone.com",
    "www.leiphone.com",
    "tmtpost.com",
    "www.tmtpost.com",
    "ithome.com",
    "www.ithome.com",
    "xinhuanet.com",
    "www.xinhuanet.com",
}

COMMUNITY_HOSTS = {
    "github.com",
    "www.github.com",
    "huggingface.co",
    "www.producthunt.com",
    "producthunt.com",
}


@dataclass
class NewsItem:
    title: str
    url: str
    description: str
    hostname: str
    published: str | None
    category: str
    score: float


def _req_json(url: str, headers: dict[str, str] | None = None, timeout: int = 25) -> dict[str, Any]:
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/json")
    for k, v in (headers or {}).items():
        if v:
            req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    return json.loads(raw)


def load_brave_api_key() -> str:
    k = (os.environ.get("BRAVE_API_KEY") or "").strip()
    if not k:
        raise SystemExit("Missing env var: BRAVE_API_KEY")
    return k


def brave_search(query: str, *, freshness: str = "pd", count: int = 6, country: str = "CN", search_lang: str = "zh-hans") -> list[dict[str, Any]]:
    key = load_brave_api_key()
    params = {
        "q": query,
        "country": country,
        "freshness": freshness,
        "count": str(count),
        "search_lang": search_lang,
        "spellcheck": "1",
    }
    url = f"{BRAVE_ENDPOINT}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/json")
    req.add_header("X-Subscription-Token", key)

    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            data = json.loads(raw)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace") if hasattr(e, "read") else ""
        raise RuntimeError(f"Brave HTTP {e.code}: {body[:400]}") from e

    web = data.get("web") or {}
    return list(web.get("results") or [])


def hostname_from_item(item: dict[str, Any]) -> str:
    meta = item.get("meta_url")
    if isinstance(meta, dict):
        h = meta.get("hostname")
        if isinstance(h, str) and h:
            return h
    url = str(item.get("url") or "")
    try:
        return urllib.parse.urlparse(url).hostname or ""
    except Exception:
        return ""


def is_blocked(host: str, title: str, desc: str) -> bool:
    h = (host or "").lower()
    if h in BLOCK_HOSTS:
        return True
    t = f"{title} {desc}".lower()
    return any(x in t for x in ("sponsored", "press release", "wikipedia"))


def is_allowed(host: str) -> bool:
    h = (host or "").lower()
    if not h:
        return False
    allow = set(PREFERRED_HOSTS) | set(COMMUNITY_HOSTS) | {"arxiv.org", "www.arxiv.org", "substack.com", "www.substack.com"}
    return h in allow or (h.startswith("www.") and h[4:] in allow)


def parse_ts(s: str | None) -> float:
    if not s:
        return 0.0
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        return 0.0


def score_item(host: str, title: str, published: str | None, category: str) -> float:
    h = (host or "").lower()
    base = 0.0
    if h in PREFERRED_HOSTS:
        base += 2.2
    elif h in COMMUNITY_HOSTS:
        base += 1.4
    elif h:
        base += 0.4

    if category in ("产品发布/模型更新", "开源/工具爆款"):
        base += 1.0

    tl = (title or "").lower()
    if any(w in tl for w in ("launch", "release", "announce", "introduc", "beta")):
        base += 0.6
    if any(w in tl for w in ("security", "leak", "breach", "ban", "lawsuit", "vulnerability")):
        base += 0.35

    ts = parse_ts(published)
    if ts:
        age_h = max(0.0, (time.time() - ts) / 3600.0)
        base += max(0.0, 1.2 - min(1.2, age_h / 36.0))

    return base


def clip(s: str, n: int) -> str:
    s = (s or "").strip()
    if len(s) <= n:
        return s
    return s[: n - 1].rstrip() + "…"


def reddit_fetch(subreddit: str, *, kind: str = "hot", limit: int = 8) -> list[dict[str, Any]]:
    # Best-effort without auth.
    url = f"https://www.reddit.com/r/{urllib.parse.quote(subreddit)}/{kind}.json?limit={limit}"
    try:
        data = _req_json(url, headers={"User-Agent": "openclaw-ai-daily-intel/1.0"}, timeout=20)
    except Exception:
        return []

    out: list[dict[str, Any]] = []
    try:
        children = (((data.get("data") or {}).get("children")) or [])
        for c in children:
            d = c.get("data") or {}
            title = str(d.get("title") or "").strip()
            permalink = str(d.get("permalink") or "").strip()
            if not title or not permalink:
                continue
            out.append(
                {
                    "subreddit": subreddit,
                    "title": title,
                    "url": "https://www.reddit.com" + permalink,
                    "score": int(d.get("score") or 0),
                    "comments": int(d.get("num_comments") or 0),
                }
            )
    except Exception:
        return []

    return out


def render_html(
    label: str,
    *,
    items: list[NewsItem],
    reddit: list[dict[str, Any]],
    meta: dict[str, Any],
    css_href: str,
    archive_href: str,
) -> str:
    def esc(s: str) -> str:
        return html.escape(s or "", quote=True)

    cat_color = {
        "产品发布/模型更新": "#F57C00",
        "开源/工具爆款": "#D81B60",
        "融资/商业": "#00897B",
        "研究/论文": "#455A64",
        "监管/政策": "#6D4C41",
        "安全/事故": "#B91C1C",
    }
    heat_color = {5: "#C2185B", 4: "#7B1FA2", 3: "#1976D2", 2: "#388E3C", 1: "#607D8B"}

    def stars(sc: float) -> int:
        if sc >= 5.2:
            return 5
        if sc >= 4.0:
            return 4
        if sc >= 2.9:
            return 3
        if sc >= 1.8:
            return 2
        return 1

    def pill(text_: str, bg: str) -> str:
        return (
            "<span class='pill' style='background:" + bg + "'>" + esc(text_) + "</span>"
        )

    def card(idx: int, it: NewsItem) -> str:
        k = stars(it.score)
        heat = pill("热度 " + "★" * k, heat_color.get(k, "#666"))
        cat = pill(it.category, cat_color.get(it.category, "#666"))
        title = clip(it.title, 120)
        desc = clip(it.description, 200)
        btn = f"<a class='btn' href='{esc(it.url)}'>打开链接</a>"
        parts = []
        parts.append("<div class='card'>")
        parts.append("<div class='row'>")
        parts.append("<div style='display:flex;gap:8px;flex-wrap:wrap'>" + heat + cat + "</div>")
        parts.append("</div>")
        parts.append(f"<div class='title'>{idx:02d}. <a href='{esc(it.url)}'>{esc(title)}</a></div>")
        if desc:
            parts.append(f"<div class='desc'>{esc(desc)}</div>")
        parts.append("<div style='margin-top:10px'>" + btn + "</div>")
        parts.append("</div>")
        return "".join(parts)

    # Group by category
    by_cat: dict[str, list[NewsItem]] = {}
    for it in items:
        by_cat.setdefault(it.category, []).append(it)

    html_lines: list[str] = []
    html_lines.append("<!doctype html><html><head><meta charset='utf-8'>")
    html_lines.append("<meta name='viewport' content='width=device-width, initial-scale=1' />")
    html_lines.append("<link rel='stylesheet' href='" + esc(css_href) + "' />")
    html_lines.append("<title>AI 日报 | " + esc(label) + "</title></head><body>")

    html_lines.append("<div class='wrap'>")
    html_lines.append("<div class='hero'>")
    html_lines.append("<div class='h1'>AI 日报 + 情报监控</div>")
    html_lines.append(
        "<div class='sub'>日期：" + esc(label) + "（北京时间）<br/>"
        + "来源：Brave Search（headline+snippet） + Reddit（best-effort）"
        + "</div>"
    )

    # Chips
    html_lines.append("<div class='chips'>")
    html_lines.append("<span class='chip'>总条目 " + str(len(items)) + "</span>")
    html_lines.append("<span class='chip'>Reddit 条目 " + str(len(reddit)) + "</span>")
    html_lines.append("<span class='chip'>freshness=" + esc(str(meta.get("freshness") or "pd")) + "</span>")
    html_lines.append("</div>")
    html_lines.append("</div>")

    # Highlights (top 10)
    html_lines.append("<div class='section'>")
    html_lines.append("<div class='section-title'>今日重点（Top）</div>")
    html_lines.append("<div class='grid'>")
    for i, it in enumerate(items[:10], 1):
        html_lines.append(card(i, it))
    html_lines.append("</div>")
    html_lines.append("</div>")

    # Categories
    for cat in ["产品发布/模型更新", "开源/工具爆款", "融资/商业", "研究/论文", "监管/政策", "安全/事故"]:
        lst = by_cat.get(cat) or []
        if not lst:
            continue
        html_lines.append("<div class='section'>")
        html_lines.append("<div class='section-title'>" + esc(cat) + "（" + str(len(lst)) + "）</div>")
        html_lines.append("<div class='grid'>")
        for i, it in enumerate(lst[:8], 1):
            html_lines.append(card(i, it))
        html_lines.append("</div>")
        html_lines.append("</div>")

    # Reddit section (no raw domain)
    if reddit:
        html_lines.append("<div class='section'>")
        html_lines.append("<div class='section-title'>Reddit 热门</div>")
        html_lines.append("<div class='grid'>")
        for i, r in enumerate(reddit[:10], 1):
            title = clip(str(r.get("title") or ""), 120)
            url = str(r.get("url") or "").strip()
            sub = str(r.get("subreddit") or "").strip()
            score = str(r.get("score") or "")
            comments = str(r.get("comments") or "")
            parts = []
            parts.append("<div class='card'>")
            parts.append("<div class='row'>")
            parts.append(
                "<div style='display:flex;gap:8px;flex-wrap:wrap'>"
                + pill("Reddit", "#111827")
                + pill("r/" + sub, "#374151")
                + "</div>"
            )
            parts.append("</div>")
            parts.append(f"<div class='title'>{i:02d}. <a href='{esc(url)}'>{esc(title)}</a></div>")
            parts.append(f"<div class='meta'>score={esc(score)} · comments={esc(comments)}</div>")
            parts.append("<div style='margin-top:10px'><a class='btn' href='" + esc(url) + "'>打开链接</a></div>")
            parts.append("</div>")
            html_lines.append("".join(parts))
        html_lines.append("</div>")
        html_lines.append("</div>")

    html_lines.append("<div class='foot'>Archive: <a href='" + esc(archive_href) + "'>历史归档</a></div>")
    html_lines.append("</div></body></html>")
    return "\n".join(html_lines)


def write_archive_index(entries: list[tuple[str, str]]) -> str:
    def esc(s: str) -> str:
        return html.escape(s or "", quote=True)

    lines: list[str] = []
    lines.append("<!doctype html><html><head><meta charset='utf-8'>")
    lines.append("<meta name='viewport' content='width=device-width, initial-scale=1' />")
    lines.append("<link rel='stylesheet' href='./assets/style.css' />")
    lines.append("<title>AI 日报归档</title></head><body>")
    lines.append("<div class='wrap'>")
    lines.append("<div class='hero'><div class='h1'>AI 日报归档</div><div class='sub'>历史日报列表</div></div>")
    lines.append("<div class='section'>")
    lines.append("<div class='card'>")
    lines.append("<ol style='margin:0;padding-left:18px'>")
    for rid, label in entries:
        lines.append(
            "<li style='margin:8px 0'><a href='./d/"
            + esc(rid)
            + ".html' style='color:#0b57d0;text-decoration:none;font-weight:900'>"
            + esc(label)
            + "</a></li>"
        )
    lines.append("</ol>")
    lines.append("</div>")
    lines.append("</div>")
    lines.append("</div></body></html>")
    return "\n".join(lines)


def main() -> int:
    now = datetime.now(TZ)
    date_str = now.strftime("%Y-%m-%d")
    run_id = now.strftime("%Y-%m-%d_%H%M")
    label = now.strftime("%Y-%m-%d %H:%M")

    docs_dir = os.path.join(os.path.dirname(__file__), "..", "docs")
    docs_dir = os.path.abspath(docs_dir)
    d_dir = os.path.join(docs_dir, "d")
    data_dir = os.path.join(docs_dir, "data")
    os.makedirs(d_dir, exist_ok=True)
    os.makedirs(data_dir, exist_ok=True)

    # collect news
    seen: set[str] = set()
    raw: list[NewsItem] = []
    queries_run = 0

    for cat, qs in CATEGORY_QUERIES.items():
        for q in qs:
            res = brave_search(q, freshness="pd", count=6)
            queries_run += 1
            for it in res:
                title = str(it.get("title") or "").strip()
                url = str(it.get("url") or "").strip()
                if not title or not url:
                    continue
                if url in seen:
                    continue
                host = hostname_from_item(it)
                desc = str(it.get("description") or "").strip()
                if is_blocked(host, title, desc):
                    continue
                if not is_allowed(host):
                    continue

                pub = it.get("published")
                published = str(pub) if isinstance(pub, (str, int, float)) else None

                seen.add(url)
                sc = score_item(host, title, published, cat)
                raw.append(NewsItem(title=title, url=url, description=desc, hostname=host or "(unknown)", published=published, category=cat, score=sc))

            time.sleep(0.12)

    raw.sort(key=lambda x: (x.score, parse_ts(x.published)), reverse=True)

    # reddit (best-effort)
    subs = (os.environ.get("REDDIT_SUBREDDITS") or "LocalLLaMA,MachineLearning,OpenAI,AI_Agents").strip()
    sub_list = [s.strip().lstrip("r/") for s in subs.split(",") if s.strip()]
    reddit: list[dict[str, Any]] = []
    for s in sub_list[:8]:
        reddit.extend(reddit_fetch(s, kind="hot", limit=6))
        time.sleep(0.1)

    meta = {
        "generatedAt": now.isoformat(),
        "tz": "Asia/Shanghai",
        "runId": run_id,
        "label": label,
        "freshness": "pd",
        "brave": {"country": "CN", "search_lang": "zh-hans"},
        "queriesRun": queries_run,
        "subreddits": sub_list,
    }

    payload = {
        "date": date_str,
        "runId": run_id,
        "label": label,
        "meta": meta,
        "items": [
            {
                "title": x.title,
                "url": x.url,
                "description": x.description,
                "host": x.hostname,
                "published": x.published,
                "category": x.category,
                "score": round(float(x.score), 3),
            }
            for x in raw
        ],
        "reddit": reddit,
    }

    json_path = os.path.join(data_dir, f"{run_id}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    # Convenience handle for clients.
    with open(os.path.join(data_dir, "latest.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    html_index = render_html(
        label,
        items=raw,
        reddit=reddit,
        meta=meta,
        css_href="assets/style.css",
        archive_href="archive.html",
    )
    html_day = render_html(
        label,
        items=raw,
        reddit=reddit,
        meta=meta,
        css_href="../assets/style.css",
        archive_href="../archive.html",
    )

    day_path = os.path.join(d_dir, f"{run_id}.html")
    with open(day_path, "w", encoding="utf-8") as f:
        f.write(html_day)

    # index points to latest
    idx_path = os.path.join(docs_dir, "index.html")
    with open(idx_path, "w", encoding="utf-8") as f:
        f.write(html_index)

    # archive index (all snapshots, prefer hourly stamps)
    rows: list[tuple[str, str, str]] = []
    for name in os.listdir(d_dir):
        if not name.endswith(".html"):
            continue
        stem = name[:-5]
        m = re.match(r"^(\d{4}-\d{2}-\d{2})_(\d{2})(\d{2})$", stem)
        if not m:
            # ignore legacy date-only archives
            continue
        d, hh, mm = m.group(1), m.group(2), m.group(3)
        sort_key = f"{d}_{hh}{mm}"
        label2 = f"{d} {hh}:{mm}"
        rows.append((sort_key, stem, label2))

    rows.sort(reverse=True)
    entries = [(stem, label2) for _k, stem, label2 in rows]

    archive_html = write_archive_index(entries)
    with open(os.path.join(docs_dir, "archive.html"), "w", encoding="utf-8") as f:
        f.write(archive_html)

    print(f"WROTE: {idx_path}")
    print(f"WROTE: {day_path}")
    print(f"WROTE: {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
