#!/usr/bin/env python3
"""
Taiwan Steel Price Analysis
Fetches news from steelnews.com.tw and analyzes via OpenRouter API.
"""
import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODELS = [
    "meta-llama/llama-3.3-70b-instruct:free",
    "google/gemma-3-27b-it:free",
    "deepseek/deepseek-r1:free",
    "mistralai/mistral-7b-instruct:free",
]
TW_TZ = timezone(timedelta(hours=8))

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

STEEL_KEYWORDS = [
    '鋼', '鐵', '廢鋼', '鋼筋', '型鋼', '鋼價', '鋼鐵', '報價', '行情',
    '噸', '廢料', 'USD', 'TWD', '匯率', '公告', '漲', '跌', '持平',
    '中鋼', '唐榮', '東和', '豐興', '宏鋼', '盛餘',
]


def log(msg: str):
    print(f"[{datetime.now(TW_TZ).strftime('%H:%M:%S')}] {msg}", flush=True)


def fetch_page(url: str, timeout: int = 15) -> str | None:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or 'utf-8'
        return resp.text
    except Exception as e:
        log(f"Warning: fetch {url} failed: {e}")
        return None


def scrape_steelnews() -> tuple[list[dict], str]:
    articles = []
    content_lines = []

    urls_to_try = [
        "https://steelnews.com.tw/index.php",
        "https://steelnews.com.tw/",
        "https://steelnews.com.tw",
    ]

    html = None
    for url in urls_to_try:
        html = fetch_page(url)
        if html:
            log(f"Fetched steelnews from: {url}")
            break

    if not html:
        log("Could not fetch steelnews.com.tw")
        return [], ""

    soup = BeautifulSoup(html, 'lxml')

    for tag in soup(['script', 'style', 'nav', 'footer']):
        tag.decompose()

    seen = set()
    for tag in soup.find_all(['a', 'h1', 'h2', 'h3', 'h4', 'p']):
        text = tag.get_text(strip=True)
        if len(text) < 8 or len(text) > 200:
            continue
        if not any(k in text for k in STEEL_KEYWORDS):
            continue
        if text in seen:
            continue
        seen.add(text)

        href = ''
        if tag.name == 'a':
            href = tag.get('href', '')
            if href and not href.startswith('http'):
                href = 'https://steelnews.com.tw/' + href.lstrip('/')

        articles.append({'title': text, 'url': href})

    article_pages_content = []
    for art in articles[:5]:
        if art['url'] and 'steelnews.com.tw' in art['url']:
            page_html = fetch_page(art['url'], timeout=10)
            if page_html:
                page_soup = BeautifulSoup(page_html, 'lxml')
                for t in page_soup(['script', 'style']):
                    t.decompose()
                page_text = page_soup.get_text(separator='\n', strip=True)
                page_lines = [l.strip() for l in page_text.split('\n') if len(l.strip()) > 8]
                relevant = [l for l in page_lines if any(k in l for k in STEEL_KEYWORDS)]
                article_pages_content.append('\n'.join(relevant[:40]))
            time.sleep(0.5)

    main_text = soup.get_text(separator='\n', strip=True)
    lines = [l.strip() for l in main_text.split('\n') if len(l.strip()) > 5]
    relevant_main = [l for l in lines if any(k in l for k in STEEL_KEYWORDS)]
    content_lines.extend(relevant_main[:80])

    for pc in article_pages_content:
        content_lines.append('\n--- 文章內容 ---\n' + pc)

    return articles[:15], '\n'.join(content_lines)


