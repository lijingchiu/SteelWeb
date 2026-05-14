#!/usr/bin/env python3
"""
Taiwan Steel Price Analysis
Fetches actual prices from chart.metaltrade.tw and news from steelnews.com.tw,
then analyzes via OpenRouter API.
"""
import ast
import base64
import json
import os
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODELS = [
    "google/gemini-2.5-flash",
    "openai/gpt-4o-mini",
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

METALTRADE_BASE = "https://chart.metaltrade.tw"
METALTRADE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Referer": "https://chart.metaltrade.tw/",
}

TAIWAN_CATEGORIES = [
    {"id":  9, "period": "6m", "key": "crude_steel_production", "name": "臺灣粗鋼產量",     "unit": "萬噸"},
    {"id": 10, "period": "3m", "key": "north_scrap_price",       "name": "北部廢鋼大盤收購價", "unit": "元/公斤"},
    {"id": 11, "period": "3m", "key": "billet_price",            "name": "小鋼胚中級出廠價",  "unit": "元/公噸"},
    {"id": 12, "period": "3m", "key": "fengxing_rebar_price",    "name": "豐興鋼筋盤價",      "unit": "元/公噸"},
    {"id": 13, "period": "3m", "key": "h_beam_price",            "name": "東鋼H型鋼流通價",   "unit": "元/公噸"},
    {"id": 14, "period": "3m", "key": "csc_wire_rod_price",      "name": "中鋼棒線盤價",      "unit": "元/公噸"},
]

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


def _parse_date_to_month(date_str: str) -> str | None:
    """Convert various date formats to YYYY-MM string."""
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m", "%Y/%m"):
        try:
            return datetime.strptime(date_str.strip(), fmt).strftime("%Y-%m")
        except ValueError:
            pass
    m = re.search(r'(\d{4})[/\-年](\d{1,2})', date_str)
    if m:
        return f"{m.group(1)}-{m.group(2).zfill(2)}"
    return None


def _parse_page_data(html: str, series_id: int) -> tuple[str | None, float | None, float | None]:
    """
    Strategy 0 (primary): parse <script type="application/json" id="page-data">.
    The payload["a"] field is a base64-encoded Python literal:
      b'...' → strip b' and ' → base64.b64decode → ast.literal_eval
    Returns {'X1': [dates], 'Y1': {'data': [values]}}
    """
    soup = BeautifulSoup(html, 'lxml')
    tag = soup.find('script', {'type': 'application/json', 'id': 'page-data'})
    if not tag:
        log(f"    [page-data] script#page-data not found for series {series_id}")
        return None, None, None

    try:
        payload = json.loads(tag.string or "")
    except (json.JSONDecodeError, TypeError) as e:
        log(f"    [page-data] json.loads failed: {e}")
        return None, None, None

    raw_a = payload.get("a", "")
    if not raw_a:
        log(f"    [page-data] 'a' field missing or empty")
        return None, None, None

    # Strip Python bytes repr wrapper: b'...' or b"..."
    b64_str = raw_a
    if (b64_str.startswith("b'") and b64_str.endswith("'")):
        b64_str = b64_str[2:-1]
    elif (b64_str.startswith('b"') and b64_str.endswith('"')):
        b64_str = b64_str[2:-1]

    try:
        decoded = base64.b64decode(b64_str).decode("utf-8")
    except Exception as e:
        log(f"    [page-data] base64 decode failed: {e}")
        return None, None, None

    try:
        data = ast.literal_eval(decoded)
    except Exception as e:
        log(f"    [page-data] ast.literal_eval failed: {e}")
        log(f"    [page-data] decoded (first 300): {decoded[:300]}")
        return None, None, None

    try:
        x1 = data["X1"]
        y1_vals = data["Y1"]["data"]
    except (KeyError, TypeError) as e:
        log(f"    [page-data] X1/Y1.data not found: {e}, keys={list(data.keys()) if isinstance(data, dict) else type(data)}")
        return None, None, None

    if not x1 or not y1_vals:
        log(f"    [page-data] X1 or Y1.data is empty")
        return None, None, None

    month_str = _parse_date_to_month(str(x1[-1]))
    if not month_str:
        log(f"    [page-data] cannot parse date: {x1[-1]}")
        return None, None, None

    try:
        latest_val = float(y1_vals[-1])
        prev_val = float(y1_vals[-2]) if len(y1_vals) >= 2 else None
    except (ValueError, TypeError) as e:
        log(f"    [page-data] value conversion failed: {e}")
        return None, None, None

    log(f"    [page-data] OK → {month_str} = {latest_val} (prev: {prev_val})")
    return month_str, latest_val, prev_val


