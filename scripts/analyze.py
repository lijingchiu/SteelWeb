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


def news_for_prompt(feed: list[dict], headlines: list[dict]) -> str:
    lines = ["【近 14 天公開新聞標題（Google 新聞）】"]
    for n in feed[:60]:
        lines.append(f"  {n.get('date', '')}｜{n.get('source', '')}｜{n['title']}")
    if headlines:
        lines.append("\n【SNN 環宇鋼鐵網 最新標題（內文為會員限定，只有標題）】")
        lines.extend(f"  {h['title']}" for h in headlines)
    return "\n".join(lines)


def build_prompt(date_str: str, week_label: str, week_range: str, targets: dict, tp: dict,
                 fx_text: str, materials: dict, news_text: str, memory_text: str,
                 accuracy_text: str, web_search: bool) -> str:
    target_lines = "\n".join(
        f"  {n}：最新公布 {targets[k]['baseline_month']} 月均價 {fmt_num(targets[k]['baseline_value'])} {u}，"
        f"「下一期月均價」= {targets[k]['target_month']}"
        for k, n, u in FORECAST_ITEMS if k in targets
    )
    item_schema = ",\n".join(f'''      "{k}": {{
        "week": {{"direction": "<up|down|stable>", "change_estimate": "<{week_label}實質成交行情變動幅度，{u}>", "reason": "<100~200字>"}},
        "next_month": {{"direction": "<up|down|stable>", "change_estimate": "<{targets.get(k, {}).get('target_month', '下一期')} 月均價相對 {targets.get(k, {}).get('baseline_month', '最新一期')} 的變動，{u}>", "reason": "<100~200字>"}},
        "revision_note": "<若方向與你最近一次預測不同，說明是哪一則新資訊造成改變；方向未變則寫「維持前次判斷」並簡述理由>"
      }}''' for k, _, u in FORECAST_ITEMS)
    search_rule = (
        "你可以使用網路搜尋。請務必先搜尋並核對以下最新資訊再下判斷：豐興本週廢鋼與鋼筋盤價（金額）、"
        "中鋼最新月盤／季盤、東和鋼鐵本月型鋼價格、威致或海光等鋼廠調價、美國與土耳其廢鋼價格、"
        "中國螺紋鋼期貨與唐山鋼胚、鐵礦砂與焦煤價格。引用的數字必須來自你實際讀到的來源。"
        if web_search else
        "本次無法使用網路搜尋，只能依下方提供的資料與新聞標題判斷；無法確認的金額不要捏造。"
    )
    return f"""你是一位台灣鋼鐵與營建材料市場的資深分析師，像股票分析師分析個股一樣，對原物料行情做出有立場、可被驗證的判斷。
今天日期：{date_str}（台灣時間，{"週末" if week_label == "下週" else "平日"}）

{search_rule}

{headline_prices_for_prompt(tp)}

{fx_text}

【完整營建材料與原物料資料（每一項都標明資料期間與更新頻率）】
{materials_for_prompt(materials)}

{news_text}

{memory_text}

{accuracy_text}

═══════════════ 預測任務 ═══════════════
請對五項台灣鋼材各做兩個預測：
1. week：{week_label}（{week_range}）的實質市場成交行情，相對上週的方向與幅度。台灣鋼價多由豐興每週一開盤、中鋼與東和每月調價，所以要以「本週已公布或即將公布的盤價」與「市場實際成交」為核心依據。
2. next_month：「下一期官方月均價」相對最新已公布月均價的方向與幅度。這是可以被驗證的預測，系統會在官方數據公布後自動計分：
{target_lines}

規則：
- 每個 reason 100~200 字，依序寫出：(a) 具體的國際或上游訊號（引用事件、價格或數據）；(b) 這個訊號如何傳導到台灣廠商的成本、報價或買氣；(c) 結論與幅度依據，指出最關鍵的因素。
- 禁止空泛理由。"stable" 只能在多空力量確實抵銷時使用，並在 reason 中同時列出多方與空方因素。
- change_estimate 必須是具體數字區間。
- 不要被單一一則新聞標題左右。若方向與你最近一次預測不同，revision_note 必須說明是哪一則新資訊造成改變；沒有新資訊就不應該翻轉方向。
- 參考你過去的命中率與誤判，修正判斷方式。
- 注意各項資料的月份不同（例如粗鋼產量比鋼價晚兩個月），引用時必須寫出正確月份。
- 引用本提示提供的資料時，稱為「官方數據」或寫出來源名稱（例如台灣金屬行情網、主計總處），不要寫「題供」或「提示提供」。
- JSON 字串內不要使用 markdown 連結或引用標記；你實際查閱過的網頁請列在 sources。

請嚴格以 JSON 格式回覆，不要輸出任何其他文字：

{{
  "exchange_rate": {{
    "usd_twd_estimate": <浮點數>,
    "impact_on_steel": "<匯率影響說明，100字內>"
  }},
  "spread_analysis": "<利差試算：廢鋼→鋼胚→鋼筋→型鋼的加工利差，含匯率影響，200字內>",
  "monthly_trend": "<未來一個月台灣鋼市展望，200字內>",
  "international_outlook": "<國際鋼鐵與原物料大局觀，含中國、日本、韓國、美國、土耳其，300字內>",
  "materials_outlook": "<營建材料觀察：依營造工程物價指數與原物料數據，說明水泥、砂石、瀝青、木材、機電、工資等的走勢與對工程成本的影響，200字內>",
  "price_forecast": {{
    "items": {{
{item_schema}
    }},
    "overall_basis": "<綜合推論：參考了哪些時事與數據、多空力量對比與權重、推論順序，250字內>"
  }},
  "risk_factors": ["<風險因素1>", "<風險因素2>", "<風險因素3>"],
  "summary": "<今日市場總結，150字內>",
  "confidence": "<high|medium|low>",
  "sources": [{{"title": "<你實際查閱的網頁標題>", "url": "<網址>"}}]
}}"""


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
        return None
    try:
        return json.loads(text[start:end])
    except json.JSONDecodeError:
        return None


