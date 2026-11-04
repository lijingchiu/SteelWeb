#!/usr/bin/env python3
"""
Taiwan Steel & Construction Materials Analysis.

1. Fetches every material price series (scripts/materials.py) and the live
   USD/TWD rate.
2. Scores past forecasts against newly published monthly prices.
3. Asks the model (OpenAI GPT-6.1 Terra with web search; OpenRouter as
   fallback) for a weekly + next-month price forecast and market analysis.
"""
import json
import os
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from concurrent.futures import ThreadPoolExecutor

import prompts
from suggestions import make_suggestions
from materials import build_materials, taiwan_prices_from_materials, write_outputs

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_URL = "https://api.openai.com/v1/responses"
OPENAI_MODEL = "gpt-6.1-terra"
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
# (provider, model, use web search). Tried in order until one returns a valid forecast.
MODEL_CHAIN = [
    ("openai",     OPENAI_MODEL,                True),
    ("openrouter", "openai/gpt-6.1-terra",      True),
    ("openrouter", "openai/gpt-6-luna",         True),
    ("openrouter", "google/gemini-2.5-flash",   False),
]
REASONING_EFFORT = "medium"
MAX_OUTPUT_TOKENS = 25000
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

FORECAST_ITEMS = [
    ("north_scrap_price",    "北部廢鋼大盤收購價", "元/公斤"),
    ("billet_price",         "小鋼胚中級出廠價",   "元/公噸"),
    ("fengxing_rebar_price", "豐興鋼筋盤價",       "元/公噸"),
    ("h_beam_price",         "東鋼H型鋼流通價",    "元/公噸"),
    ("csc_wire_rod_price",   "中鋼棒線盤價",       "元/公噸"),
]
HEADLINE_NAMES = {
    "crude_steel_production": "臺灣粗鋼產量",
    **{k: n for k, n, _ in FORECAST_ITEMS},
}
ACCURACY_PATH = Path("data/accuracy.json")
HISTORY_DIR = Path("data/history")
# A published monthly change within ±0.3% counts as "stable" when scoring.
STABLE_BAND_PCT = 0.3
STEELNEWS_URL = "https://steelnews.com.tw/index.php"


def log(msg: str):
    print(f"[{datetime.now(TW_TZ).strftime('%H:%M:%S')}] {msg}", flush=True)


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


def scrape_steelnews_headlines() -> list[dict]:
    """Public headline list from SNN. Article bodies are member-only, so only titles are used."""
    try:
        r = requests.get(STEELNEWS_URL, headers=HEADERS, timeout=25)
        r.raise_for_status()
        r.encoding = r.apparent_encoding or "utf-8"
    except Exception as e:
        log(f"Warning: steelnews fetch failed: {e}")
        return []
    soup = BeautifulSoup(r.text, "lxml")
    seen, out = set(), []
    for a in soup.select('a[href*="news/content?id="]'):
        title = a.get_text(" ", strip=True)
        if len(title) < 6 or title in seen:
            continue
        seen.add(title)
        href = a["href"]
        url = href if href.startswith("http") else "https://steelnews.com.tw/" + href.lstrip("/")
        out.append({"title": title, "url": url, "source": "SNN 環宇鋼鐵網", "date": ""})
    log(f"steelnews: {len(out)} headlines")
    return out[:30]


# ── Forecast windows ──────────────────────────────────────

def next_month(month: str) -> str:
    y, m = map(int, month.split("-"))
    return f"{y + (m == 12)}-{1 if m == 12 else m + 1:02d}"


def forecast_week(now: datetime) -> tuple[str, str]:
    """On weekends the forecast covers next week, otherwise the current week."""
    monday = (now + timedelta(days=7 - now.weekday())) if now.weekday() >= 5 else (now - timedelta(days=now.weekday()))
    sunday = monday + timedelta(days=6)
    label = "下週" if now.weekday() >= 5 else "本週"
    return label, f"{monday:%m/%d}–{sunday:%m/%d}"


def forecast_targets(materials: dict) -> dict:
    by_id = {it["id"]: it for it in materials.get("items", [])}
    targets = {}
    for key, _, _ in FORECAST_ITEMS:
        it = by_id.get(key)
        if it and it.get("period") and len(it["period"]) == 7:
            targets[key] = {
                "baseline_month": it["period"],
                "baseline_value": it["value"],
                "target_month": next_month(it["period"]),
            }
    return targets


# ── Accuracy tracking ─────────────────────────────────────

def direction_of(pct: float) -> str:
    if pct > STABLE_BAND_PCT:
        return "up"
    if pct < -STABLE_BAND_PCT:
        return "down"
    return "stable"


def score_accuracy(materials: dict, history_dir: Path = HISTORY_DIR) -> dict:
    """Compare every stored next-month forecast with the monthly average published later."""
    actual = {it["id"]: dict(it.get("history", [])) for it in materials.get("items", [])}
    names = {k: n for k, n, _ in FORECAST_ITEMS}
    records, pending = [], 0
    for path in sorted(history_dir.glob("*.json")):
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        pf = d.get("price_forecast") or {}
        for key, f in (pf.get("items") or {}).items():
            tgt = (pf.get("targets") or {}).get(key)
            pred = ((f or {}).get("next_month") or {}).get("direction")
            if not tgt or pred not in ("up", "down", "stable"):
                continue
            real = actual.get(key, {}).get(tgt["target_month"])
            base = tgt.get("baseline_value")
            if real is None or not base:
                pending += 1
                continue
            pct = (real - base) / base * 100
            act = direction_of(pct)
            records.append({
                "date": d.get("date"), "key": key, "name": names.get(key, key),
                "target_month": tgt["target_month"], "predicted": pred, "actual": act,
                "actual_pct": round(pct, 2), "hit": pred == act,
            })
    per_item = {}
    for key, name, _ in FORECAST_ITEMS:
        rs = [r for r in records if r["key"] == key]
        per_item[key] = {"name": name, "hits": sum(r["hit"] for r in rs), "total": len(rs)}
    total = len(records)
    return {
        "updated_at": datetime.now(TW_TZ).isoformat(),
        "method": f"每日的「下一期月均價」方向預測，與台灣金屬行情網日後公布的月均價比較；月變動在 ±{STABLE_BAND_PCT}% 內視為持平。",
        "overall": {"hits": sum(r["hit"] for r in records), "total": total},
        "per_item": per_item,
        "pending": pending,
        "recent": sorted(records, key=lambda r: (r["date"] or "", r["key"]), reverse=True)[:40],
    }