def _parse_formula(html: str, series_id: int) -> tuple[str | None, float | None, float | None]:
    """
    Strategy 1 (fallback): parse <p id="formula"> plain-text description.
    Examples:
      2026年4月平均價格為新台幣10.2元/公斤
      2026年2月臺灣粗鋼產量為111.1萬公噸
    """
    soup = BeautifulSoup(html, 'lxml')
    formula = soup.find('p', id='formula')
    if not formula:
        log(f"    [formula] p#formula not found for series {series_id}")
        return None, None, None

    text = formula.get_text(strip=True)
    log(f"    [formula] text: {text[:300]}")

    m = re.search(r'(\d{4})年(\d{1,2})月[^0-9]*?([\d,]+\.?\d*)', text)
    if m:
        month_str = f"{m.group(1)}-{m.group(2).zfill(2)}"
        try:
            val = float(m.group(3).replace(',', ''))
            log(f"    [formula] OK → {month_str} = {val}")
            return month_str, val, None
        except ValueError:
            pass

    log(f"    [formula] could not extract year/month/value")
    return None, None, None


def fetch_metaltrade_series(session: requests.Session, series_id: int, period: str = "3m") -> tuple[str | None, float | None, float | None]:
    """
    Fetches a single data series from metaltrade.tw.
    Returns (month_str, latest_value, prev_month_value) or (None, None, None) on failure.

    Parse priority:
      0. script#page-data  (base64 Python literal)
      1. p#formula         (plain-text description)
      2. HTML table rows
      3. JS labels/data arrays
      4. JSON-like date/value pairs in script tags
    """
    urls_to_try = [
        f"{METALTRADE_BASE}/ste/domestic/{series_id}/{period}/",
        f"{METALTRADE_BASE}/ste/domestic/{series_id}/",
    ]
    html = None
    for url in urls_to_try:
        try:
            resp = session.get(url, headers=METALTRADE_HEADERS, timeout=25)
            log(f"    GET {url} -> HTTP {resp.status_code}")
            log(f"    Content-Encoding: {resp.headers.get('Content-Encoding', '(none)')}")
            log(f"    Content-Type: {resp.headers.get('Content-Type', '(none)')}")
            resp.raise_for_status()
            resp.encoding = resp.apparent_encoding or 'utf-8'
            html = resp.text
            log(f"    Response size: {len(html)} bytes")
            log(f"    HTML preview: {repr(html[:200])}")
            break
        except Exception as e:
            log(f"    Warning: {url} failed: {e}")

    if not html:
        log(f"  Warning: all URLs failed for series {series_id}")
        return None, None, None

    # Strategy 0: script#page-data (primary — base64 Python literal)
    result = _parse_page_data(html, series_id)
    if result[0] is not None:
        return result

    # Strategy 1: p#formula plain-text
    result = _parse_formula(html, series_id)
    if result[0] is not None:
        return result

    soup = BeautifulSoup(html, 'lxml')

    # Strategy 2: HTML table rows
    data_rows = []
    for table in soup.find_all('table'):
        for row in table.find_all('tr'):
            cells = row.find_all(['td', 'th'])
            if len(cells) < 2:
                continue
            date_text = cells[0].get_text(strip=True)
            val_text = cells[-1].get_text(strip=True).replace(',', '').replace(' ', '')
            month_str = _parse_date_to_month(date_text)
            if not month_str:
                continue
            try:
                data_rows.append((month_str, float(val_text)))
            except ValueError:
                pass
    if data_rows:
        data_rows.sort(key=lambda x: x[0])
        latest_month, latest_val = data_rows[-1]
        prev_val = data_rows[-2][1] if len(data_rows) >= 2 else None
        log(f"    [table] OK → {latest_month} = {latest_val}")
        return latest_month, latest_val, prev_val

    # Strategy 3: JS labels/data arrays in script tags
    for script in soup.find_all('script'):
        text = script.get_text()
        labels_m = re.search(r'["\']?labels["\']?\s*:\s*\[([^\]]+)\]', text, re.DOTALL)
        data_m = re.search(r'["\']?data["\']?\s*:\s*\[([^\]]+)\]', text, re.DOTALL)
        if not (labels_m and data_m):
            continue
        try:
            raw_labels = [l.strip().strip('"\'') for l in labels_m.group(1).split(',') if l.strip()]
            raw_vals = [v.strip() for v in data_m.group(1).split(',') if v.strip()]
            pairs = []
            for lbl, v in zip(raw_labels, raw_vals):
                ms = _parse_date_to_month(lbl)
                if ms:
                    pairs.append((ms, float(v)))
            if pairs:
                pairs.sort(key=lambda x: x[0])
                latest_month, latest_val = pairs[-1]
                prev_val = pairs[-2][1] if len(pairs) >= 2 else None
                log(f"    [js-array] OK → {latest_month} = {latest_val}")
                return latest_month, latest_val, prev_val
        except (ValueError, IndexError):
            pass

    # Strategy 4: JSON-like [date, value] pairs in script tags
    for script in soup.find_all('script'):
        text = script.get_text()
        matches = re.findall(r'\[\s*["\'](\d{4}[/\-]\d{1,2})["\'],\s*([\d.]+)\s*\]', text)
        if matches:
            pairs = []
            for lbl, v in matches:
                ms = _parse_date_to_month(lbl)
                if ms:
                    try:
                        pairs.append((ms, float(v)))
                    except ValueError:
                        pass
            if pairs:
                pairs.sort(key=lambda x: x[0])
                latest_month, latest_val = pairs[-1]
                prev_val = pairs[-2][1] if len(pairs) >= 2 else None
                log(f"    [json-pairs] OK → {latest_month} = {latest_val}")
                return latest_month, latest_val, prev_val

    log(f"  Warning: all parse strategies failed for series {series_id}")
    return None, None, None


