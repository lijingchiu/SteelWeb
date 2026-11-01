#!/usr/bin/env python3
"""
Construction material price aggregator.

Fetches every price series the site shows from public, openly licensed
sources, one source at a time so a failing source never blocks the others.
When a source fails, its items from the previous run are carried over and
flagged stale. Writes data/materials.json and rebuilds data/chart-data.json.

Sources (all verified reachable from GitHub-hosted runners):
  - 台灣金屬行情網 chart.metaltrade.tw: Taiwan steel monthly prices and
    production, international steel quotes (weekly/daily).
  - 行政院主計總處 營造工程物價指數 (ws.dgbas.gov.tw XML).
  - 臺北市 / 新北市 / 臺中市 主計處 營造工程物價指數 (open data).
  - World Bank Commodity Price Data (Pink Sheet), monthly.
  - 臺灣證券交易所 OpenAPI, daily closing prices.
  - Google News RSS headlines for weekly mill price announcements.
"""
import ast
import base64
import io
import json
import re
import statistics
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

TW_TZ = timezone(timedelta(hours=8))
MATERIALS_PATH = Path("data/materials.json")
CHART_PATH = Path("data/chart-data.json")
HISTORY_POINTS = 36

UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
}

GROUPS = [
    {"id": "tw_steel",     "name": "臺灣鋼材盤價",       "desc": "台灣金屬行情網・月均價"},
    {"id": "intl_steel",   "name": "國際鋼材行情",       "desc": "台灣金屬行情網・國際報價（週／日更新）"},
    {"id": "production",   "name": "粗鋼產量",           "desc": "台灣金屬行情網・月資料"},
    {"id": "cci_national", "name": "全國營造工程物價指數", "desc": "行政院主計總處・民國110年=100"},
    {"id": "cci_local",    "name": "地方營造工程物價指數", "desc": "臺北市、新北市、臺中市主計處"},
    {"id": "commodities",  "name": "國際原物料",         "desc": "世界銀行 Pink Sheet・月均價"},
    {"id": "fx",           "name": "匯率",               "desc": "銀行牌告・每日"},
    {"id": "stocks",       "name": "鋼鐵與水泥類股",     "desc": "臺灣證券交易所・每日收盤價"},
]

# metaltrade series id -> (item id, group, region). Domestic 9-14 and
# international 1-8 were confirmed to carry page-data.
METALTRADE_SERIES = [
    ("ste/domestic/9/",       "crude_steel_production", "production", "臺灣"),
    ("ste/domestic/10/",      "north_scrap_price",      "tw_steel",   "臺灣北部"),
    ("ste/domestic/11/",      "billet_price",           "tw_steel",   "臺灣"),
    ("ste/domestic/12/",      "fengxing_rebar_price",   "tw_steel",   "臺灣"),
    ("ste/domestic/13/",      "h_beam_price",           "tw_steel",   "臺灣"),
    ("ste/domestic/14/",      "csc_wire_rod_price",     "tw_steel",   "臺灣"),
    ("ste/international/1/",  "mt_world_crude",         "production", "全球"),
    ("ste/international/2/",  "mt_china_crude",         "production", "中國大陸"),
    ("ste/international/3/",  "mt_cis_billet",          "intl_steel", "獨立國協黑海"),
    ("ste/international/4/",  "mt_cis_slab",            "intl_steel", "獨立國協黑海"),
    ("ste/international/5/",  "mt_vn_hrc_import",       "intl_steel", "越南"),
    ("ste/international/6/",  "mt_cis_hrc",             "intl_steel", "獨立國協黑海"),
    ("ste/international/7/",  "mt_seu_rebar",           "intl_steel", "南歐"),
    ("ste/international/8/",  "mt_tr_rebar",            "intl_steel", "土耳其"),
]
METALTRADE_BASE = "https://chart.metaltrade.tw/"

DGBAS_CCI_URL = "https://ws.dgbas.gov.tw/001/Upload/461/relfile/11525/230553/pr0501a1m.xml"
TAIPEI_CCI_URL = (
    "https://tsis.dbas.gov.taipei/statis/webMain.aspx?sys=220&ymf=9201&kind=21&type=0"
    "&funid=a04004101&cycle=1&outmode=12&compmode=0&outkind=1&deflst=2&nzo=1"
)
NTPC_CCI_URL = "https://data.ntpc.gov.tw/api/datasets/9d0483b6-513a-46b2-92e3-5f9b315999bb/csv/file"
TAICHUNG_DATASET_API = "https://data.gov.tw/api/v2/rest/dataset/167838"