def valid_forecast(parsed: dict | None) -> bool:
    items = ((parsed or {}).get("price_forecast") or {}).get("items") or {}
    good = sum(1 for k, _, _ in FORECAST_ITEMS
               if (items.get(k) or {}).get("week", {}).get("direction") in ("up", "down", "stable")
               and (items.get(k) or {}).get("next_month", {}).get("direction") in ("up", "down", "stable"))
    return good >= 4


def call_openai(prompt: str, model: str, web: bool) -> tuple[str, list[dict]]:
    body = {
        "model": model,
        "input": prompt,
        "reasoning": {"effort": REASONING_EFFORT},
        "max_output_tokens": MAX_OUTPUT_TOKENS,
    }
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


def call_openrouter(prompt: str, model: str, web: bool) -> tuple[str, list[dict]]:
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": MAX_OUTPUT_TOKENS,
        "reasoning": {"effort": REASONING_EFFORT},
    }
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


def run_analysis(build: callable) -> tuple[dict | None, list[dict], str | None]:
    """build(web_search: bool) -> prompt. Returns (analysis, citations, model label)."""
    for provider, model, web in MODEL_CHAIN:
        key = OPENAI_API_KEY if provider == "openai" else OPENROUTER_API_KEY
        if not key:
            log(f"Skipping {provider}:{model} (no API key)")
            continue
        prompt = build(web)
        for attempt in range(2):
            try:
                log(f"Calling {provider}:{model} web={web} (attempt {attempt + 1}/2, prompt {len(prompt)} chars)")
                t0 = time.time()
                fn = call_openai if provider == "openai" else call_openrouter
                text, cites = fn(prompt, model, web)
                parsed = extract_json(text)
                log(f"  {len(text)} chars, {len(cites)} citations in {time.time() - t0:.0f}s")
                if valid_forecast(parsed):
                    label = f"{model}（{'OpenAI API' if provider == 'openai' else 'OpenRouter'}）"
                    return parsed, cites, label
                log("  Response missing a valid price_forecast; retrying")
            except Exception as e:
                log(f"  {provider}:{model} error: {e}")
            time.sleep(10)
    return None, [], None


# ── Main ──────────────────────────────────────────────────

def dedupe_citations(cites: list[dict]) -> list[dict]:
    seen, out = set(), []
    for c in cites:
        u = c["url"].split("#")[0]
        if u not in seen:
            seen.add(u)
            out.append({"title": c["title"][:120], "url": c["url"]})
    return out[:20]


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

    def build(web: bool) -> str:
        return build_prompt(
            date_str, week_label, week_range, targets, taiwan_prices,
            format_exchange_rate_for_prompt(exchange_rate), materials,
            news_for_prompt(feed, headlines),
            memory_for_prompt(load_recent_forecasts(date_str)),
            accuracy_for_prompt(accuracy), web,
        )

    analysis, citations, model_label = run_analysis(build)
    if analysis:
        listed = [c for c in (analysis.pop("sources", None) or []) if isinstance(c, dict)
                  and str(c.get("url", "")).startswith("http")]
        citations = citations + [{"title": str(c.get("title") or c["url"]), "url": c["url"]} for c in listed]
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