def scrape_metaltrade_taiwan() -> dict:
    """
    Fetches the 6 Taiwan domestic steel price categories from metaltrade.tw.
    Returns a dict with the data, or carries over previous data on failure.
    """
    log("Fetching Taiwan prices from chart.metaltrade.tw ...")

    session = requests.Session()
    try:
        r1 = session.get(f"{METALTRADE_BASE}/ste/domestic/9/6m/", headers=METALTRADE_HEADERS, timeout=15)
        log(f"  Warm-up GET /ste/domestic/9/6m/ -> HTTP {r1.status_code}")
        time.sleep(0.5)
    except Exception as e:
        log(f"  Warm-up failed: {e}")

    result = {}
    data_month = None

    for cat in TAIWAN_CATEGORIES:
        time.sleep(0.6)
        month_str, latest_val, prev_val = fetch_metaltrade_series(session, cat["id"], cat.get("period", "3m"))
        if month_str and latest_val is not None:
            mom_change = round(latest_val - prev_val, 4) if prev_val is not None else None
            result[cat["key"]] = {
                "value": latest_val,
                "unit": cat["unit"],
                "mom_change": mom_change,
                "month": month_str,
            }
            if data_month is None or month_str > data_month:
                data_month = month_str
            log(f"  {cat['name']}: {latest_val} {cat['unit']} ({month_str})")
        else:
            result[cat["key"]] = {
                "value": None,
                "unit": cat["unit"],
                "mom_change": None,
                "month": None,
            }
            log(f"  {cat['name']}: no data retrieved")

    return {"data_month": data_month, **result}


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


def format_taiwan_prices_for_prompt(taiwan_prices: dict) -> str:
    lines = []
    month = taiwan_prices.get("data_month", "未知")
    lines.append(f"【台灣鋼鐵實際報價 - 資料月份：{month}】")
    for cat in TAIWAN_CATEGORIES:
        key = cat["key"]
        item = taiwan_prices.get(key, {})
        val = item.get("value")
        unit = item.get("unit", "")
        mom = item.get("mom_change")
        if val is not None:
            mom_str = f"（月變動：{'+' if mom and mom > 0 else ''}{mom} {unit}）" if mom is not None else ""
            lines.append(f"  {cat['name']}：{val} {unit} {mom_str}")
        else:
            lines.append(f"  {cat['name']}：資料待取得")
    return "\n".join(lines)