WB_LANDING = "https://www.worldbank.org/en/research/commodity-markets"
WB_SOURCE_URL = WB_LANDING
WB_COMMODITIES = [
    # (header in Pink Sheet, item id, Chinese name)
    ("Iron ore, cfr spot",           "wb_iron_ore",   "鐵礦砂（CFR 現貨）"),
    ("Coal, Australian",             "wb_coal_au",    "澳洲動力煤"),
    ("Coal, South African",          "wb_coal_za",    "南非動力煤"),
    ("Copper",                       "wb_copper",     "銅"),
    ("Aluminum",                     "wb_aluminum",   "鋁"),
    ("Zinc",                         "wb_zinc",       "鋅"),
    ("Nickel",                       "wb_nickel",     "鎳"),
    ("Lead",                         "wb_lead",       "鉛"),
    ("Tin",                          "wb_tin",        "錫"),
    ("Crude oil, Brent",             "wb_brent",      "布蘭特原油"),
    ("Crude oil, WTI",               "wb_wti",        "WTI 原油"),
    ("Crude oil, Dubai",             "wb_dubai",      "杜拜原油"),
    ("Natural gas, US",              "wb_ng_us",      "美國天然氣"),
    ("Natural gas, Europe",          "wb_ng_eu",      "歐洲天然氣"),
    ("Liquefied natural gas, Japan", "wb_lng_jp",     "日本液化天然氣"),
    ("Logs, Malaysian",              "wb_logs_my",    "馬來西亞原木"),
    ("Sawnwood, Malaysian",          "wb_sawnwood_my", "馬來西亞製材"),
    ("Plywood",                      "wb_plywood",    "合板"),
]
WB_UNITS = {
    "($/mt)": "美元/公噸", "($/bbl)": "美元/桶", "($/mmbtu)": "美元/百萬英熱單位",
    "($/dmtu)": "美元/乾公噸度", "($/cubic meter)": "美元/立方公尺", "(cents/sheet)": "美分/張",
}

TWSE_URL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
TWSE_CODES = [
    "2002", "2006", "2007", "2014", "2015", "2023", "2027", "2031", "9958",
    "1101", "1102", "1103", "1104", "1108", "1109", "1110",
]

NEWS_QUERIES = [
    "豐興 鋼筋 盤價", "豐興 廢鋼", "中鋼 盤價", "東和鋼鐵 型鋼", "鋼筋 價格",
    "廢鋼 價格", "水泥 價格", "預拌混凝土 價格", "砂石 價格", "鐵礦砂 價格",
]
GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"
# Aggregator / PR outlets that surface generic global industry reports, not Taiwan market news.
NEWS_SOURCE_BLOCKLIST = {"IndexBox", "TradingKey", "Funliday", "Reccessary", "NAI500", "Yahoo - 汽機車"}
NEWS_TITLE_EXCLUDE = re.compile(r"市場展望20\d\d|市場規模|年複合成長率|CAGR")


def log(msg: str):
    print(f"[{datetime.now(TW_TZ).strftime('%H:%M:%S')}] {msg}", flush=True)


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(UA)
    return s


def _get(session: requests.Session, url: str, timeout: int = 40, tries: int = 2, **kw) -> requests.Response:
    last = None
    for i in range(tries):
        try:
            r = session.get(url, timeout=timeout, **kw)
            r.raise_for_status()
            return r
        except Exception as e:
            last = e
            if i + 1 < tries:
                time.sleep(3)
    raise last


# ── Generic helpers ────────────────────────────────────────

def roc_to_month(text: str) -> str | None:
    """'115年 9月' / '102年1月' -> '2026-09'."""
    m = re.search(r"(\d{2,3})\s*年\s*(\d{1,2})\s*月", text)
    if not m:
        return None
    return f"{int(m.group(1)) + 1911}-{int(m.group(2)):02d}"


