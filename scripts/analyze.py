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


def _parse_page_data_history(html: str, series_id: int) -> list[tuple[str, float]]:
    """Extract all (month, value) pairs from page-data for historical seeding."""
    soup = BeautifulSoup(html, 'lxml')
    tag = soup.find('script', {'type': 'application/json', 'id': 'page-data'})
    if not tag:
        return []
    try:
        payload = json.loads(tag.string or "")
        raw_a = payload.get("a", "")
        if not raw_a:
            return []
        b64_str = raw_a
        if b64_str.startswith("b'") and b64_str.endswith("'"):
            b64_str = b64_str[2:-1]
        elif b64_str.startswith('b"') and b64_str.endswith('"'):
            b64_str = b64_str[2:-1]
        decoded = base64.b64decode(b64_str).decode("utf-8")
        data = ast.literal_eval(decoded)
        x1 = data["X1"]
        y1_vals = data["Y1"]["data"]
    except Exception:
        return []

    pairs = []
    for date_raw, val in zip(x1, y1_vals):
        month_str = _parse_date_to_month(str(date_raw))
        if not month_str:
            continue
        try:
            pairs.append((month_str, float(val)))
        except (ValueError, TypeError):
            pass
    return pairs


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


CATHAY_FX_URL = "https://accessibility.cathaybk.com.tw/exchange-rate-search.aspx"
BOT_FX_CSV_URL = "https://rate.bot.com.tw/xrt/flcsv/0/day"
RTER_FX_URL = "https://tw.rter.info/capi.php"
ERAPI_FX_URL = "https://open.er-api.com/v6/latest/USD"

# Plausible USD/TWD band used to reject parsing garbage (e.g. dates, IDs)
FX_MIN, FX_MAX = 20.0, 45.0


def _plausible_fx(v) -> bool:
    try:
        return FX_MIN <= float(v) <= FX_MAX
    except (TypeError, ValueError):
        return False


def _floats_in_texts(texts: list[str]) -> list[float]:
    vals = []
    for t in texts:
        for m in re.findall(r'\d+(?:\.\d+)?', t.replace(',', '')):
            try:
                v = float(m)
            except ValueError:
                continue
            if _plausible_fx(v):
                vals.append(v)
    return vals


def fetch_cathay_usd_rate(session: requests.Session) -> tuple[float | None, float | None, float | None]:
    """
    Primary source: Cathay United Bank accessibility exchange-rate page.
    Returns (mid, spot_buy, spot_sell). Header-aware when the table exposes
    即期買入/即期賣出 columns; otherwise falls back to the min/max midpoint of
    all plausible USD/TWD numbers in the USD row.
    """
    resp = session.get(CATHAY_FX_URL, headers=HEADERS, timeout=25)
    log(f"    GET {CATHAY_FX_URL} -> HTTP {resp.status_code}")
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or 'utf-8'
    soup = BeautifulSoup(resp.text, 'lxml')

    tables = soup.find_all('table')
    log(f"    [cathay] page size {len(resp.text)} bytes, {len(tables)} tables")

    for table in tables:
        header_cells = []
        header_row = table.find('tr')
        if header_row:
            header_cells = [c.get_text(strip=True) for c in header_row.find_all(['th', 'td'])]

        for row in table.find_all('tr'):
            row_text = row.get_text()
            if '美元' not in row_text and not re.search(r'\bUSD\b', row_text):
                continue
            # Skip rows for other USD-quoted currencies (e.g. 澳幣 AUD/USD cross rates)
            if any(cross in row_text for cross in ('澳幣', '紐幣', '歐元', '英鎊', '日圓', '人民幣', '港幣')):
                continue

            cells = [c.get_text(strip=True) for c in row.find_all(['td', 'th'])]

            # Header-aware extraction: locate 即期買入 / 即期賣出 columns
            buy = sell = None
            if header_cells and len(header_cells) == len(cells):
                for i, h in enumerate(header_cells):
                    hn = h.replace(' ', '')
                    if '即期' in hn and '買' in hn and _plausible_fx(cells[i].replace(',', '')):
                        buy = float(cells[i].replace(',', ''))
                    if '即期' in hn and '賣' in hn and _plausible_fx(cells[i].replace(',', '')):
                        sell = float(cells[i].replace(',', ''))
            if buy is not None and sell is not None:
                mid = round((buy + sell) / 2, 4)
                log(f"    [cathay] header-aware → spot buy {buy} / sell {sell} / mid {mid}")
                return mid, buy, sell

            # Generic fallback: midpoint of the min/max plausible values in the row
            vals = _floats_in_texts(cells)
            if len(vals) >= 2:
                lo, hi = min(vals), max(vals)
                mid = round((lo + hi) / 2, 4)
                log(f"    [cathay] generic → values {vals} → mid {mid}")
                return mid, lo, hi
            if len(vals) == 1:
                log(f"    [cathay] single value → {vals[0]}")
                return vals[0], None, None

    log("    [cathay] USD row not found")
    return None, None, None