def call_openrouter(news_content: str, date_str: str, taiwan_prices: dict) -> dict | None:
    if not OPENROUTER_API_KEY:
        log("ERROR: OPENROUTER_API_KEY not set")
        return None

    prices_context = format_taiwan_prices_for_prompt(taiwan_prices)

    prompt = f"""你是一位台灣鋼鐵市場的資深分析師，專精廢鋼、鋼筋、型鋼之現貨市場。
今天日期：{date_str}（台灣時間）

以下是最新的台灣鋼鐵官方統計數據（來源：台灣金屬行情網）：
{prices_context}

請根據以下台灣鋼鐵新聞及市場資訊，進行專業分析：

═══════════════════════════════
{news_content[:6000]}
═══════════════════════════════

請嚴格以 JSON 格式回覆，不要輸出任何其他文字：

{{
  "exchange_rate": {{
    "usd_twd_estimate": <浮點數，如 32.50>,
    "impact_on_steel": "<匯率影響說明，100字內>"
  }},
  "spread_analysis": "<利差試算分析：說明廢鋼→鋼筋→型鋼之加工利差，含匯率影響，200字內>",
  "monthly_trend": "<下月走勢完整預測，含漲跌理由與幅度預估，200字內>",
  "international_outlook": "<國際鋼鐵市場大局觀，含中國、日本、韓國、美國市場動態，300字內>",
  "risk_factors": [
    "<風險因素1>",
    "<風險因素2>",
    "<風險因素3>"
  ],
  "summary": "<今日市場總結（結合官方統計數據與最新新聞），150字內>",
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
                    break
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


def update_chart_data(data_month: str | None, taiwan_prices: dict):
    chart_path = Path("data/chart-data.json")
    try:
        with open(chart_path) as f:
            cd = json.load(f)
    except Exception:
        cd = {}

    if "months" not in cd:
        cd = {
            "months": [],
            "billet_price": [],
            "fengxing_rebar_price": [],
            "h_beam_price": [],
            "csc_wire_rod_price": [],
            "north_scrap_price": [],
            "crude_steel_production": [],
        }

    if data_month and data_month not in cd.get("months", []):
        cd["months"].append(data_month)
        cd["billet_price"].append(taiwan_prices.get("billet_price", {}).get("value"))
        cd["fengxing_rebar_price"].append(taiwan_prices.get("fengxing_rebar_price", {}).get("value"))
        cd["h_beam_price"].append(taiwan_prices.get("h_beam_price", {}).get("value"))
        cd["csc_wire_rod_price"].append(taiwan_prices.get("csc_wire_rod_price", {}).get("value"))
        cd["north_scrap_price"].append(taiwan_prices.get("north_scrap_price", {}).get("value"))
        cd["crude_steel_production"].append(taiwan_prices.get("crude_steel_production", {}).get("value"))

        if len(cd["months"]) > 36:
            for key in cd:
                if isinstance(cd[key], list):
                    cd[key] = cd[key][-36:]

    with open(chart_path, "w", encoding="utf-8") as f:
        json.dump(cd, f, ensure_ascii=False)
    log(f"Updated chart-data.json ({len(cd.get('months', []))} monthly data points)")


def carry_over_taiwan_prices() -> dict:
    """Load previous taiwan_prices from latest.json as fallback."""
    try:
        with open("data/latest.json") as f:
            prev = json.load(f)
        tp = prev.get("taiwan_prices", {})
        if tp and tp.get("data_month"):
            log("Using carried-over taiwan_prices from previous run")
            return tp
    except Exception:
        pass
    return {"data_month": None}


def main():
    now = datetime.now(TW_TZ)
    date_str = now.strftime("%Y-%m-%d")
    dt_str = now.isoformat()

    log(f"=== Steel Price Analysis: {date_str} ===")

    taiwan_prices = scrape_metaltrade_taiwan()
    fetched_any = any(
        taiwan_prices.get(cat["key"], {}).get("value") is not None
        for cat in TAIWAN_CATEGORIES
    )
    if not fetched_any:
        log("Warning: metaltrade.tw fetch returned no data, carrying over previous prices")
        taiwan_prices = carry_over_taiwan_prices()

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

    analysis = call_openrouter(full_content, date_str, taiwan_prices)

    if not analysis:
        log("FATAL: Could not obtain analysis from OpenRouter")
        sys.exit(1)

    output = {
        "generated_at": dt_str,
        "date": date_str,
        "model_used": analysis.pop("model_used", MODELS[0]),
        "news_count": len(articles),
        "news_sources": articles[:12],
        "taiwan_prices": taiwan_prices,
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

    update_chart_data(taiwan_prices.get("data_month"), taiwan_prices)

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