def roc_date_to_iso(text: str) -> str | None:
    """'1151030' -> '2026-10-30'."""
    m = re.fullmatch(r"(\d{3})(\d{2})(\d{2})", text.strip())
    if not m:
        return None
    return f"{int(m.group(1)) + 1911}-{m.group(2)}-{m.group(3)}"


def to_float(v) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace(",", "").strip()
    if s in ("", "-", "…", "...", "—"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def infer_freq(periods: list[str]) -> str:
    """Infer 日/週/月 from the spacing of the most recent dated points."""
    dated = [p for p in periods if len(p) == 10][-12:]
    if len(dated) < 3:
        return "月"
    ds = [datetime.strptime(p, "%Y-%m-%d") for p in dated]
    gaps = [(b - a).days for a, b in zip(ds, ds[1:]) if (b - a).days > 0]
    if not gaps:
        return "月"
    g = statistics.median(gaps)
    if g <= 3:
        return "日"
    if g <= 10:
        return "週"
    return "月"


def make_item(*, id, name, group, unit, history, source, source_url,
              region="", freq=None, note="") -> dict | None:
    """Build an item from a chronologically sortable [(period, value)] list."""
    hist = sorted({p: v for p, v in history if v is not None}.items())
    if not hist:
        return None
    hist = hist[-HISTORY_POINTS:]
    period, value = hist[-1]
    prev_period, prev = (hist[-2] if len(hist) >= 2 else (None, None))
    change = round(value - prev, 6) if prev is not None else None
    change_pct = round(change / prev * 100, 3) if prev not in (None, 0) and change is not None else None
    return {
        "id": id, "name": name, "group": group, "region": region, "unit": unit,
        "value": value, "period": period, "prev": prev, "prev_period": prev_period,
        "change": change, "change_pct": change_pct,
        "freq": freq or infer_freq([p for p, _ in hist]),
        "source": source, "source_url": source_url, "note": note,
        "history": [[p, v] for p, v in hist], "stale": False,
    }


# ── 台灣金屬行情網 ─────────────────────────────────────────

def decode_page_data(html: str) -> dict | None:
    soup = BeautifulSoup(html, "lxml")
    tag = soup.find("script", {"type": "application/json", "id": "page-data"})
    if not tag:
        return None
    raw = json.loads(tag.string or "{}").get("a", "")
    if raw[:2] in ("b'", 'b"'):
        raw = raw[2:-1]
    return ast.literal_eval(base64.b64decode(raw).decode("utf-8"))


def split_name_unit(label: str) -> tuple[str, str]:
    """'豐興鋼筋盤價(新台幣元/公噸)' -> ('豐興鋼筋盤價', '元/公噸')."""
    m = re.match(r"^(.*?)\s*[\(（]([^\(\)（）]*)[\)）]\s*$", label)
    if not m:
        return label.strip(), ""
    unit = m.group(2).replace("新台幣", "").strip()
    return m.group(1).strip(), unit


def parse_metaltrade(html: str) -> tuple[str, str, list[tuple[str, float]]] | None:
    data = decode_page_data(html)
    if not data:
        return None
    xs, y = data.get("X1") or [], data.get("Y1") or {}
    name, unit = split_name_unit(str(y.get("name") or ""))
    raw = list(zip(xs, y.get("data") or []))
    if not raw:
        return None
    periods = [str(x)[:10] for x, _ in raw]
    monthly = all(p.endswith("-01") for p in periods[-6:]) and infer_freq(periods) == "月"
    hist = []
    for x, v in raw:
        p = str(x)[:7] if monthly else str(x)[:10]
        hist.append((p, to_float(v)))
    return name, unit, hist


def fetch_metaltrade(session) -> list[dict]:
    items = []
    for path, item_id, group, region in METALTRADE_SERIES:
        url = METALTRADE_BASE + path
        try:
            r = _get(session, url, headers={"Referer": METALTRADE_BASE})
            r.encoding = r.apparent_encoding or "utf-8"
            parsed = parse_metaltrade(r.text)
        except Exception as e:
            log(f"  metaltrade {path} failed: {e}")
            continue
        if not parsed:
            log(f"  metaltrade {path}: no page-data")
            continue
        name, unit, hist = parsed
        it = make_item(id=item_id, name=name, group=group, unit=unit, history=hist,
                       source="台灣金屬行情網", source_url=url, region=region)
        if it:
            items.append(it)
        time.sleep(0.5)
    return items


# ── 主計總處 營造工程物價指數 ───────────────────────────────

def clean_cci_name(raw: str) -> str:
    name = re.sub(r"\(指數基期[^)]*\)", "", raw).strip()
    name = re.sub(r"^[一二三四五六七八九十]+\.", "", name)
    name = re.sub(r"^\([一二三四五六七八九十]+\)", "", name)
    return name.replace("_", " · ").strip()


def parse_dgbas_cci(xml_text: str) -> dict[str, list[tuple[str, float]]]:
    """Returns {item name: [(YYYY-MM, value)]} preserving the XML's item order."""
    series: dict[str, list] = {}
    for block in re.findall(r"<Obs>(.*?)</Obs>", xml_text, re.S):
        def f(tag):
            m = re.search(rf"<{tag}>(.*?)</{tag}>", block, re.S)
            return m.group(1).strip() if m else ""
        if f("TYPE") != "原始值":
            continue
        m = re.fullmatch(r"(\d{4})M(\d{2})", f("TIME_PERIOD"))
        v = to_float(f("Item_VALUE"))
        if not m or v is None:
            continue
        series.setdefault(clean_cci_name(f("Item")), []).append((f"{m.group(1)}-{m.group(2)}", v))
    return series


def fetch_dgbas_cci(session) -> list[dict]:
    r = _get(session, DGBAS_CCI_URL, timeout=60)
    r.encoding = "utf-8"
    items = []
    for i, (name, hist) in enumerate(parse_dgbas_cci(r.text).items()):
        it = make_item(id=f"cci_tw_{i:02d}", name=name, group="cci_national", unit="指數",
                       history=hist, source="行政院主計總處", source_url=DGBAS_CCI_URL,
                       region="全國", freq="月")
        if it:
            items.append(it)
    return items


def parse_taipei_cci(csv_text: str) -> dict[str, list[tuple[str, float]]]:
    import csv
    rows = list(csv.reader(io.StringIO(csv_text)))
    if not rows:
        return {}
    header = rows[0]
    wanted = {"總指數": "臺北市 · 總指數", "材料類指數": "臺北市 · 材料類", "勞務類指數": "臺北市 · 勞務類"}
    cols = {}
    for i, h in enumerate(header):
        for key, label in wanted.items():
            if h.endswith("/" + key):
                cols[label] = i
    out: dict[str, list] = {label: [] for label in cols}
    for row in rows[1:]:
        if not row:
            continue
        month = roc_to_month(row[0])
        if not month:
            continue
        for label, i in cols.items():
            if i < len(row):
                out[label].append((month, to_float(row[i])))
    return out


def parse_ntpc_cci(csv_text: str) -> list[tuple[str, float]]:
    import csv
    hist = []
    for row in csv.reader(io.StringIO(csv_text)):
        if len(row) >= 2:
            month = roc_to_month(row[0])
            if month:
                hist.append((month, to_float(row[1])))
    return hist


def parse_taichung_cci(records: list[dict]) -> dict[str, list[tuple[str, float]]]:
    out: dict[str, list] = {}
    for rec in records:
        if not str(rec.get("項目", "")).startswith("營造工程物價指數-物價指數"):
            continue
        month = str(rec.get("資料時間日期", ""))[:7]
        name = str(rec.get("欄位名稱", "")).strip()
        if re.fullmatch(r"\d{4}-\d{2}", month) and name:
            out.setdefault(f"臺中市 · {name}", []).append((month, to_float(rec.get("數值"))))
    return out


def fetch_local_cci(session) -> list[dict]:
    items, errors = [], []
    try:
        r = _get(session, TAIPEI_CCI_URL)
        for label, hist in parse_taipei_cci(r.content.decode("utf-8-sig", "replace")).items():
            it = make_item(id=f"cci_tpe_{label.split(' · ')[1]}", name=label, group="cci_local", unit="指數",
                           history=hist, source="臺北市政府主計處", source_url=TAIPEI_CCI_URL,
                           region="臺北市", freq="月")
            if it:
                items.append(it)
    except Exception as e:
        errors.append(f"臺北市: {e}")
    try:
        r = _get(session, NTPC_CCI_URL)
        it = make_item(id="cci_ntpc_total", name="新北市 · 總指數", group="cci_local", unit="指數",
                       history=parse_ntpc_cci(r.content.decode("utf-8-sig", "replace")),
                       source="新北市政府主計處", source_url=NTPC_CCI_URL, region="新北市", freq="月")
        if it:
            items.append(it)
    except Exception as e:
        errors.append(f"新北市: {e}")
    try:
        meta = _get(session, TAICHUNG_DATASET_API).json().get("result", {})
        records = []
        for d in meta.get("distribution") or []:
            u = d.get("resourceDownloadUrl")
            if u and (d.get("resourceFormat") or "").upper() == "JSON":
                try:
                    records.extend(_get(session, u, timeout=60).json())
                except Exception as e:
                    errors.append(f"臺中市 resource: {e}")
        for i, (label, hist) in enumerate(parse_taichung_cci(records).items()):
            it = make_item(id=f"cci_txg_{i:02d}", name=label, group="cci_local", unit="指數",
                           history=hist, source="臺中市政府主計處",
                           source_url="https://data.gov.tw/dataset/167838", region="臺中市", freq="月")
            if it:
                items.append(it)
    except Exception as e:
        errors.append(f"臺中市: {e}")
    if errors:
        log(f"  local CCI partial errors: {errors}")
    if not items:
        raise RuntimeError("; ".join(errors) or "no local CCI items")
    return items


# ── World Bank Pink Sheet ──────────────────────────────────

def parse_worldbank(xlsx_bytes: bytes) -> list[dict]:
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes), read_only=True, data_only=True)
    rows = list(wb["Monthly Prices"].iter_rows(values_only=True))
    hdr_i = next(i for i, row in enumerate(rows) if row and any(str(c or "").startswith("Crude oil") for c in row))
    header = [str(c or "").replace("**", "").strip() for c in rows[hdr_i]]
    units = [str(c or "").strip() for c in rows[hdr_i + 1]]
    data_rows = [r for r in rows[hdr_i + 2:] if r and re.fullmatch(r"\d{4}M\d{2}", str(r[0] or ""))]
    items = []
    for col_name, item_id, zh in WB_COMMODITIES:
        try:
            ci = next(i for i, h in enumerate(header) if h == col_name)
        except StopIteration:
            continue
        hist = [(f"{str(r[0])[:4]}-{str(r[0])[5:7]}", to_float(r[ci])) for r in data_rows[-HISTORY_POINTS - 1:]]
        it = make_item(id=item_id, name=zh, group="commodities", unit=WB_UNITS.get(units[ci], units[ci]),
                       history=hist, source="World Bank Pink Sheet", source_url=WB_SOURCE_URL,
                       region="國際", freq="月", note=col_name)
        if it:
            items.append(it)
    return items