def accuracy_for_prompt(acc: dict) -> str:
    o = acc.get("overall", {})
    if not o.get("total"):
        return f"【你過去預測的準確率】尚無可驗證的紀錄（{acc.get('pending', 0)} 筆預測等待官方月均價公布）。"
    lines = [f"【你過去預測的準確率】下一期月均價方向命中 {o['hits']}/{o['total']}（{o['hits'] / o['total']:.0%}）"]
    for v in acc["per_item"].values():
        if v["total"]:
            lines.append(f"  {v['name']}：{v['hits']}/{v['total']}")
    misses = [r for r in acc.get("recent", []) if not r["hit"]][:5]
    if misses:
        lines.append("  最近的誤判（請檢討原因並避免重蹈）：")
        for r in misses:
            lines.append(f"    {r['date']} 預測 {r['name']} {r['target_month']} 為 {r['predicted']}，實際 {r['actual']}（{r['actual_pct']:+.2f}%）")
    return "\n".join(lines)


# ── Forecast memory ───────────────────────────────────────

def load_recent_forecasts(today: str, days: int = 7, history_dir: Path = HISTORY_DIR) -> list[dict]:
    out = []
    for path in sorted(history_dir.glob("*.json"), reverse=True):
        if path.stem >= today:
            continue
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        pf = d.get("price_forecast") or {}
        entry = {"date": d.get("date", path.stem), "items": {}}
        for key, _, _ in FORECAST_ITEMS:
            f = (pf.get("items") or {}).get(key)
            if f:
                entry["items"][key] = {
                    "week": (f.get("week") or {}).get("direction"),
                    "week_est": (f.get("week") or {}).get("change_estimate"),
                    "next_month": (f.get("next_month") or {}).get("direction"),
                }
            elif (d.get("tomorrow_forecast") or {}).get(key):
                old = d["tomorrow_forecast"][key]
                entry["items"][key] = {"week": old.get("direction"), "week_est": old.get("change_estimate"), "next_month": None}
        if entry["items"]:
            out.append(entry)
        if len(out) >= days:
            break
    return out


def memory_for_prompt(memory: list[dict]) -> str:
    if not memory:
        return "【你最近的預測】無紀錄。"
    names = {k: n for k, n, _ in FORECAST_ITEMS}
    lines = ["【你最近 7 天的預測（新到舊）】"]
    for e in memory:
        parts = [f"{names[k]} 週:{v['week'] or '-'}({v['week_est'] or '-'}) 月:{v['next_month'] or '-'}"
                 for k, v in e["items"].items()]
        lines.append(f"  {e['date']}：" + "；".join(parts))
    return "\n".join(lines)


# ── Prompt ────────────────────────────────────────────────

def fmt_num(v) -> str:
    if v is None:
        return "-"
    return f"{v:,.2f}".rstrip("0").rstrip(".") if abs(v) < 1000 else f"{v:,.0f}"


def materials_for_prompt(materials: dict) -> str:
    groups = {g["id"]: g["name"] for g in materials.get("groups", [])}
    trend_groups = {"tw_steel", "intl_steel", "production", "commodities"}
    lines, current = [], None
    for it in materials.get("items", []):
        if it["group"] != current:
            current = it["group"]
            lines.append(f"\n《{groups.get(current, current)}》")
        chg = f"，較前期 {it['change_pct']:+.2f}%" if it.get("change_pct") is not None else ""
        stale = "〔來源暫時無法連線，沿用前次資料〕" if it.get("stale") else ""
        region = f"（{it['region']}）" if it.get("region") and it["region"] not in it["name"] else ""
        line = f"  {it['name']}{region}：{fmt_num(it['value'])} {it['unit']}（{it['period']}{chg}，{it['freq']}更新）{stale}"
        if it["group"] in trend_groups and len(it.get("history", [])) >= 3:
            tail = " → ".join(fmt_num(v) for _, v in it["history"][-6:])
            line += f"\n      近期走勢：{tail}"
        lines.append(line)
    return "\n".join(lines).strip()


def headline_prices_for_prompt(tp: dict) -> str:
    lines = ["【台灣鋼材官方月均價（台灣金屬行情網）— 注意每項的資料月份不同】"]
    for key, name in HEADLINE_NAMES.items():
        it = tp.get(key) or {}
        if it.get("value") is None:
            lines.append(f"  {name}：資料待取得")
            continue
        mom = it.get("mom_change")
        mom_s = f"，月變動 {mom:+,.2f}".rstrip("0").rstrip(".") if mom is not None else ""
        lines.append(f"  {name}：{fmt_num(it['value'])} {it['unit']}（資料月份 {it['month']}{mom_s}）")
    return "\n".join(lines)