def fetch_bot_usd_rate(session: requests.Session) -> tuple[float | None, float | None, float | None]:
    """
    Fallback 1: Bank of Taiwan open CSV. Documented layout per row:
    [0]=currency, [1]='本行買入', [2]=cash buy, [3]=spot buy, ...,
    [11]='本行賣出', [12]=cash sell, [13]=spot sell, ...
    """
    resp = session.get(BOT_FX_CSV_URL, headers=HEADERS, timeout=25)
    log(f"    GET {BOT_FX_CSV_URL} -> HTTP {resp.status_code}")
    resp.raise_for_status()
    text = resp.content.decode('utf-8-sig', errors='replace')

    for line in text.splitlines():
        fields = [f.strip() for f in line.split(',')]
        if not fields or fields[0].upper() != 'USD':
            continue
        try:
            if len(fields) >= 14 and fields[1] == '本行買入' and fields[11] == '本行賣出':
                buy, sell = float(fields[3]), float(fields[13])
                if _plausible_fx(buy) and _plausible_fx(sell):
                    mid = round((buy + sell) / 2, 4)
                    log(f"    [bot-csv] indexed → spot buy {buy} / sell {sell} / mid {mid}")
                    return mid, buy, sell
        except (ValueError, IndexError):
            pass
        vals = _floats_in_texts(fields)
        if len(vals) >= 2:
            lo, hi = min(vals), max(vals)
            mid = round((lo + hi) / 2, 4)
            log(f"    [bot-csv] generic → mid {mid}")
            return mid, lo, hi

    log("    [bot-csv] USD line not found")
    return None, None, None


def fetch_rter_usd_rate(session: requests.Session) -> tuple[float | None, float | None, float | None]:
    """Fallback 2: tw.rter.info JSON API — {'USDTWD': {'Exrate': 32.5, ...}}."""
    resp = session.get(RTER_FX_URL, headers=HEADERS, timeout=25)
    log(f"    GET {RTER_FX_URL} -> HTTP {resp.status_code}")
    resp.raise_for_status()
    v = resp.json().get("USDTWD", {}).get("Exrate")
    if _plausible_fx(v):
        log(f"    [rter] → {v}")
        return round(float(v), 4), None, None
    return None, None, None


def fetch_erapi_usd_rate(session: requests.Session) -> tuple[float | None, float | None, float | None]:
    """Fallback 3: open.er-api.com JSON — rates.TWD."""
    resp = session.get(ERAPI_FX_URL, headers=HEADERS, timeout=25)
    log(f"    GET {ERAPI_FX_URL} -> HTTP {resp.status_code}")
    resp.raise_for_status()
    v = resp.json().get("rates", {}).get("TWD")
    if _plausible_fx(v):
        log(f"    [er-api] → {v}")
        return round(float(v), 4), None, None
    return None, None, None


def fetch_exchange_rate() -> dict:
    """
    Fetches the live USD/TWD rate through a source-fallback chain.
    Returns {} when every source fails and no previous rate can be carried over.
    """
    log("Fetching USD/TWD exchange rate ...")
    session = requests.Session()
    sources = [
        ("國泰世華銀行", fetch_cathay_usd_rate),
        ("臺灣銀行",     fetch_bot_usd_rate),
        ("RTER 即匯站",  fetch_rter_usd_rate),
        ("open.er-api.com", fetch_erapi_usd_rate),
    ]
    for name, fn in sources:
        try:
            mid, buy, sell = fn(session)
        except Exception as e:
            log(f"  {name} failed: {e}")
            continue
        if mid is not None and _plausible_fx(mid):
            log(f"  USD/TWD = {mid} (source: {name})")
            fx = {
                "usd_twd": mid,
                "source": name,
                "fetched_at": datetime.now(TW_TZ).isoformat(),
            }
            if buy is not None and sell is not None:
                fx["spot_buy"] = buy
                fx["spot_sell"] = sell
            return fx

    # Last resort: carry over the previous run's rate
    try:
        with open("data/latest.json") as f:
            prev = json.load(f).get("exchange_rate", {})
        v = prev.get("usd_twd") or prev.get("usd_twd_estimate")
        if _plausible_fx(v):
            log(f"  All sources failed; carrying over previous rate {v}")
            return {
                "usd_twd": round(float(v), 4),
                "source": f"{prev.get('source', '前次資料')}（沿用前次）",
                "fetched_at": prev.get("fetched_at") or datetime.now(TW_TZ).isoformat(),
                "carried_over": True,
            }
    except Exception:
        pass

    log("  Warning: no exchange rate available from any source")
    return {}


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