def fetch_worldbank(session) -> list[dict]:
    landing = _get(session, WB_LANDING).text
    links = re.findall(r'https?://[^"\']+?CMO-Historical-Data-Monthly\.xlsx', landing)
    if not links:
        raise RuntimeError("monthly xlsx link not found on landing page")
    return parse_worldbank(_get(session, links[0], timeout=90).content)


# ── TWSE daily closes ──────────────────────────────────────

def parse_twse(rows: list[dict]) -> list[dict]:
    items = []
    for code in TWSE_CODES:
        row = next((r for r in rows if r.get("Code") == code), None)
        if not row:
            continue
        close, chg = to_float(row.get("ClosingPrice")), to_float(row.get("Change"))
        date = roc_date_to_iso(str(row.get("Date", "")))
        if close is None or not date:
            continue
        prev = round(close - chg, 4) if chg is not None else None
        items.append({
            "id": f"twse_{code}", "name": f"{row.get('Name', code)}（{code}）", "group": "stocks",
            "region": "臺灣", "unit": "元/股", "value": close, "period": date,
            "prev": prev, "prev_period": None, "change": chg,
            "change_pct": round(chg / prev * 100, 3) if prev else None,
            "freq": "日", "source": "臺灣證券交易所", "source_url": "https://openapi.twse.com.tw/",
            "note": "水泥股" if code.startswith("11") else "鋼鐵股",
            "history": [[date, close]], "stale": False,
        })
    return items