STORY_ANCHORS = (
    ["prices", "materials", "chart", "forecast", "analysis", "news"]
    + [f"fc-{k}" for k, _, _ in FORECAST_ITEMS]
)
TOP_STORIES_MIN, TOP_STORIES_MAX = 3, 5


def news_pool(feed: list[dict], headlines: list[dict]) -> list[dict]:
    """Every headline the model may cite, with a stable id (N1, N2, ...)."""
    pool = []
    for n in feed[:60]:
        pool.append({"title": n["title"], "url": n.get("url", ""), "source": n.get("source", ""), "date": n.get("date", "")})
    for h in headlines:
        pool.append({"title": h["title"], "url": h.get("url", ""), "source": h.get("source") or "SNN 環宇鋼鐵網", "date": h.get("date", "")})
    for i, n in enumerate(pool, 1):
        n["id"] = f"N{i}"
    return pool


def news_for_prompt(feed: list[dict], headlines: list[dict]) -> str:
    lines = ["【近 14 天公開新聞標題（Google 新聞與 SNN 環宇鋼鐵網；SNN 內文為會員限定，只有標題）】",
             "  格式：編號｜日期｜媒體｜標題"]
    for n in news_pool(feed, headlines):
        lines.append(f"  {n['id']}｜{n['date'] or '-'}｜{n['source'] or '-'}｜{n['title']}")
    return "\n".join(lines)


def finalize_top_stories(raw, pool: list[dict]) -> list[dict]:
    """
    Turn the model's story picks into 3-5 verified entries. Attention is the number
    of distinct outlets among the cited headlines, counted here from the real feed,
    so the model cannot inflate it; links always come from the cited headlines.
    """
    by_id = {n["id"]: n for n in pool}
    stories = []
    for order, st in enumerate(raw if isinstance(raw, list) else []):
        if not isinstance(st, dict):
            continue
        items = [by_id[i] for i in dict.fromkeys(str(x).strip() for x in st.get("ids") or []) if i in by_id]
        head = str(st.get("headline") or "").strip()
        if not items or not head:
            continue
        sources = list(dict.fromkeys(n["source"] for n in items if n["source"]))
        link = next((n for n in items if str(n["url"]).startswith("http")), None)
        anchor = st.get("anchor") if st.get("anchor") in STORY_ANCHORS else "news"
        stories.append({
            "headline": head[:40],
            "subheadline": str(st.get("subheadline") or "").strip()[:60],
            "url": link["url"] if link else "",
            "source": link["source"] if link else (sources[0] if sources else ""),
            "date": max((n["date"] for n in items if n["date"]), default=""),
            "coverage": len(sources) or 1,
            "anchor": anchor,
            "search": str(st.get("search") or "").strip()[:20] if anchor == "materials" else "",
            "articles": [{k: n[k] for k in ("title", "url", "source", "date")}
                         for n in items if str(n["url"]).startswith("http")][:6],
            "_order": order,
        })
    stories.sort(key=lambda x: (-x["coverage"], x["_order"]))
    stories = stories[:TOP_STORIES_MAX]
    if len(stories) < TOP_STORIES_MIN:
        used = {x["url"] for x in stories}
        for n in pool:
            if len(stories) >= TOP_STORIES_MIN:
                break
            if str(n["url"]).startswith("http") and n["url"] not in used:
                used.add(n["url"])
                stories.append({"headline": n["title"][:40], "subheadline": " · ".join(x for x in (n["source"], n["date"]) if x),
                                 "url": n["url"], "source": n["source"], "date": n["date"], "coverage": 1,
                                 "anchor": "news", "search": "",
                                 "articles": [{k: n[k] for k in ("title", "url", "source", "date")}], "_order": 99})
    for x in stories:
        x.pop("_order", None)
    return stories


# ── Historical base rates ─────────────────────────────────