def format_exchange_rate_for_prompt(fx: dict) -> str:
    if not fx or not fx.get("usd_twd"):
        return "【美元/台幣匯率】今日無法取得實際匯率，請依近期市場資訊自行合理推估。"
    parts = [f"【美元/台幣匯率（實際抓取，非推估）】{fx['usd_twd']}"]
    if fx.get("spot_buy") is not None and fx.get("spot_sell") is not None:
        parts.append(f"（即期買入 {fx['spot_buy']} / 即期賣出 {fx['spot_sell']}）")
    parts.append(f"　來源：{fx.get('source', '未知')}")
    if fx.get("carried_over"):
        parts.append("　注意：本數值為沿用前次抓取結果")
    parts.append("\n匯率相關分析必須以上述實際匯率為基準；usd_twd_estimate 欄位請直接填入該實際數值，不要自行推估。")
    return "".join(parts)


def call_openrouter(news_content: str, date_str: str, taiwan_prices: dict, exchange_rate: dict | None = None) -> dict | None:
    if not OPENROUTER_API_KEY:
        log("ERROR: OPENROUTER_API_KEY not set")
        return None

    prices_context = format_taiwan_prices_for_prompt(taiwan_prices)
    fx_context = format_exchange_rate_for_prompt(exchange_rate or {})

    prompt = f"""你是一位台灣鋼鐵市場的資深分析師，專精廢鋼、鋼筋、型鋼之現貨市場。
今天日期：{date_str}（台灣時間）

以下是最新的台灣鋼鐵官方統計數據（來源：台灣金屬行情網）：
{prices_context}

{fx_context}

請根據以下台灣鋼鐵新聞及市場資訊，進行專業分析：

═══════════════════════════════
{news_content[:6000]}
═══════════════════════════════

關於 tomorrow_forecast（明日走勢預測）的特別要求：
1. 針對五項材料（北部廢鋼、小鋼胚、豐興鋼筋、東鋼H型鋼、中鋼棒線）分別給出「明日」的走勢判斷。
2. 每項的 reason 必須有理有據，具體引用可查證的依據，例如：
   - 上方新聞中的具體事件（廠商調價公告、開盤動態、庫存變化）
   - 國際市場變化（中國螺紋鋼期貨、唐山鋼胚、日韓出口報價、土耳其廢鋼進口價、美國廢鋼行情）
   - 原物料供需與產地事件（澳洲/巴西鐵礦砂、焦煤供應、日本H2廢鋼標售、美國HMS廢鋼出口、中國粗鋼限產或出口退稅政策、能源價格）
   - 匯率（美元/台幣走勢對進口成本的影響）
3. 禁止空泛理由（如「市場觀望」單獨成句）；每項 reason 至少要包含一個具體的因果推論鏈：事件 → 傳導路徑 → 對該材料明日價格的影響。
4. 台灣盤價多為週度調整：若你判斷明日該項盤價不會調整，direction 用 "stable" 並在 reason 說明維持盤價的原因（例如豐興週一已開平盤、成本端無明顯變動）。
5. overall_basis 要交代你整體參考了哪些時事與數據、推論的先後邏輯，讓讀者能檢驗你的推理。

請嚴格以 JSON 格式回覆，不要輸出任何其他文字：

{{
  "exchange_rate": {{
    "usd_twd_estimate": <浮點數，如 32.50>,
    "impact_on_steel": "<匯率影響說明，100字內>"
  }},
  "spread_analysis": "<利差試算分析：說明廢鋼→鋼筋→型鋼之加工利差，含匯率影響，200字內>",
  "monthly_trend": "<下月走勢完整預測，含漲跌理由與幅度預估，200字內>",
  "international_outlook": "<國際鋼鐵市場大局觀，含中國、日本、韓國、美國市場動態，300字內>",
  "tomorrow_forecast": {{
    "north_scrap_price": {{
      "direction": "<up|down|stable>",
      "change_estimate": "<幅度預估，如 +0.1~0.2 元/公斤 或 持平>",
      "reason": "<具體依據與因果推論，100字內>"
    }},
    "billet_price": {{
      "direction": "<up|down|stable>",
      "change_estimate": "<幅度預估，如 +100~200 元/公噸 或 持平>",
      "reason": "<具體依據與因果推論，100字內>"
    }},
    "fengxing_rebar_price": {{
      "direction": "<up|down|stable>",
      "change_estimate": "<幅度預估，元/公噸>",
      "reason": "<具體依據與因果推論，100字內>"
    }},
    "h_beam_price": {{
      "direction": "<up|down|stable>",
      "change_estimate": "<幅度預估，元/公噸>",
      "reason": "<具體依據與因果推論，100字內>"
    }},
    "csc_wire_rod_price": {{
      "direction": "<up|down|stable>",
      "change_estimate": "<幅度預估，元/公噸>",
      "reason": "<具體依據與因果推論，100字內>"
    }},
    "overall_basis": "<綜合推論脈絡：列出你參考的時事、國際行情、原物料供需與產地事件，說明推理順序與權重，250字內>"
  }},
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
            "max_tokens": 4000,
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


def seed_chart_history():
    """Fetch up to 12 months of history for each series and bulk-insert into chart-data.json."""
    log("Seeding historical chart data from metaltrade.tw ...")
    session = requests.Session()
    try:
        session.get(f"{METALTRADE_BASE}/ste/domestic/9/6m/", headers=METALTRADE_HEADERS, timeout=15)
        time.sleep(0.5)
    except Exception:
        pass

    series_history: dict[str, list[tuple[str, float]]] = {}
    for cat in TAIWAN_CATEGORIES:
        time.sleep(0.6)
        pairs: list[tuple[str, float]] = []
        for period in ("12m", "6m", cat.get("period", "3m")):
            url = f"{METALTRADE_BASE}/ste/domestic/{cat['id']}/{period}/"
            try:
                resp = session.get(url, headers=METALTRADE_HEADERS, timeout=25)
                resp.raise_for_status()
                resp.encoding = resp.apparent_encoding or 'utf-8'
                pairs = _parse_page_data_history(resp.text, cat["id"])
                if pairs:
                    log(f"  {cat['name']} ({period}): {len(pairs)} months")
                    break
            except Exception as e:
                log(f"  {cat['name']} {period} failed: {e}")
        if not pairs:
            log(f"  {cat['name']}: no historical data")
        else:
            series_history[cat["key"]] = pairs

    if not series_history:
        log("  No historical data retrieved, skipping seed")
        return

    chart_path = Path("data/chart-data.json")
    try:
        with open(chart_path) as f:
            cd = json.load(f)
    except Exception:
        cd = {}

    CHART_KEYS = ["billet_price", "fengxing_rebar_price", "h_beam_price",
                  "csc_wire_rod_price", "north_scrap_price", "crude_steel_production"]

    if "months" not in cd:
        cd = {"months": [], **{k: [] for k in CHART_KEYS}}

    # Build month→values map from existing chart data
    existing: dict[str, dict] = {}
    for i, m in enumerate(cd.get("months", [])):
        existing[m] = {k: cd[k][i] if i < len(cd.get(k, [])) else None for k in CHART_KEYS}

    # Merge historical pairs into existing map
    new_months = 0
    for key, pairs in series_history.items():
        for month_str, val in pairs:
            if month_str not in existing:
                existing[month_str] = {k: None for k in CHART_KEYS}
                new_months += 1
            existing[month_str][key] = val

    sorted_months = sorted(existing.keys())
    if len(sorted_months) > 36:
        sorted_months = sorted_months[-36:]

    cd["months"] = sorted_months
    for k in CHART_KEYS:
        cd[k] = [existing[m].get(k) for m in sorted_months]

    with open(chart_path, "w", encoding="utf-8") as f:
        json.dump(cd, f, ensure_ascii=False)
    log(f"Chart-data.json seeded: {new_months} new months added, {len(sorted_months)} total")


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

    exchange_rate = fetch_exchange_rate()

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

    analysis = call_openrouter(full_content, date_str, taiwan_prices, exchange_rate)

    if not analysis:
        log("FATAL: Could not obtain analysis from OpenRouter")
        sys.exit(1)

    # The real fetched rate always overrides the AI's number; the AI only
    # contributes the impact commentary. Fall back to the AI estimate (and
    # mark it as such) only when every fetch source failed.
    ai_fx = analysis.get("exchange_rate") or {}
    if exchange_rate.get("usd_twd"):
        merged_fx = {
            "usd_twd": exchange_rate["usd_twd"],
            "usd_twd_estimate": exchange_rate["usd_twd"],
            "source": exchange_rate.get("source"),
            "fetched_at": exchange_rate.get("fetched_at"),
            "impact_on_steel": ai_fx.get("impact_on_steel", ""),
        }
        if exchange_rate.get("spot_buy") is not None:
            merged_fx["spot_buy"] = exchange_rate["spot_buy"]
            merged_fx["spot_sell"] = exchange_rate["spot_sell"]
        if exchange_rate.get("carried_over"):
            merged_fx["carried_over"] = True
    else:
        merged_fx = {**ai_fx, "source": "AI 推估"}
    analysis["exchange_rate"] = merged_fx

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

    chart_path = Path("data/chart-data.json")
    try:
        existing_chart = json.loads(chart_path.read_text())
        needs_seed = len(existing_chart.get("months", [])) < 6
    except Exception:
        needs_seed = True
    if needs_seed:
        seed_chart_history()

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