def fetch_twse(session) -> list[dict]:
    rows = _get(session, TWSE_URL, timeout=60).json()
    items = parse_twse(rows)
    if not items:
        raise RuntimeError("no matching TWSE codes")
    return items


# ── FX ─────────────────────────────────────────────────────

def fx_item(fx: dict | None) -> list[dict]:
    if not fx or not fx.get("usd_twd"):
        return []
    date = str(fx.get("fetched_at") or datetime.now(TW_TZ).isoformat())[:10]
    it = make_item(id="fx_usd_twd", name="美元兌新台幣", group="fx", unit="新台幣/美元",
                   history=[(date, fx["usd_twd"])], source=fx.get("source") or "銀行牌告",
                   source_url="https://accessibility.cathaybk.com.tw/exchange-rate-search.aspx",
                   region="臺灣", freq="日")
    if it and fx.get("carried_over"):
        it["stale"] = True
    return [it] if it else []


# ── Google News RSS headline feed ─────────────────────────

def parse_google_news(xml_text: str, query: str) -> list[dict]:
    out = []
    for block in re.findall(r"<item>(.*?)</item>", xml_text, re.S):
        def f(tag):
            m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", block, re.S)
            return re.sub(r"<!\[CDATA\[|\]\]>", "", m.group(1)).strip() if m else ""
        title, link, pub, src = f("title"), f("link"), f("pubDate"), f("source")
        title = re.sub(r"&amp;", "&", title)
        if src and title.endswith(" - " + src):
            title = title[: -(len(src) + 3)].strip()
        try:
            date = parsedate_to_datetime(pub).astimezone(TW_TZ).strftime("%Y-%m-%d")
        except Exception:
            date = ""
        if title:
            out.append({"title": title, "url": link, "source": src, "date": date, "query": query})
    return out