def base_rates(materials: dict, targets: dict) -> dict:
    """How each series has moved month to month, so forecasts start from history, not one headline."""
    by_id = {it["id"]: it for it in materials.get("items", [])}
    out = {}
    for key, name, unit in FORECAST_ITEMS:
        hist = [(p, v) for p, v in (by_id.get(key) or {}).get("history", []) if isinstance(v, (int, float))]
        if len(hist) < 6:
            continue
        changes = [(hist[i][0], (hist[i][1] - hist[i - 1][1]) / hist[i - 1][1] * 100)
                   for i in range(1, len(hist)) if hist[i - 1][1]]
        dirs = [direction_of(c) for _, c in changes]
        moves = sorted(abs(c) for _, c in changes if abs(c) > STABLE_BAND_PCT)
        target_mm = (targets.get(key) or {}).get("target_month", "")[5:]
        out[key] = {
            "name": name, "unit": unit, "months": len(changes),
            "up": dirs.count("up"), "down": dirs.count("down"), "stable": dirs.count("stable"),
            "median_move_pct": round(moves[len(moves) // 2], 2) if moves else 0.0,
            "recent": [(p, round(c, 2)) for p, c in changes[-3:]],
            "same_month": [(p, round(c, 2)) for p, c in changes if target_mm and p[5:] == target_mm],
        }
    return out


def base_rates_for_prompt(rates: dict) -> str:
    if not rates:
        return "【歷史基準率】資料不足。"
    lines = [f"【歷史基準率：官方月均價過去的月變動（月變動在 ±{STABLE_BAND_PCT}% 內算持平）】"]
    for r in rates.values():
        recent = "、".join(f"{p} {c:+.2f}%" for p, c in r["recent"])
        same = "、".join(f"{p} {c:+.2f}%" for p, c in r["same_month"]) or "無"
        lines.append(
            f"  {r['name']}：近 {r['months']} 個月中 上漲 {r['up']} 次、下跌 {r['down']} 次、持平 {r['stable']} 次；"
            f"有變動時的幅度中位數 {r['median_move_pct']}%；最近三個月 {recent}；歷年同月份 {same}")
    return "\n".join(lines)


# ── Reasoning-chain validation ────────────────────────────
# Candidate cause -> effect links between monthly series. Each is tested on the
# stored history so the model only leans on links that actually held.
CHAIN_CANDIDATES = [
    ("north_scrap_price", "fengxing_rebar_price"),
    ("north_scrap_price", "billet_price"),
    ("billet_price", "fengxing_rebar_price"),
    ("billet_price", "h_beam_price"),
    ("billet_price", "csc_wire_rod_price"),
    ("wb_iron_ore", "billet_price"),
    ("wb_iron_ore", "csc_wire_rod_price"),
    ("wb_coal_au", "billet_price"),
    ("wb_brent", "north_scrap_price"),
    ("cci_tw_04", "fengxing_rebar_price"),
]
CHAIN_MIN_POINTS = 12


def _monthly_changes(item: dict) -> dict[str, float]:
    pts = [(p, v) for p, v in item.get("history", []) if len(p) == 7 and isinstance(v, (int, float))]
    return {pts[i][0]: (pts[i][1] - pts[i - 1][1]) / pts[i - 1][1] * 100
            for i in range(1, len(pts)) if pts[i - 1][1]}


def _shift_month(month: str, back: int) -> str:
    y, m = map(int, month.split("-"))
    m -= back
    while m < 1:
        m, y = m + 12, y - 1
    return f"{y}-{m:02d}"


def _corr(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (vx * vy) ** 0.5 if vx and vy else 0.0


def chain_links(materials: dict) -> list[dict]:
    """For each candidate link, the lag (0 or 1 month) with the strongest co-movement."""
    by_id = {it["id"]: it for it in materials.get("items", []) if not it.get("stale")}
    links = []
    for cause, effect in CHAIN_CANDIDATES:
        if cause not in by_id or effect not in by_id:
            continue
        ca, ce = _monthly_changes(by_id[cause]), _monthly_changes(by_id[effect])
        best = None
        for lag in (0, 1):
            pairs = [(ca[_shift_month(m, lag)], ce[m]) for m in ce if _shift_month(m, lag) in ca]
            if len(pairs) < CHAIN_MIN_POINTS:
                continue
            r = _corr([a for a, _ in pairs], [b for _, b in pairs])
            moved = [(a, b) for a, b in pairs if abs(a) > STABLE_BAND_PCT]
            effect_moved = sum(abs(b) > STABLE_BAND_PCT for _, b in moved)
            same = sum((a > 0) == (b > 0) for a, b in moved if abs(b) > STABLE_BAND_PCT)
            cand = {"cause": cause, "effect": effect, "cause_name": by_id[cause]["name"],
                    "effect_name": by_id[effect]["name"], "lag": lag, "r": round(r, 2), "n": len(pairs),
                    "cause_moves": len(moved), "effect_followed": effect_moved, "same_dir": same}
            if best is None or abs(cand["r"]) > abs(best["r"]):
                best = cand
        if best:
            r = best["r"]
            best["strength"] = "強" if r >= 0.6 else "中等" if r >= 0.35 else "弱或不成立"
            links.append(best)
    links.sort(key=lambda x: -x["r"])
    return links


def links_for_prompt(links: list[dict]) -> str:
    if not links:
        return "歷史資料不足，無法驗證推理鏈。"
    lines = [f"以下由過去約 36 個月的官方月資料計算（月變動在 ±{STABLE_BAND_PCT}% 內視為沒動）。"
             "「同月」表示兩者在同一個月一起變動，「晚一個月」表示前者先動、後者下個月才跟。"]
    for x in links:
        when = "同月" if x["lag"] == 0 else "晚一個月"
        follow = (f"前者有變動的 {x['cause_moves']} 個月裡，後者跟著變動 {x['effect_followed']} 次，其中同方向 {x['same_dir']} 次"
                  if x["cause_moves"] else "前者幾乎沒變動")
        lines.append(f"- {x['cause_name']} → {x['effect_name']}：{when}連動，相關係數 {x['r']:+.2f}（{x['strength']}）；{follow}。")
    return "\n".join(lines)


_MD_CITE = re.compile(r"\(\s*\[[^\]]*\]\([^)]*\)\s*\)")
_MD_LINK = re.compile(r"\[([^\]]*)\]\((?:https?:)?[^)]*\)")
_BARE_URL = re.compile(r"https?://\S+")
# Leftover of a link cut off mid-URL, e.g. "([site](" once the URL itself is gone.
_LINK_STUB = re.compile(r"\(?\s*\[[^\]]*\]\(\s*\)?\s*\)?")


def plain_text(s) -> str:
    """Drop citation markup and URLs from model prose; links live in the sources lists."""
    s = _MD_CITE.sub("", str(s or ""))
    s = _MD_LINK.sub(r"\1", s)
    s = _BARE_URL.sub("", s)
    s = _LINK_STUB.sub("", s)
    return re.sub(r"[ \t]{2,}", " ", s).strip()


def clean_prose(obj, skip=("url", "sources", "web_citations", "news_sources", "articles", "source_url")):
    """Recursively apply plain_text to every string in model output, except link fields."""
    if isinstance(obj, dict):
        return {k: (v if k in skip else clean_prose(v, skip)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [clean_prose(v, skip) for v in obj]
    return plain_text(obj) if isinstance(obj, str) else obj


def _domain(url: str) -> str:
    m = re.match(r"https?://([^/]+)", url or "")
    host = (m.group(1) if m else "").lower()
    return host[4:] if host.startswith("www.") else host


def finalize_dossier(raw: dict | None) -> dict | None:
    """Keep only facts backed by real URLs and count independent sources ourselves (distinct domains)."""
    if not isinstance(raw, dict):
        return None
    facts = []
    for f in raw.get("facts") or []:
        if not isinstance(f, dict) or not str(f.get("fact") or "").strip():
            continue
        srcs = [{"title": str(x.get("title") or x.get("url"))[:120], "url": x["url"]}
                for x in (f.get("sources") or []) if isinstance(x, dict) and str(x.get("url", "")).startswith("http")]
        if not srcs:
            continue
        facts.append({
            "id": str(f.get("id") or f"F{len(facts) + 1}"),
            "fact": plain_text(f["fact"])[:200],
            "date": str(f.get("date") or "")[:10],
            "type": f.get("type") if f.get("type") in ("公告", "成交", "報價", "預估", "傳聞") else "報價",
            "materials": [m for m in (f.get("materials") or []) if isinstance(m, str)][:6],
            "sources": srcs[:5],
            "source_count": len({_domain(x["url"]) for x in srcs}),
        })
    if len(facts) < 3:
        return None
    ids = {f["id"] for f in facts}
    drivers = {}
    for key, _, _ in FORECAST_ITEMS:
        rows = []
        for d in ((raw.get("drivers") or {}).get(key) or []):
            if not isinstance(d, dict) or not d.get("factor"):
                continue
            rows.append({
                "dimension": d.get("dimension") if d.get("dimension") in prompts.DIMENSIONS else "市場情緒",
                "factor": str(d["factor"])[:120],
                "direction": d.get("direction") if d.get("direction") in ("up", "down", "neutral") else "neutral",
                "strength": d.get("strength") if d.get("strength") in (1, 2, 3) else 1,
                "horizon": d.get("horizon") if d.get("horizon") in ("week", "month") else "month",
                "facts": [x for x in (d.get("facts") or []) if x in ids],
            })
        drivers[key] = rows
    conflicts = [{k: str(c.get(k) or "")[:200] for k in ("topic", "versions", "judgment")}
                 for c in (raw.get("conflicts") or []) if isinstance(c, dict) and c.get("topic")]
    gaps = [str(g)[:120] for g in (raw.get("gaps") or []) if str(g).strip()][:10]
    chains = [{"chain": str(c.get("chain"))[:80],
               "status": c.get("status") if c.get("status") in ("正在發生", "沒有發生", "尚待觀察") else "尚待觀察",
               "facts": [x for x in (c.get("facts") or []) if x in ids], "note": str(c.get("note") or "")[:150]}
              for c in (raw.get("chains") or []) if isinstance(c, dict) and c.get("chain")][:10]
    return {"facts": facts, "drivers": drivers, "conflicts": conflicts[:8], "chains": chains, "gaps": gaps}


def dossier_for_prompt(d: dict) -> str:
    names = {k: n for k, n, _ in FORECAST_ITEMS}
    arrow = {"up": "偏漲", "down": "偏跌", "neutral": "中性"}
    out = ["<facts>"]
    for f in d["facts"]:
        out.append(f'<fact id="{f["id"]}" date="{f["date"] or "不明"}" type="{f["type"]}" independent_sources="{f["source_count"]}">{f["fact"]}</fact>')
    out.append("</facts>\n<chains>")
    for c in d.get("chains", []):
        out.append(f'<chain status="{c["status"]}" facts="{",".join(c["facts"])}">{c["chain"]}：{c["note"]}</chain>')
    out.append("</chains>\n<drivers>")
    for key, rows in d["drivers"].items():
        for r in rows:
            out.append(f'<driver material="{names[key]}" dimension="{r["dimension"]}" direction="{arrow[r["direction"]]}" '
                       f'strength="{r["strength"]}" horizon="{"本週" if r["horizon"] == "week" else "下個月"}" facts="{",".join(r["facts"])}">{r["factor"]}</driver>')
    out.append("</drivers>\n<conflicts>")
    for c in d["conflicts"]:
        out.append(f"<conflict topic=\"{c['topic']}\">各家說法：{c['versions']}｜判斷：{c['judgment']}</conflict>")
    out.append("</conflicts>\n<gaps>")
    out.extend(f"<gap>{g}</gap>" for g in d["gaps"])
    out.append("</gaps>")
    return "\n".join(out)


def build_research_prompt(date_str, week_label, week_range, tp, fx_text, materials, news_text, rates_text, links_text):
    knowledge_path = Path(__file__).resolve().parents[1] / 'data/engineering-knowledge/index.json'
    try:
        knowledge = json.loads(knowledge_path.read_text(encoding='utf-8'))
        sources = '\n'.join(f"- {c['field']}｜{c['title']}｜{c['organization']}｜{c['url']}"
                            for c in knowledge['cards'] if c.get('daily_research'))
    except (OSError, ValueError, KeyError, TypeError):
        sources = ''
    return prompts.research_prompt(
        date_str=date_str, week_label=week_label, week_range=week_range,
        official_prices=headline_prices_for_prompt(tp), fx=fx_text, base_rates=rates_text,
        links=links_text, materials=materials_for_prompt(materials), news=news_text,
        professional_sources=sources)


def build_prompt(date_str: str, week_label: str, week_range: str, targets: dict, tp: dict,
                 fx_text: str, materials: dict, news_text: str, memory_text: str,
                 accuracy_text: str, web_search: bool, rates_text: str = "",
                 links_text: str = "", dossier_text: str = "") -> str:
    target_lines = "\n".join(
        f"  {n}：最新公布 {targets[k]['baseline_month']} 月均價 {fmt_num(targets[k]['baseline_value'])} {u}，"
        f"下一期月均價 = {targets[k]['target_month']}"
        for k, n, u in FORECAST_ITEMS if k in targets
    )
    return prompts.forecast_prompt(
        date_str=date_str, week_label=week_label, week_range=week_range, targets=target_lines,
        official_prices=headline_prices_for_prompt(tp), fx=fx_text, base_rates=rates_text,
        links=links_text, dossier=dossier_text, materials=materials_for_prompt(materials),
        news=news_text, memory=memory_text, accuracy=accuracy_text,
        item_schema=prompts.item_schema(FORECAST_ITEMS, targets, week_label),
        mode="dossier" if dossier_text else ("web" if web_search else "offline"))


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


# ── Model calls ───────────────────────────────────────────

def extract_json(text: str) -> dict | None:
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M)
    start, end = text.find("{"), text.rfind("}") + 1
    if start < 0 or end <= start:
        log(f"  No JSON object in response: {text[:200]!r}")
        return None
    try:
        return json.loads(text[start:end])
    except json.JSONDecodeError as e:
        log(f"  JSON parse error: {e}; near {text[start:end][max(0, e.pos - 120):e.pos + 80]!r}")
        return None


def valid_forecast(parsed: dict | None) -> bool:
    items = ((parsed or {}).get("price_forecast") or {}).get("items") or {}
    good = sum(1 for k, _, _ in FORECAST_ITEMS
               if (items.get(k) or {}).get("week", {}).get("direction") in ("up", "down", "stable")
               and (items.get(k) or {}).get("next_month", {}).get("direction") in ("up", "down", "stable"))
    return good >= 4


def call_openai(prompt: str, model: str, web: bool, json_mode: bool = False,
                effort: str = REASONING_EFFORT) -> tuple[str, list[dict]]:
    body = {
        "model": model,
        "input": prompt,
        "reasoning": {"effort": effort},
        "max_output_tokens": MAX_OUTPUT_TOKENS,
    }
    # OpenAI rejects JSON mode together with web search, so it is only used for repairs.
    if json_mode:
        body["text"] = {"format": {"type": "json_object"}}
    if web:
        body["tools"] = [{"type": "web_search"}]
    r = requests.post(OPENAI_URL, headers={"Authorization": f"Bearer {OPENAI_API_KEY}"}, json=body, timeout=600)
    if not r.ok:
        raise RuntimeError(f"OpenAI HTTP {r.status_code}: {r.text[:300]}")
    j = r.json()
    if j.get("status") not in (None, "completed"):
        log(f"  OpenAI response status={j.get('status')} details={j.get('incomplete_details')}")
    texts, cites = [], []
    for item in j.get("output", []):
        if item.get("type") != "message":
            continue
        for c in item.get("content", []):
            if c.get("type") == "output_text":
                texts.append(c.get("text", ""))
                for a in c.get("annotations", []) or []:
                    if a.get("type") == "url_citation" and a.get("url"):
                        cites.append({"title": a.get("title") or a["url"], "url": a["url"]})
    usage = j.get("usage") or {}
    log(f"  OpenAI usage: in={usage.get('input_tokens')} out={usage.get('output_tokens')}")
    return "".join(texts) or j.get("output_text", ""), cites


def call_openrouter(prompt: str, model: str, web: bool, json_mode: bool = False) -> tuple[str, list[dict]]:
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": MAX_OUTPUT_TOKENS,
        "reasoning": {"effort": REASONING_EFFORT},
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    if web:
        body["plugins"] = [{"id": "web", "max_results": 8}]
    r = requests.post(OPENROUTER_URL, json=body, timeout=600, headers={
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "HTTP-Referer": "https://lijingchiu.github.io/SteelWeb",
        "X-Title": "Taiwan Steel Price Analysis",
    })
    if not r.ok:
        raise RuntimeError(f"OpenRouter HTTP {r.status_code}: {r.text[:300]}")
    msg = r.json()["choices"][0]["message"]
    cites = []
    for a in msg.get("annotations", []) or []:
        uc = a.get("url_citation") or {}
        if uc.get("url"):
            cites.append({"title": uc.get("title") or uc["url"], "url": uc["url"]})
    return msg.get("content") or "", cites


def repair_json(text: str, model: str) -> dict | None:
    """Fix malformed JSON with a cheap JSON-mode call instead of redoing the web research."""
    log("  Repairing malformed JSON (JSON mode, no web search)")
    try:
        fixed, _ = call_openai(
            "下面這段文字應該是一個 JSON 物件，但格式有錯。請只修正 JSON 語法（例如引號、逗號、括號、跳脫字元），"
            "保留所有欄位與文字內容原樣，輸出修正後的 JSON：\n\n" + text,
            model, web=False, json_mode=True, effort="low")
        return extract_json(fixed)
    except Exception as e:
        log(f"  JSON repair failed: {e}")
        return None


def run_stage(name: str, build: callable, accept: callable, web: bool | None,
              json_mode: bool = False) -> tuple[dict | None, list[dict], str | None]:
    """
    Try each provider in MODEL_CHAIN until one returns a response that accept() approves.
    build(web) -> prompt. web=None uses each provider's own web setting; True/False forces it
    (forced True skips providers without web search).
    """
    for provider, model, can_web in MODEL_CHAIN:
        key = OPENAI_API_KEY if provider == "openai" else OPENROUTER_API_KEY
        if not key:
            continue
        use_web = can_web if web is None else web
        if use_web and not can_web:
            continue
        # JSON mode cannot be combined with web search.
        jm = json_mode and not use_web
        prompt = build(use_web)
        for attempt in range(2):
            try:
                log(f"[{name}] {provider}:{model} web={use_web} json={jm} (attempt {attempt + 1}/2, prompt {len(prompt)} chars)")
                t0 = time.time()
                if provider == "openai":
                    text, cites = call_openai(prompt, model, use_web, json_mode=jm)
                else:
                    text, cites = call_openrouter(prompt, model, use_web, json_mode=jm)
                parsed = extract_json(text)
                log(f"[{name}]   {len(text)} chars, {len(cites)} citations in {time.time() - t0:.0f}s")
                if parsed is None and text.strip() and OPENAI_API_KEY:
                    parsed = repair_json(text, OPENAI_MODEL)
                if accept(parsed):
                    return parsed, cites, f"{model}（{'OpenAI API' if provider == 'openai' else 'OpenRouter'}）"
                log(f"[{name}]   response rejected by validation; retrying")
            except Exception as e:
                log(f"[{name}]   {provider}:{model} error: {e}")
            time.sleep(10)
    return None, [], None


def run_analysis(build: callable) -> tuple[dict | None, list[dict], str | None]:
    """Single-stage fallback: the forecast prompt with each provider's own web setting."""
    return run_stage("forecast", build, valid_forecast, web=None)


# ── Forecast ensemble ─────────────────────────────────────
ENSEMBLE_RUNS = 3
DIRS = ("up", "stable", "down")


def scenario_probs(f: dict) -> dict | None:
    sc = ((f or {}).get("next_month") or {}).get("scenarios") or {}
    try:
        vals = {d: max(0.0, float((sc.get(d) or {}).get("prob"))) for d in DIRS}
    except (TypeError, ValueError):
        return None
    total = sum(vals.values())
    return {d: v / total * 100 for d, v in vals.items()} if total > 0 else None


def round_to_100(p: dict) -> dict:
    floors = {d: int(p[d]) for d in DIRS}
    rest = 100 - sum(floors.values())
    for d in sorted(DIRS, key=lambda d: p[d] - floors[d], reverse=True)[:rest]:
        floors[d] += 1
    return floors


def aggregate_forecasts(samples: list[dict]) -> dict:
    """
    Combine independent forecast runs: per material, the median probability of each
    outcome (renormalised) decides the next-month direction, a majority vote decides
    the week direction, and the wording comes from the run closest to that consensus.
    """
    if len(samples) == 1:
        return samples[0]

    def items_of(x):
        return (x.get("price_forecast") or {}).get("items") or {}

    merged_items, agree_score = {}, [0] * len(samples)
    for key, _, _ in FORECAST_ITEMS:
        cands = [(i, items_of(x).get(key)) for i, x in enumerate(samples) if items_of(x).get(key)]
        if not cands:
            continue
        probs = [(i, scenario_probs(f)) for i, f in cands]
        probs = [(i, p) for i, p in probs if p]
        if probs:
            med = {d: sorted(p[d] for _, p in probs)[len(probs) // 2] if len(probs) % 2 else
                   sum(sorted(p[d] for _, p in probs)[len(probs) // 2 - 1:len(probs) // 2 + 1]) / 2 for d in DIRS}
            total = sum(med.values()) or 1
            consensus = round_to_100({d: v / total * 100 for d, v in med.items()})
            month_dir = max(DIRS, key=lambda d: consensus[d])
            pool = [(i, p) for i, p in probs if items_of(samples[i])[key]["next_month"].get("direction") == month_dir] or probs
            pick = min(pool, key=lambda ip: sum(abs(ip[1][d] - consensus[d]) for d in DIRS))[0]
        else:
            consensus, pick = None, cands[0][0]
            month_dir = items_of(samples[pick])[key]["next_month"].get("direction")
        votes = [f["week"].get("direction") for _, f in cands if f.get("week")]
        week_dir = max(set(votes), key=votes.count) if votes else None
        chosen = json.loads(json.dumps(items_of(samples[pick])[key]))
        if chosen.get("week", {}).get("direction") != week_dir:
            alt = next((f for _, f in cands if f.get("week", {}).get("direction") == week_dir), None)
            if alt:
                chosen["week"] = alt["week"]
        if consensus:
            sc = chosen["next_month"].setdefault("scenarios", {})
            for d in DIRS:
                sc.setdefault(d, {})["prob"] = consensus[d]
            chosen["next_month"]["direction"] = month_dir
        chosen["ensemble"] = {
            "runs": len(cands),
            "month_agree": sum(1 for _, f in cands if f["next_month"].get("direction") == month_dir),
            "week_agree": votes.count(week_dir) if week_dir else 0,
        }
        merged_items[key] = chosen
        for i, f in cands:
            agree_score[i] += (f["next_month"].get("direction") == month_dir) + (f.get("week", {}).get("direction") == week_dir)

    base = json.loads(json.dumps(samples[max(range(len(samples)), key=lambda i: agree_score[i])]))
    base.setdefault("price_forecast", {})["items"] = merged_items
    sources = []
    for x in samples:
        sources.extend(x.get("sources") or [])
    base["sources"] = sources
    return base


def run_forecast_ensemble(build: callable, runs: int = ENSEMBLE_RUNS):
    """Run the no-tools forecast stage several times in parallel and aggregate."""
    with ThreadPoolExecutor(max_workers=runs) as pool:
        futures = [pool.submit(run_stage, f"forecast#{i + 1}", build, valid_forecast, False, True) for i in range(runs)]
        results = [f.result() for f in futures]
    ok = [(a, c, l) for a, c, l in results if a]
    log(f"Forecast ensemble: {len(ok)}/{runs} runs succeeded")
    if not ok:
        return None, [], None
    cites = [c for _, cs, _ in ok for c in cs]
    label = ok[0][2]
    return aggregate_forecasts([a for a, _, _ in ok]), cites, label


# ── Main ──────────────────────────────────────────────────

def dedupe_citations(cites: list[dict]) -> list[dict]:
    seen, out = set(), []
    for c in cites:
        u = c["url"].split("#")[0]
        if u not in seen:
            seen.add(u)
            out.append({"title": c["title"][:120], "url": c["url"]})
    return out[:40]


def main():
    now = datetime.now(TW_TZ)
    date_str = now.strftime("%Y-%m-%d")
    log(f"=== Steel & Materials Analysis: {date_str} ===")

    exchange_rate = fetch_exchange_rate()
    materials = build_materials(exchange_rate)
    write_outputs(materials)
    taiwan_prices = taiwan_prices_from_materials(materials)

    accuracy = score_accuracy(materials)
    ACCURACY_PATH.write_text(json.dumps(accuracy, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"Accuracy: {accuracy['overall']['hits']}/{accuracy['overall']['total']} scored, {accuracy['pending']} pending")

    headlines = scrape_steelnews_headlines()
    feed = materials.get("news_feed", [])
    week_label, week_range = forecast_week(now)
    targets = forecast_targets(materials)

    fx_text = format_exchange_rate_for_prompt(exchange_rate)
    news_text = news_for_prompt(feed, headlines)
    rates_text = base_rates_for_prompt(base_rates(materials, targets))
    links = chain_links(materials)
    links_text = links_for_prompt(links)
    memory_text = memory_for_prompt(load_recent_forecasts(date_str))
    accuracy_text = accuracy_for_prompt(accuracy)

    # Stage 1: researcher with web search builds a verified dossier.
    raw_dossier, research_cites, _ = run_stage(
        "research",
        lambda web: build_research_prompt(date_str, week_label, week_range, taiwan_prices, fx_text,
                                          materials, news_text, rates_text, links_text),
        lambda parsed: finalize_dossier(parsed) is not None, web=True)
    dossier = finalize_dossier(raw_dossier)
    if dossier:
        log(f"Dossier: {len(dossier['facts'])} facts "
            f"({sum(f['source_count'] >= 2 for f in dossier['facts'])} cross-checked), "
            f"{len(dossier['conflicts'])} conflicts, {len(dossier['chains'])} chains, {len(dossier['gaps'])} gaps")
        for f in dossier["facts"]:
            research_cites.extend(f["sources"])

    def build(web: bool) -> str:
        return build_prompt(date_str, week_label, week_range, targets, taiwan_prices, fx_text, materials,
                            news_text, memory_text, accuracy_text, web, rates_text, links_text,
                            dossier_for_prompt(dossier) if dossier else "")

    # Stage 2: independent forecast runs without tools, aggregated; single-stage fallback otherwise.
    if dossier:
        analysis, citations, model_label = run_forecast_ensemble(build)
    else:
        analysis, citations, model_label = None, [], None
    if not analysis:
        log("Falling back to single-stage analysis with web search")
        analysis, citations, model_label = run_analysis(build)
    if analysis:
        analysis = clean_prose(analysis)
    citations = research_cites + citations
    if analysis:
        listed = [c for c in (analysis.pop("sources", None) or []) if isinstance(c, dict)
                  and str(c.get("url", "")).startswith("http")]
        citations = citations + [{"title": str(c.get("title") or c["url"]), "url": c["url"]} for c in listed]
        if dossier:
            fact_ids = {f["id"] for f in dossier["facts"]}
            for item in (analysis.get("price_forecast") or {}).get("items", {}).values():
                item["evidence"] = [x for x in (item.get("evidence") or []) if x in fact_ids]
            analysis["research"] = {**dossier, "links": links}
        else:
            analysis["research"] = {"facts": [], "drivers": {}, "conflicts": [], "chains": [], "gaps": [], "links": links}
    if not analysis:
        log("FATAL: no model returned a valid analysis; material data was still saved")
        sys.exit(1)

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

    pf = analysis.setdefault("price_forecast", {})
    pf["week_label"], pf["week_range"], pf["targets"] = week_label, week_range, targets

    analysis["top_stories"] = finalize_top_stories(analysis.get("top_stories"), news_pool(feed, headlines))
    log(f"Top stories: {[(x['coverage'], x['headline']) for x in analysis['top_stories']]}")

    news_sources = [{k: n.get(k, "") for k in ("title", "url", "source", "date")} for n in feed[:24]]
    news_sources += headlines[:12]
    output = {
        "generated_at": now.isoformat(),
        "date": date_str,
        "model_used": model_label,
        "news_count": len(news_sources),
        "news_sources": news_sources,
        "web_citations": dedupe_citations(citations),
        "taiwan_prices": taiwan_prices,
        **analysis,
    }
    output['suggested_questions'] = make_suggestions(output)

    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    Path("data/latest.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    (HISTORY_DIR / f"{date_str}.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    log("Saved data/latest.json and history")

    idx_path = Path("data/history-index.json")
    try:
        index = json.loads(idx_path.read_text())
    except Exception:
        index = []
    index = sorted(set(index) | {date_str}, reverse=True)[:90]
    idx_path.write_text(json.dumps(index, ensure_ascii=False))

    log(f"=== Analysis complete ({model_label}) ===")


if __name__ == "__main__":
    main()