def call_openrouter(content: str, date_str: str) -> dict | None:
    if not OPENROUTER_API_KEY:
        log("ERROR: OPENROUTER_API_KEY not set")
        return None

    prompt = f"""你是一位台灣鋼鐵市場的資深分析師，專精廢鋼、鋼筋（螺紋鋼）、型鋼之現貨市場。
今天日期：{date_str}（台灣時間）

請根據以下台灣鋼鐵新聞及市場資訊，進行專業分析：

═══════════════════════════════
{content[:6500]}
═══════════════════════════════

請嚴格以 JSON 格式回覆，不要輸出任何其他文字：

{{
  "prices": {{
    "scrap_steel": {{
      "current_estimate": <整數，元/公噸>,
      "prediction_next_week": <整數，元/公噸>,
      "trend": "<up|down|stable>",
      "change_amount": <整數，可為負值，預期本週變動>,
      "reason": "<50字內說明>"
    }},
    "rebar": {{
      "current_estimate": <整數>,
      "prediction_next_week": <整數>,
      "trend": "<up|down|stable>",
      "change_amount": <整數>,
      "reason": "<50字內說明>"
    }},
    "structural_steel": {{
      "current_estimate": <整數>,
      "prediction_next_week": <整數>,
      "trend": "<up|down|stable>",
      "change_amount": <整數>,
      "reason": "<50字內說明>"
    }}
  }},
  "exchange_rate": {{
    "usd_twd_estimate": <浮點數，如 32.50>,
    "impact_on_steel": "<匯率影響說明，100字內>"
  }},
  "spread_analysis": "<利差試算分析，說明廢鋼至鋼筋、型鋼之加工利差，含匯率影響，200字內>",
  "weekly_trend": "<本週走勢完整預測，含漲跌理由與幅度預估，200字內>",
  "international_outlook": "<國際鋼鐵市場大局觀，含中國、日本、韓國、美國市場動態，300字內>",
  "risk_factors": [
    "<風險因素1>",
    "<風險因素2>",
    "<風險因素3>"
  ],
  "summary": "<今日市場總結，150字內>",
  "confidence": "<high|medium|low>"
}}"""

    req_headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://lijingchiu.github.io/SteelWeb",
        "X-Title": "Taiwan Steel Price Analysis",
    }

    for model in MODELS:
        log(f"Trying model: {model}")
        req_body = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 2500,
            "temperature": 0.25,
        }
        for attempt in range(2):
            try:
                log(f"  Calling OpenRouter (attempt {attempt + 1}/2)...")
                resp = requests.post(
                    OPENROUTER_URL,
                    headers=req_headers,
                    json=req_body,
                    timeout=90,
                )
                if resp.status_code == 429:
                    retry_after = int(resp.headers.get("Retry-After", 15))
                    wait = min(retry_after, 30)
                    log(f"  429 rate limited, waiting {wait}s then trying next model")
                    time.sleep(wait)
                    break  # skip remaining attempts for this model
                resp.raise_for_status()
                data = resp.json()

                raw = data["choices"][0]["message"]["content"].strip()
                log(f"  Got response ({len(raw)} chars) from {model}")

                start = raw.find('{')
                end = raw.rfind('}') + 1
                if start >= 0 and end > start:
                    parsed = json.loads(raw[start:end])
                    parsed["model_used"] = model
                    return parsed
                else:
                    log("  Warning: no JSON found in response")

            except json.JSONDecodeError as e:
                log(f"  JSON parse error: {e}")
            except Exception as e:
                log(f"  OpenRouter error: {e}")

            if attempt == 0:
                log("  Retrying in 10s...")
                time.sleep(10)

    log("FATAL: all models exhausted")
    return None


def update_chart_data(date_str: str, prices: dict):
    chart_path = Path("data/chart-data.json")
    try:
        with open(chart_path) as f:
            cd = json.load(f)
    except Exception:
        cd = {"dates": [], "scrap_steel": [], "rebar": [], "structural_steel": []}

    if date_str not in cd["dates"]:
        cd["dates"].append(date_str)
        cd["scrap_steel"].append(prices.get("scrap_steel", {}).get("current_estimate"))
        cd["rebar"].append(prices.get("rebar", {}).get("current_estimate"))
        cd["structural_steel"].append(prices.get("structural_steel", {}).get("current_estimate"))

        if len(cd["dates"]) > 90:
            cd["dates"] = cd["dates"][-90:]
            cd["scrap_steel"] = cd["scrap_steel"][-90:]
            cd["rebar"] = cd["rebar"][-90:]
            cd["structural_steel"] = cd["structural_steel"][-90:]

    with open(chart_path, "w", encoding="utf-8") as f:
        json.dump(cd, f, ensure_ascii=False)
    log(f"Updated chart-data.json ({len(cd['dates'])} data points)")


def main():
    now = datetime.now(TW_TZ)
    date_str = now.strftime("%Y-%m-%d")
    dt_str = now.isoformat()

    log(f"=== Steel Price Analysis: {date_str} ===")

    articles, content = scrape_steelnews()
    log(f"Scraped {len(articles)} articles, {len(content)} chars of content")

    if not content.strip():
        content = (
            f"今日（{date_str}）無法取得最新新聞。"
            "請根據近期台灣鋼鐵市場趨勢、國際原物料行情、中國出口政策、"
            "美元/台幣匯率等因素，進行合理推估與分析。"
        )

    article_titles = "\n".join(f"  - {a['title']}" for a in articles)
    full_content = f"【新聞標題列表】\n{article_titles}\n\n【網頁擷取內容】\n{content}"

    analysis = call_openrouter(full_content, date_str)

    if not analysis:
        log("FATAL: Could not obtain analysis from OpenRouter")
        sys.exit(1)

    output = {
        "generated_at": dt_str,
        "date": date_str,
        "model_used": analysis.pop("model_used", MODELS[0]),
        "news_count": len(articles),
        "news_sources": articles[:12],
        **analysis,
    }

    Path("data/history").mkdir(parents=True, exist_ok=True)

    with open("data/latest.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    log("Saved data/latest.json")

    hist_path = f"data/history/{date_str}.json"
    with open(hist_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    log(f"Saved {hist_path}")

    update_chart_data(date_str, analysis.get("prices", {}))

    idx_path = Path("data/history-index.json")
    try:
        index = json.loads(idx_path.read_text())
    except Exception:
        index = []
    if date_str not in index:
        index.append(date_str)
    index = sorted(set(index), reverse=True)[:90]
    idx_path.write_text(json.dumps(index, ensure_ascii=False))
    log("Updated history-index.json")

    log("=== Analysis complete! ===")


if __name__ == "__main__":
    main()