def fetch_news_feed(session) -> list[dict]:
    seen, feed = set(), []
    for q in NEWS_QUERIES:
        try:
            r = _get(session, GOOGLE_NEWS_RSS, params={
                "q": f"{q} when:14d", "hl": "zh-TW", "gl": "TW", "ceid": "TW:zh-Hant"})
        except Exception as e:
            log(f"  news query {q!r} failed: {e}")
            continue
        for n in parse_google_news(r.text, q):
            if n["source"] in NEWS_SOURCE_BLOCKLIST or NEWS_TITLE_EXCLUDE.search(n["title"]):
                continue
            key = re.sub(r"\s+", "", n["title"])
            if key not in seen:
                seen.add(key)
                feed.append(n)
        time.sleep(0.4)
    feed.sort(key=lambda n: n["date"], reverse=True)
    return feed[:60]


# ── Orchestration ─────────────────────────────────────────

def _load_previous() -> dict:
    try:
        return json.loads(MATERIALS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _merge_accumulating(items: list[dict], prev_items: dict) -> None:
    """For sources that return only the latest point, extend history from the previous run."""
    for it in items:
        old = prev_items.get(it["id"])
        if not old:
            continue
        merged = dict(old.get("history", []))
        for p, v in it["history"]:
            merged[p] = v
        hist = sorted(merged.items())[-HISTORY_POINTS:]
        it["history"] = [[p, v] for p, v in hist]
        if len(hist) >= 2 and it["group"] == "fx":
            it["prev_period"], it["prev"] = hist[-2]
            it["change"] = round(it["value"] - it["prev"], 6)
            it["change_pct"] = round(it["change"] / it["prev"] * 100, 3) if it["prev"] else None


def build_materials(fx: dict | None = None) -> dict:
    """Fetch every source; carry over stale items for sources that fail."""
    log("Fetching construction material sources ...")
    session = _session()
    prev = _load_previous()
    prev_items = {it["id"]: it for it in prev.get("items", [])}
    fetchers = [
        ("台灣金屬行情網", fetch_metaltrade, ("tw_steel", "intl_steel", "production")),
        ("行政院主計總處", fetch_dgbas_cci, ("cci_national",)),
        ("地方主計處", fetch_local_cci, ("cci_local",)),
        ("World Bank", fetch_worldbank, ("commodities",)),
        ("臺灣證券交易所", fetch_twse, ("stocks",)),
    ]
    items, status = [], []
    for name, fn, groups in fetchers:
        t0 = time.time()
        try:
            got = fn(session)
            if not got:
                raise RuntimeError("no items parsed")
            if fn is fetch_twse:
                _merge_accumulating(got, prev_items)
            items.extend(got)
            status.append({"source": name, "ok": True, "items": len(got), "seconds": round(time.time() - t0, 1)})
            log(f"  {name}: {len(got)} items")
        except Exception as e:
            carried = [dict(it, stale=True) for it in prev_items.values() if it.get("group") in groups]
            items.extend(carried)
            status.append({"source": name, "ok": False, "items": len(carried), "error": str(e)[:200]})
            log(f"  {name} FAILED ({e}); carried over {len(carried)} stale items")

    fx_items = fx_item(fx)
    if fx_items:
        _merge_accumulating(fx_items, prev_items)
        items.extend(fx_items)
    elif "fx_usd_twd" in prev_items:
        items.append(dict(prev_items["fx_usd_twd"], stale=True))

    try:
        news = fetch_news_feed(session)
        ok = bool(news)
        news = news or prev.get("news_feed", [])
        status.append({"source": "Google 新聞", "ok": ok, "items": len(news)})
    except Exception as e:
        news = prev.get("news_feed", [])
        status.append({"source": "Google 新聞", "ok": False, "items": len(news), "error": str(e)[:200]})

    order = {g["id"]: i for i, g in enumerate(GROUPS)}
    items.sort(key=lambda it: order.get(it["group"], 99))
    return {
        "updated_at": datetime.now(TW_TZ).isoformat(),
        "groups": GROUPS,
        "items": items,
        "news_feed": news,
        "sources_status": status,
    }


def build_chart_data(materials: dict) -> dict | None:
    """Rebuild the trend chart from full source histories, each series on its own months."""
    by_id = {it["id"]: it for it in materials.get("items", []) if not it.get("stale")}
    keys = ["billet_price", "fengxing_rebar_price", "h_beam_price", "csc_wire_rod_price",
            "north_scrap_price", "crude_steel_production"]
    if not all(k in by_id for k in keys[:4]):
        return None
    series = {k: dict(by_id[k]["history"]) if k in by_id else {} for k in keys}
    months = sorted(set().union(*(series[k].keys() for k in keys[:5])))[-HISTORY_POINTS:]
    chart = {"months": months}
    for k in keys:
        chart[k] = [series[k].get(m) for m in months]
    return chart


def write_outputs(materials: dict) -> None:
    MATERIALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    MATERIALS_PATH.write_text(json.dumps(materials, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"Saved {MATERIALS_PATH} ({len(materials['items'])} items)")
    chart = build_chart_data(materials)
    if chart:
        CHART_PATH.write_text(json.dumps(chart, ensure_ascii=False), encoding="utf-8")
        log(f"Rebuilt {CHART_PATH} ({len(chart['months'])} months)")
    else:
        log("Chart data not rebuilt (metaltrade series unavailable); keeping previous file")


def taiwan_prices_from_materials(materials: dict) -> dict:
    """The six headline series in the legacy latest.json shape, each with its own month."""
    units = {"crude_steel_production": "萬噸", "north_scrap_price": "元/公斤"}
    by_id = {it["id"]: it for it in materials.get("items", [])}
    out, months = {}, []
    for key in ["crude_steel_production", "north_scrap_price", "billet_price",
                "fengxing_rebar_price", "h_beam_price", "csc_wire_rod_price"]:
        it = by_id.get(key)
        if not it:
            out[key] = {"value": None, "unit": units.get(key, "元/公噸"), "mom_change": None, "month": None}
            continue
        out[key] = {
            "value": it["value"], "unit": units.get(key, "元/公噸"),
            "mom_change": it["change"], "month": it["period"], "stale": it.get("stale", False),
        }
        if key != "crude_steel_production":
            months.append(it["period"])
    out["data_month"] = max(months) if months else None
    return out


def main():
    from analyze import fetch_exchange_rate
    materials = build_materials(fetch_exchange_rate())
    write_outputs(materials)


if __name__ == "__main__":
    main()
