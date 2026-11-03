"""
Daily newsletter deck: a condensed PPTX of the day's prices, forecasts and news.

Runs after analyze.py has finished, so it only ever summarises the final,
complete analysis. Two stages:

1. GPT-6 Luna writes the slide text as JSON from the finished data. The code
   checks it (required fields, length limits, no links or markdown, and every
   number must exist in the source data) and sends any problems back for a
   rewrite. If it still cannot pass, no deck is published rather than a bad one.
2. The code lays out the slides itself in the website's style. All tables,
   numbers, badges, probabilities and the chart come straight from the data,
   so the model never decides a figure that appears on a slide.

Output: reports/steel-daily-YYYY-MM-DD.pptx and data/report.json (manifest the
site reads for its download button). Old decks are pruned after KEEP_DAYS.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
from lxml import etree
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION, XL_MARKER_STYLE
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt

sys.path.insert(0, str(Path(__file__).parent))
from prompts import WRITING_RULES  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
REPORTS = ROOT / "reports"
TW = timezone(timedelta(hours=8))
KEEP_DAYS = 30

OPENAI_URL = "https://api.openai.com/v1/responses"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODELS = [("openai", "gpt-6-luna"), ("openrouter", "openai/gpt-6-luna")]
EFFORT = "medium"
ATTEMPTS = 3

ITEMS = [
    ("north_scrap_price", "北部廢鋼大盤收購價", "N. Taiwan Scrap"),
    ("billet_price", "小鋼胚中級出廠價", "Billet Ex-Factory"),
    ("fengxing_rebar_price", "豐興鋼筋盤價", "Fengxing Rebar"),
    ("h_beam_price", "東鋼H型鋼流通價", "H-Beam Circulation"),
    ("csc_wire_rod_price", "中鋼棒線盤價", "CSC Wire Rod"),
]
PRICE_ROWS = [("crude_steel_production", "臺灣粗鋼產量", "Crude Steel Production")] + ITEMS
CHART_SERIES = [("billet_price", "小鋼胚"), ("fengxing_rebar_price", "鋼筋"),
                ("h_beam_price", "H型鋼"), ("csc_wire_rod_price", "棒線")]
DIR = {"up": "▲ 看漲", "down": "▼ 看跌", "stable": "◆ 持平"}
MOVER_GROUPS = {"cci_national", "cci_local", "commodities", "intl_steel"}

# Website light theme.
CREAM = RGBColor(0xE6, 0xE6, 0xEB)
PAPER = RGBColor(0xF6, 0xF6, 0xF8)
INK = RGBColor(0x2A, 0x1F, 0x17)
MUTED = RGBColor(0x6D, 0x62, 0x5A)
COPPER = RGBColor(0x7A, 0x4A, 0x28)
DOWN = RGBColor(0x9C, 0x50, 0x50)
SAND = RGBColor(0xA8, 0x96, 0x82)
LINE = RGBColor(0xC9, 0xC6, 0xC6)
UP_DIM = RGBColor(0xE0, 0xD5, 0xCE)
DOWN_DIM = RGBColor(0xE3, 0xD3, 0xD5)
FLAT_DIM = RGBColor(0xDB, 0xD9, 0xDA)
CHART_COLORS = [COPPER, DOWN, MUTED, SAND]

CJK = "Microsoft JhengHei"
LATIN = "Arial"
SERIF = "Georgia"
MONO = "Consolas"

W, H = Inches(13.333), Inches(7.5)
MX = Inches(0.7)


def log(msg: str):
    print(f"[report] {msg}", flush=True)


def load(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def fmt(v) -> str:
    if not isinstance(v, (int, float)):
        return str(v if v is not None else "-")
    if abs(v) >= 1000 or float(v).is_integer():
        return f"{v:,.0f}"
    return f"{v:,.2f}".rstrip("0").rstrip(".")


def signed(v) -> str:
    if not isinstance(v, (int, float)):
        return "-"
    return ("+" if v > 0 else "") + fmt(v)


# ── Source data for the writer ───────────────────────────────

def plain(s) -> str:
    s = re.sub(r"\(?\s*\[([^\]]*)\]\([^)]*\)\s*\)?", "", str(s or ""))
    s = re.sub(r"https?://\S+", "", s)
    return re.sub(r"\s+", " ", s).strip()


def build_source(d: dict, m: dict, acc: dict) -> str:
    out = []

    def add(title, lines):
        lines = [x for x in (lines if isinstance(lines, list) else [lines]) if x]
        if lines:
            out.append(f"【{title}】\n" + "\n".join(lines))

    add("資料日期", f"分析發布日 {d.get('date', '-')}")
    add("今日重點", [d.get("headline"), d.get("headline_sub"), plain(d.get("summary"))])
    names = {k: n for k, n, _ in PRICE_ROWS}
    add("台灣鋼材行情", [
        f"{names.get(k, k)}：{fmt(v.get('value'))} {v.get('unit', '')}（{v.get('month', '-')}，較前月 {signed(v.get('mom_change'))}）"
        for k, v in (d.get("taiwan_prices") or {}).items() if isinstance(v, dict)])
    fx = d.get("exchange_rate") or {}
    if fx:
        add("匯率", f"美元兌新台幣 {fx.get('usd_twd')}。{plain(fx.get('impact_on_steel'))}")
    for key, title in (("spread_analysis", "價差"), ("monthly_trend", "本月趨勢"),
                       ("international_outlook", "國際市場"), ("materials_outlook", "營建材料展望")):
        add(title, plain(d.get(key)))
    add("風險因素", [f"・{plain(r)}" for r in d.get("risk_factors") or []])

    pf = d.get("price_forecast") or {}
    lines = [f"預測期間：{pf.get('week_label', '本週')} {pf.get('week_range', '')}"]
    for key, name, _ in ITEMS:
        f = (pf.get("items") or {}).get(key) or {}
        w, n = f.get("week") or {}, f.get("next_month") or {}
        tgt = ((pf.get("targets") or {}).get(key) or {}).get("target_month", "下一期")
        sc = (n.get("scenarios") or {})
        probs = "、".join(f"{DIR.get(s, s)[2:]}{(sc.get(s) or {}).get('prob')}%" for s in ("up", "stable", "down") if sc.get(s))
        lines += [f"■ {name}",
                  f"  本週：{DIR.get(w.get('direction'), '-')} {w.get('change_estimate', '')}。{plain(w.get('reason'))}",
                  f"  {tgt} 月均價：{DIR.get(n.get('direction'), '-')} {n.get('change_estimate', '')}（{probs}）。{plain(n.get('reason'))}"]
        if f.get("counterpoint"):
            lines.append(f"  反方看法：{plain(f['counterpoint'])}")
        if f.get("watch"):
            lines.append(f"  後續觀察：{plain(f['watch'])}")
    if pf.get("overall_basis"):
        lines.append(f"綜合推論：{plain(pf['overall_basis'])}")
    add("盤價預測", lines)

    if acc and acc.get("overall"):
        o = acc["overall"]
        add("過去預測準確度", f"月均價方向命中 {o.get('hits')}/{o.get('total')} 次")
    r = d.get("research") or {}
    add("查證過的事實", [f"［{f.get('date', '')}・{f.get('source_count', 1)} 個來源］{plain(f.get('fact'))}"
                       for f in (r.get("facts") or [])[:40]])
    add("原物料推理鏈", [f"・{c.get('chain')}：{c.get('status')}。{plain(c.get('note'))}" for c in r.get("chains") or []])
    add("今日重點新聞", [f"・{s.get('headline')}｜{s.get('subheadline', '')}（{s.get('source', '')} {s.get('date', '')}）"
                       for s in d.get("top_stories") or []])
    add("營建材料與原物料變動", [f"・{it['name']}：{fmt(it['value'])} {it.get('unit', '')}（{it.get('period')}，較前期 {it['change_pct']:+.2f}%）"
                             for it in movers(m, 12) + [x for x in construction_movers(m) if x not in movers(m, 12)]])
    return "\n\n".join(out)


def movers(m: dict, n: int) -> list[dict]:
    items = [it for it in (m or {}).get("items", [])
             if it.get("group") in MOVER_GROUPS and not it.get("stale")
             and isinstance(it.get("change_pct"), (int, float)) and isinstance(it.get("value"), (int, float))]
    return sorted(items, key=lambda it: abs(it["change_pct"]), reverse=True)[:n]


# ── Writer prompt and checks ────────────────────────────────

LIMITS = {
    "cover.title": 28, "cover.subtitle": 32, "cover.summary": 100,
    "key_points.title": 16, "key_points.detail": 62,
    "price_notes": 26,
    "trend.title": 22, "trend.points": 58,
    "forecast.title": 24, "forecast.week": 40, "forecast.month": 42, "forecast.overall": 90,
    "materials.title": 22, "materials.points": 58,
    "international.title": 22, "international.points": 58,
    "news.headline": 28, "news.why": 60,
    "risks.risk": 46, "risks.watch": 46,
    "actions.title": 22, "actions.points": 60,
}
COUNTS = {"key_points": (4, 4), "trend.points": (2, 3), "materials.points": (3, 4),
          "international.points": (3, 4), "news": (3, 5), "risks": (3, 4), "actions.points": (3, 4)}


def writer_prompt(source: str, feedback: str = "") -> str:
    keys = "、".join(k for k, *_ in ITEMS) + "、crude_steel_production"
    fb = f"\n<previous_problems>\n上一版有以下問題，請全部修正後重寫整份 JSON：\n{feedback}\n</previous_problems>\n" if feedback else ""
    return f"""<role>
你是台灣鋼鐵市場每日電子報的主編。下方 <source> 是今天已經完成的完整分析。請把它濃縮成一份給營造公司總經理看的每日簡報文字。
你只負責文字，表格、數字、圖表會由程式從資料直接產生。
</role>

<rules>
- 只能使用 <source> 裡的資訊。不要加入 <source> 沒有的事實、數字或日期，也不要自己計算新的數字。
- 引用數字時照抄 <source> 的寫法並帶單位，例如「每公噸18,500元」。
- 每個欄位都有字數上限（括號內），寧可短，不可超過。每一則只講一件事。
- 不要使用 markdown、網址、英文句子、事實編號（如 F1）。
- 不要寫任何免責或提醒字句，例如「AI 預估」「不是保證」「預測不保證」「僅供參考」「請自行判斷」。簡報最後一頁已在固定位置統一說明，重複寫會干擾閱讀。說到預測時直接講方向、幅度和機率，例如「11月鋼筋月均價看漲，約每公噸+60至+300元，上漲機率42%」。
- 不確定或只有單一來源的事要明說。
</rules>

{WRITING_RULES}

<output_format>
只輸出一個 JSON 物件：
{{
  "cover": {{"title": "<今天最重要的一件事，像報紙頭條（{LIMITS['cover.title']}字內）>",
             "subtitle": "<第二重要的事（{LIMITS['cover.subtitle']}字內）>",
             "summary": "<三句內的今日總結（{LIMITS['cover.summary']}字內）>"}},
  "key_points": [ {{"title": "<重點標題（{LIMITS['key_points.title']}字內）>", "detail": "<說明（{LIMITS['key_points.detail']}字內）>"}} ，剛好 4 則 ],
  "price_notes": {{"<品項代號>": "<這個報價的一句短評，講原因或意義，不要重複表格已有的價格、漲跌與月份（{LIMITS['price_notes']}字內）>"}}，品項代號為：{keys},
  "trend": {{"title": "<走勢頁標題（{LIMITS['trend.title']}字內）>", "points": ["<近月走勢的觀察（{LIMITS['trend.points']}字內）>", 2 到 3 則]}},
  "forecast": {{"title": "<預測頁標題（{LIMITS['forecast.title']}字內）>",
                "items": {{"<品項代號，不含 crude_steel_production>": {{"week": "<本週預估的理由（{LIMITS['forecast.week']}字內）>", "month": "<月均價預估的理由（{LIMITS['forecast.month']}字內）>"}}}},
                "overall": "<綜合判斷（{LIMITS['forecast.overall']}字內）>"}},
  "materials": {{"title": "<營建材料頁標題（{LIMITS['materials.title']}字內）>", "points": ["<營建材料或物價指數的重點（{LIMITS['materials.points']}字內）>", 3 到 4 則]}},
  "international": {{"title": "<國際市場頁標題（{LIMITS['international.title']}字內）>", "points": ["<國際鋼市、原物料或匯率重點（{LIMITS['international.points']}字內）>", 3 到 4 則]}},
  "news": [ {{"headline": "<新聞標題改寫（{LIMITS['news.headline']}字內）>", "why": "<這則新聞對台灣鋼價或工程成本的意義（{LIMITS['news.why']}字內）>", "source": "<媒體名稱>", "date": "<YYYY-MM-DD>"}}，3 到 5 則，選最重要的 ],
  "risks": [ {{"risk": "<可能讓預測失準的風險（{LIMITS['risks.risk']}字內）>", "watch": "<接下來要觀察什麼（{LIMITS['risks.watch']}字內）>"}}，3 到 4 則 ],
  "actions": {{"title": "<對採購的意義頁標題（{LIMITS['actions.title']}字內）>", "points": ["<對鋼材採購、工程報價或成本控管的具體意義（{LIMITS['actions.points']}字內）>", 3 到 4 則]}}
}}
</output_format>
{fb}
<source>
{source}
</source>

再次提醒：只用 <source> 的資訊，遵守字數上限，只輸出 JSON。"""


DISCLAIMER = re.compile(r"AI\s*預估|AI\s*預測|不是保證|並非保證|不保證|僅供參考|請自行判斷")
NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def numbers_in(text: str) -> set[str]:
    out = set()
    for raw in NUM.findall(text or ""):
        v = raw.replace(",", "")
        if v.endswith(".0"):
            v = v[:-2]
        out.add(v)
    return out


def iter_texts(content: dict):
    """Yield (path, text, limit) for every model-written string."""
    c = content
    for k in ("title", "subtitle", "summary"):
        yield f"cover.{k}", (c.get("cover") or {}).get(k), LIMITS[f"cover.{k}"]
    for i, kp in enumerate(c.get("key_points") or []):
        yield f"key_points[{i}].title", kp.get("title"), LIMITS["key_points.title"]
        yield f"key_points[{i}].detail", kp.get("detail"), LIMITS["key_points.detail"]
    for k, v in (c.get("price_notes") or {}).items():
        yield f"price_notes.{k}", v, LIMITS["price_notes"]
    for sec in ("trend", "materials", "international", "actions"):
        s = c.get(sec) or {}
        yield f"{sec}.title", s.get("title"), LIMITS[f"{sec}.title"]
        for i, p in enumerate(s.get("points") or []):
            yield f"{sec}.points[{i}]", p, LIMITS[f"{sec}.points"]
    fc = c.get("forecast") or {}
    yield "forecast.title", fc.get("title"), LIMITS["forecast.title"]
    yield "forecast.overall", fc.get("overall"), LIMITS["forecast.overall"]
    for k, v in (fc.get("items") or {}).items():
        yield f"forecast.items.{k}.week", (v or {}).get("week"), LIMITS["forecast.week"]
        yield f"forecast.items.{k}.month", (v or {}).get("month"), LIMITS["forecast.month"]
    for i, n in enumerate(c.get("news") or []):
        yield f"news[{i}].headline", n.get("headline"), LIMITS["news.headline"]
        yield f"news[{i}].why", n.get("why"), LIMITS["news.why"]
    for i, r in enumerate(c.get("risks") or []):
        yield f"risks[{i}].risk", r.get("risk"), LIMITS["risks.risk"]
        yield f"risks[{i}].watch", r.get("watch"), LIMITS["risks.watch"]


def check(content: dict, source: str) -> list[str]:
    problems = []
    if not isinstance(content, dict):
        return ["輸出不是 JSON 物件"]
    for key, (lo, hi) in COUNTS.items():
        sec, _, sub = key.partition(".")
        arr = (content.get(sec) or {}).get(sub) if sub else content.get(sec)
        n = len(arr) if isinstance(arr, list) else 0
        if not lo <= n <= hi:
            problems.append(f"{key} 應有 {lo}～{hi} 則，目前 {n} 則")
    needed = [k for k, *_ in PRICE_ROWS]
    missing = [k for k in needed if not (content.get("price_notes") or {}).get(k)]
    if missing:
        problems.append(f"price_notes 缺少：{'、'.join(missing)}")
    missing = [k for k, *_ in ITEMS if not ((content.get("forecast") or {}).get("items") or {}).get(k)]
    if missing:
        problems.append(f"forecast.items 缺少：{'、'.join(missing)}")

    allowed = numbers_in(source)
    for path, text, limit in iter_texts(content):
        if not isinstance(text, str) or not text.strip():
            problems.append(f"{path} 是空的")
            continue
        if len(text) > limit:
            problems.append(f"{path} 有 {len(text)} 字，超過上限 {limit} 字：「{text}」")
        if re.search(r"https?://|www\.|\*\*|\[[^\]]*\]\(|^#", text):
            problems.append(f"{path} 含有網址或 markdown：「{text}」")
        if DISCLAIMER.search(text):
            problems.append(f"{path} 含有免責字句（如「AI 預估」「不是保證」），請刪除後直接講結論：「{text}」")
        if re.search(r"\bF\d+\b", text):
            problems.append(f"{path} 含有事實編號：「{text}」")
        bad = sorted(v for v in numbers_in(text)
                     if v not in allowed and not (v.isdigit() and int(v) <= 31))
        if bad:
            problems.append(f"{path} 的數字 {', '.join(bad)} 在資料中找不到，請改用資料裡的數字或刪除：「{text}」")
    return problems


def call_model(provider: str, model: str, prompt: str) -> str:
    if provider == "openai":
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("OPENAI_API_KEY not set")
        r = requests.post(OPENAI_URL, timeout=600, headers={"Authorization": f"Bearer {key}"}, json={
            "model": model, "input": prompt, "reasoning": {"effort": EFFORT},
            "text": {"format": {"type": "json_object"}}, "max_output_tokens": 16000, "store": False,
        })
        if not r.ok:
            raise RuntimeError(f"OpenAI HTTP {r.status_code}: {r.text[:300]}")
        j = r.json()
        u = j.get("usage") or {}
        log(f"  usage in={u.get('input_tokens')} out={u.get('output_tokens')}")
        return "".join(c.get("text", "") for item in j.get("output", []) if item.get("type") == "message"
                       for c in item.get("content", []) if c.get("type") == "output_text")
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY not set")
    r = requests.post(OPENROUTER_URL, timeout=600, headers={"Authorization": f"Bearer {key}"}, json={
        "model": model, "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"}, "reasoning": {"effort": EFFORT}, "max_tokens": 16000,
    })
    if not r.ok:
        raise RuntimeError(f"OpenRouter HTTP {r.status_code}: {r.text[:300]}")
    return r.json()["choices"][0]["message"].get("content") or ""


def parse_json(text: str):
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?|```$", "", text).strip()
    try:
        return json.loads(text)
    except Exception:
        a, b = text.find("{"), text.rfind("}")
        if a >= 0 and b > a:
            try:
                return json.loads(text[a:b + 1])
            except Exception:
                return None
    return None


def write_content(source: str) -> tuple[dict | None, str | None]:
    for provider, model in MODELS:
        feedback = ""
        for attempt in range(1, ATTEMPTS + 1):
            log(f"{provider}/{model} attempt {attempt}")
            try:
                content = parse_json(call_model(provider, model, writer_prompt(source, feedback)))
            except Exception as e:
                log(f"  failed: {e}")
                break
            problems = check(content, source) if content is not None else ["輸出不是有效的 JSON"]
            if not problems:
                return content, model
            log(f"  {len(problems)} problems: " + " | ".join(problems[:6]))
            feedback = "\n".join(f"- {p}" for p in problems[:30])
    return None, None


# ── Slide drawing ────────────────────────────────────────────

def set_font(run, size, color=INK, bold=False, kind="body", spacing=None):
    f = run.font
    f.size = Pt(size)
    f.bold = bold
    f.color.rgb = color
    latin = {"body": LATIN, "serif": SERIF, "mono": MONO}[kind]
    f.name = latin
    rpr = run._r.get_or_add_rPr()
    for tag in ("a:ea", "a:cs"):
        el = rpr.find(qn(tag))
        if el is None:
            el = etree.SubElement(rpr, qn(tag))
        el.set("typeface", CJK)
    if spacing is not None:
        rpr.set("spc", str(int(spacing)))


def text(slide, x, y, w, h, value, size=14, color=INK, bold=False, kind="body", align=PP_ALIGN.LEFT,
         anchor=MSO_ANCHOR.TOP, spacing=None, line=1.25):
    box = slide.shapes.add_textbox(x, y, w, h)
    tf = box.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = anchor
    paras = value if isinstance(value, list) else [value]
    for i, p in enumerate(paras):
        para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        para.alignment = align
        para.line_spacing = line
        runs = p if isinstance(p, list) else [(p, {})]
        for chunk, opts in runs:
            r = para.add_run()
            r.text = str(chunk)
            set_font(r, opts.get("size", size), opts.get("color", color), opts.get("bold", bold),
                     opts.get("kind", kind), opts.get("spacing", spacing))
    return box


def rect(slide, x, y, w, h, fill, line=None, shape=MSO_SHAPE.RECTANGLE, radius=None):
    s = slide.shapes.add_shape(shape, int(x), int(y), int(w), int(h))
    s.fill.solid()
    s.fill.fore_color.rgb = fill
    if line is None:
        s.line.fill.background()
    else:
        s.line.color.rgb = line
        s.line.width = Pt(0.75)
    style = s._element.find(qn("p:style"))
    if style is not None:
        s._element.remove(style)
    if radius is not None and shape == MSO_SHAPE.ROUNDED_RECTANGLE:
        s.adjustments[0] = radius
    return s


def hline(slide, x, y, w, color=LINE, weight=0.75):
    return rect(slide, x, y, w, Pt(weight), color)


def badge(slide, x, y, direction, w=Inches(1.05), h=Inches(0.34), size=11):
    fill, color = {"up": (UP_DIM, COPPER), "down": (DOWN_DIM, DOWN)}.get(direction, (FLAT_DIM, MUTED))
    s = rect(slide, x, y, w, h, fill, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.5)
    tf = s.text_frame
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    r = p.add_run()
    r.text = DIR.get(direction, "－")
    set_font(r, size, color, bold=True)
    return s


class Deck:
    def __init__(self, date: str):
        self.prs = Presentation()
        self.prs.slide_width, self.prs.slide_height = W, H
        self.blank = self.prs.slide_layouts[6]
        self.date = date
        self.section = 0

    def slide(self, en: str, zh: str, title: str):
        s = self.prs.slides.add_slide(self.blank)
        s.background.fill.solid()
        s.background.fill.fore_color.rgb = CREAM
        self.section += 1
        text(s, MX, Inches(0.5), Inches(9), Inches(0.3),
             [[(f"§ {self.section:02d} · {en.upper()}", {"kind": "body", "spacing": 300}),
               (f"   {zh}", {"spacing": 200})]], size=10.5, color=COPPER, bold=True)
        text(s, MX, Inches(0.85), W - 2 * MX, Inches(0.7), title, size=28, bold=True)
        hline(s, MX, Inches(1.62), W - 2 * MX, INK, 1.25)
        self.footer(s)
        return s

    def footer(self, s):
        n = len(self.prs.slides)
        hline(s, MX, H - Inches(0.55), W - 2 * MX)
        text(s, MX, H - Inches(0.45), Inches(7), Inches(0.25), "台灣鋼鐵市場分析 · 每日快報", size=9, color=MUTED, spacing=100)
        text(s, W - MX - Inches(4), H - Inches(0.45), Inches(4), Inches(0.25), f"{self.date}  ·  {n:02d}",
             size=9, color=MUTED, kind="mono", align=PP_ALIGN.RIGHT)


def bullets(slide, x, y, w, h, points, size=15, gap=10):
    paras = []
    for p in points:
        paras.append([("・", {"color": COPPER, "bold": True}), (p, {})])
    box = text(slide, x, y, w, h, paras, size=size, line=1.35)
    for para in box.text_frame.paragraphs:
        para.space_after = Pt(gap)
    return box


def cover(deck: Deck, d: dict, c: dict):
    s = deck.prs.slides.add_slide(deck.blank)
    s.background.fill.solid()
    s.background.fill.fore_color.rgb = CREAM
    text(s, MX, Inches(0.6), Inches(8), Inches(0.3), "AI ANALYSIS · 每日自動化分析報告", size=10.5, color=MUTED, spacing=300)
    text(s, MX, Inches(1.15), Inches(7.5), Inches(0.9), "T O D A Y", size=50, color=SAND, kind="serif", spacing=1200)
    text(s, MX, Inches(1.95), Inches(7.6), Inches(1.1), "鋼市每日快報", size=58, bold=True)
    rect(s, MX, Inches(3.35), Inches(0.07), Inches(1.0), COPPER)
    text(s, MX + Inches(0.3), Inches(3.3), Inches(6.9), Inches(0.6), c["cover"]["title"], size=22, bold=True, line=1.15)
    text(s, MX + Inches(0.3), Inches(3.95), Inches(6.9), Inches(0.4), c["cover"]["subtitle"], size=14, color=MUTED)
    text(s, MX, Inches(4.75), Inches(6.9), Inches(1.4), c["cover"]["summary"], size=14, color=MUTED, line=1.55)

    # Focus card, like the site's hero.
    x0, y0, cw = Inches(8.35), Inches(1.4), Inches(4.3)
    hline(s, x0, y0, cw)
    text(s, x0, y0 + Inches(0.35), cw, Inches(0.3), "TODAY'S FOCUS · 焦點報價", size=10, color=COPPER, spacing=300, bold=True)
    tp = (d.get("taiwan_prices") or {}).get("fengxing_rebar_price") or {}
    text(s, x0, y0 + Inches(0.75), cw, Inches(0.5), "豐興鋼筋盤價", size=24, bold=True)
    text(s, x0, y0 + Inches(1.28), cw, Inches(0.3), "Fengxing Rebar · 元 / 公噸", size=11, color=MUTED, spacing=100)
    text(s, x0, y0 + Inches(1.65), cw, Inches(1.0),
         [[("NT$ ", {"size": 18, "color": MUTED, "kind": "serif"}), (fmt(tp.get("value")), {"size": 54, "kind": "mono"})]], size=54)
    mom = tp.get("mom_change")
    text(s, x0, y0 + Inches(2.75), cw, Inches(0.35),
         [[(f"{signed(mom)} 元/公噸", {"color": COPPER if (mom or 0) > 0 else DOWN if (mom or 0) < 0 else MUTED, "bold": True, "kind": "mono"}),
           ("   vs. 上月", {"color": MUTED, "size": 11})]], size=15)
    text(s, x0, y0 + Inches(3.2), cw, Inches(0.3), f"DATA · {tp.get('month', '-')}", size=10, color=MUTED, kind="mono", spacing=200)
    hline(s, x0, y0 + Inches(3.7), cw)
    text(s, x0, y0 + Inches(3.95), cw, Inches(0.3), f"發布日期  {deck.date}", size=12, color=MUTED, kind="mono")
    deck.footer(s)


def key_points(deck: Deck, c: dict):
    s = deck.slide("Highlights", "今日重點", "今天你需要知道的四件事")
    cw, ch = (W - 2 * MX - Inches(0.4)) / 2, Inches(2.25)
    for i, kp in enumerate(c["key_points"][:4]):
        x = MX + (cw + Inches(0.4)) * (i % 2)
        y = Inches(1.95) + (ch + Inches(0.3)) * (i // 2)
        rect(s, x, y, cw, ch, PAPER, LINE)
        text(s, x + Inches(0.35), y + Inches(0.3), Inches(0.8), Inches(0.5), f"{i + 1:02d}", size=22, color=COPPER, kind="mono")
        text(s, x + Inches(1.1), y + Inches(0.3), cw - Inches(1.4), Inches(0.5), kp["title"], size=19, bold=True)
        text(s, x + Inches(1.1), y + Inches(0.9), cw - Inches(1.4), ch - Inches(1.1), kp["detail"], size=14, color=MUTED, line=1.5)


def price_table(deck: Deck, d: dict, c: dict):
    s = deck.slide("Today's Quotes", "全項鋼材報價", "台灣鋼材最新行情")
    tp = d.get("taiwan_prices") or {}
    cols = [("品名", Inches(3.3), PP_ALIGN.LEFT), ("報價", Inches(1.9), PP_ALIGN.RIGHT), ("單位", Inches(1.1), PP_ALIGN.LEFT),
            ("月增", Inches(1.6), PP_ALIGN.RIGHT), ("資料月份", Inches(1.2), PP_ALIGN.CENTER), ("短評", Inches(2.83), PP_ALIGN.LEFT)]
    y = Inches(1.85)
    x = MX
    for name, w, al in cols:
        text(s, x, y, w, Inches(0.3), name, size=10.5, color=MUTED, align=al, spacing=150)
        x += w + Inches(0.06)
    y += Inches(0.4)
    hline(s, MX, y, W - 2 * MX)
    row_h = Inches(0.7)
    for key, name, en in PRICE_ROWS:
        it = tp.get(key) or {}
        mom = it.get("mom_change")
        x = MX
        cells = [
            [[(name, {"bold": True, "size": 16})], [(en.upper(), {"size": 8.5, "color": MUTED, "spacing": 150})]],
            fmt(it.get("value")), it.get("unit", ""), signed(mom), it.get("month", "-"), c["price_notes"].get(key, ""),
        ]
        for (cname, w, al), val in zip(cols, cells):
            if cname == "品名":
                text(s, x, y + Inches(0.1), w, row_h, val, size=16, line=1.1)
            elif cname == "報價":
                text(s, x, y, w, row_h, val, size=22, kind="mono", align=al, anchor=MSO_ANCHOR.MIDDLE)
            elif cname == "月增":
                col = COPPER if (mom or 0) > 0 else DOWN if (mom or 0) < 0 else MUTED
                text(s, x, y, w, row_h, val, size=14, kind="mono", color=col, align=al, anchor=MSO_ANCHOR.MIDDLE, bold=True)
            elif cname == "短評":
                text(s, x + Inches(0.15), y, w - Inches(0.15), row_h, val, size=12, color=MUTED, anchor=MSO_ANCHOR.MIDDLE, line=1.25)
            else:
                text(s, x, y, w, row_h, val, size=12, color=MUTED, align=al, anchor=MSO_ANCHOR.MIDDLE,
                     kind="mono" if cname == "資料月份" else "body")
            x += w + Inches(0.06)
        y += row_h
        hline(s, MX, y, W - 2 * MX)
    fx = d.get("exchange_rate") or {}
    if fx.get("usd_twd"):
        text(s, MX, y + Inches(0.2), W - 2 * MX, Inches(0.3),
             [[("USD / TWD  ", {"color": MUTED, "spacing": 200, "size": 10}), (f"{fx['usd_twd']}", {"kind": "mono", "color": COPPER, "bold": True}),
               (f"   {fx.get('source', '')}", {"color": MUTED, "size": 10})]], size=14)


def trend(deck: Deck, chart: dict, c: dict):
    s = deck.slide("Price Trend", "價格走勢", c["trend"]["title"])
    months = (chart or {}).get("months") or []
    n = min(24, len(months))
    cd = CategoryChartData()
    cd.categories = [f"{mo[2:4]}/{mo[5:7]}" for mo in months[-n:]]
    added = 0
    for key, label in CHART_SERIES:
        vals = ((chart or {}).get(key) or [])[-n:]
        if len(vals) == n and n:
            cd.add_series(label, [v if isinstance(v, (int, float)) else None for v in vals])
            added += 1
    cw = Inches(8.1)
    if added:
        gf = s.shapes.add_chart(XL_CHART_TYPE.LINE, MX, Inches(1.9), cw, Inches(4.7), cd)
        ch = gf.chart
        ch.has_legend = True
        ch.legend.position = XL_LEGEND_POSITION.TOP
        ch.legend.include_in_layout = False
        ch.legend.font.size = Pt(11)
        ch.legend.font.color.rgb = MUTED
        ch.font.name = LATIN
        for i, ser in enumerate(ch.series):
            ser.format.line.color.rgb = CHART_COLORS[i % len(CHART_COLORS)]
            ser.format.line.width = Pt(2.25)
            ser.smooth = False
            ser.marker.style = XL_MARKER_STYLE.NONE
        va, ca = ch.value_axis, ch.category_axis
        va.has_major_gridlines = True
        va.major_gridlines.format.line.color.rgb = LINE
        va.format.line.fill.background()
        va.tick_labels.font.size = Pt(10)
        va.tick_labels.font.color.rgb = MUTED
        vals_all = [v for key, _ in CHART_SERIES for v in ((chart or {}).get(key) or [])[-n:] if isinstance(v, (int, float))]
        if vals_all:
            va.minimum_scale = max(0, (min(vals_all) * 0.9) // 5000 * 5000)
            va.maximum_scale = -(-max(vals_all) * 1.05 // 5000) * 5000
        va.tick_labels.number_format = '#,##0'
        va.tick_labels.number_format_is_linked = False
        ca.tick_labels.font.size = Pt(9)
        # Schema order: ... lblOffset, tickLblSkip, tickMarkSkip, noMultiLvlLbl, extLst.
        ax = ca._element
        anchor = ax.find(qn("c:noMultiLvlLbl"))
        if anchor is None:
            anchor = ax.find(qn("c:extLst"))
        for tag in ("c:tickLblSkip", "c:tickMarkSkip"):
            el = etree.Element(qn(tag), val="3")
            if anchor is not None:
                anchor.addprevious(el)
            else:
                ax.append(el)
        ca.tick_labels.font.color.rgb = MUTED
        ca.format.line.color.rgb = LINE
        text(s, MX, Inches(6.62), cw, Inches(0.25), "單位：元／公噸 · 資料來源：台灣金屬行情網月均價", size=9, color=MUTED)
    bullets(s, MX + cw + Inches(0.45), Inches(2.0), W - 2 * MX - cw - Inches(0.45), Inches(4.6), c["trend"]["points"], size=14)


def forecast_table(deck: Deck, d: dict, c: dict):
    pf = d.get("price_forecast") or {}
    week = f"{pf.get('week_label', '本週')} {pf.get('week_range', '')}".strip()
    tgt = next(iter((pf.get("targets") or {}).values()), {}).get("target_month", "下一期")
    s = deck.slide("Price Outlook", "盤價走勢預測", c["forecast"]["title"])
    cols = [("品項", Inches(3.0)), (f"{week}行情", Inches(2.9)), (f"{tgt} 月均價", Inches(2.9)), ("月均價機率（漲／平／跌）", Inches(3.13))]
    x, y = MX, Inches(1.85)
    for name, w in cols:
        text(s, x, y, w, Inches(0.3), name, size=10.5, color=MUTED, spacing=100)
        x += w + Inches(0.06)
    y += Inches(0.4)
    hline(s, MX, y, W - 2 * MX)
    row_h = Inches(0.78)
    for key, name, en in ITEMS:
        f = (pf.get("items") or {}).get(key) or {}
        wk, nm = f.get("week") or {}, f.get("next_month") or {}
        x = MX
        text(s, x, y + Inches(0.14), cols[0][1], row_h, [[(name, {"bold": True})], [(en.upper(), {"size": 8.5, "color": MUTED, "spacing": 150})]], size=15, line=1.1)
        x += cols[0][1] + Inches(0.06)
        for g, (cname, w) in ((wk, cols[1]), (nm, cols[2])):
            badge(s, x, y + Inches(0.21), g.get("direction"))
            text(s, x + Inches(1.2), y, w - Inches(1.2), row_h, g.get("change_estimate", "-"), size=12, kind="mono", color=MUTED, anchor=MSO_ANCHOR.MIDDLE)
            x += w + Inches(0.06)
        sc = nm.get("scenarios") or {}
        probs = [(sc.get(k) or {}).get("prob") for k in ("up", "stable", "down")]
        if all(isinstance(p, (int, float)) for p in probs) and sum(probs) > 0:
            bw = cols[3][1] - Inches(0.1)
            bx = x
            for p, col in zip(probs, (COPPER, SAND, DOWN)):
                seg = int(bw * p / sum(probs))
                if seg > 0:
                    rect(s, bx, y + Inches(0.22), seg, Inches(0.12), col)
                bx += seg
            text(s, x, y + Inches(0.42), bw, Inches(0.3),
                 [[(f"漲 {probs[0]}%", {"color": COPPER}), (f"   平 {probs[1]}%", {"color": MUTED}), (f"   跌 {probs[2]}%", {"color": DOWN})]],
                 size=11, kind="mono")
        y += row_h
        hline(s, MX, y, W - 2 * MX)
    text(s, MX, y + Inches(0.2), W - 2 * MX, Inches(0.6), c["forecast"]["overall"], size=13, color=MUTED, line=1.4)


def forecast_reasons(deck: Deck, d: dict, c: dict):
    pf = d.get("price_forecast") or {}
    s = deck.slide("Reasoning", "預測依據", "各品項為什麼這樣預估")
    y = Inches(1.9)
    row_h = Inches(0.9)
    for key, name, _ in ITEMS:
        f = (pf.get("items") or {}).get(key) or {}
        notes = (c["forecast"].get("items") or {}).get(key) or {}
        text(s, MX, y, Inches(2.7), row_h, name, size=15, bold=True)
        badge(s, MX + Inches(2.75), y, (f.get("week") or {}).get("direction"), w=Inches(0.95), size=10)
        text(s, MX + Inches(3.8), y + Inches(0.02), Inches(3.75), row_h, [[("本週  ", {"color": COPPER, "bold": True, "size": 10.5}), (notes.get("week", ""), {})]],
             size=12, color=INK, line=1.3)
        badge(s, MX + Inches(7.7), y, (f.get("next_month") or {}).get("direction"), w=Inches(0.95), size=10)
        text(s, MX + Inches(8.75), y + Inches(0.02), W - 2 * MX - Inches(8.75), row_h,
             [[("月均價  ", {"color": COPPER, "bold": True, "size": 10.5}), (notes.get("month", ""), {})]], size=12, color=INK, line=1.3)
        y += row_h
        hline(s, MX, y - Inches(0.12), W - 2 * MX)
    text(s, MX, y + Inches(0.02), W - 2 * MX, Inches(0.3), "機率與區間請見前頁。", size=10.5, color=MUTED)


def construction_movers(m: dict) -> list[dict]:
    ok = lambda it: (not it.get("stale") and isinstance(it.get("change_pct"), (int, float))
                     and isinstance(it.get("value"), (int, float)))
    items = [it for it in (m or {}).get("items", []) if ok(it)]
    cci = sorted((it for it in items if it.get("group") in ("cci_national", "cci_local")),
                 key=lambda it: abs(it["change_pct"]), reverse=True)[:4]
    raw = sorted((it for it in items if it.get("group") == "commodities"
                  and any(w in it.get("name", "") for w in ("鐵礦", "煤", "銅", "鋁", "鋅"))),
                 key=lambda it: abs(it["change_pct"]), reverse=True)[:3]
    return cci + raw


def materials_slide(deck: Deck, m: dict, c: dict):
    s = deck.slide("Construction Materials", "營建材料行情", c["materials"]["title"])
    rows = construction_movers(m)
    tw = Inches(6.9)
    y = Inches(1.85)
    text(s, MX, y, tw, Inches(0.3), [[("營造物價指數與原物料", {"bold": True, "color": INK}), ("   各取較前期變動最大者", {"color": MUTED, "size": 10})]], size=12)
    y += Inches(0.42)
    hline(s, MX, y, tw)
    for it in rows:
        pct = it["change_pct"]
        col = COPPER if pct > 0 else DOWN if pct < 0 else MUTED
        text(s, MX, y, Inches(3.2), Inches(0.55), it["name"] + (f"（{it['region']}）" if it.get("region") else ""), size=13, anchor=MSO_ANCHOR.MIDDLE)
        text(s, MX + Inches(3.2), y, Inches(1.7), Inches(0.55), [[(fmt(it["value"]), {"kind": "mono", "size": 14}), (f" {it.get('unit', '')}", {"size": 9, "color": MUTED})]],
             size=14, align=PP_ALIGN.RIGHT, anchor=MSO_ANCHOR.MIDDLE)
        text(s, MX + Inches(4.95), y, Inches(1.0), Inches(0.55), f"{pct:+.2f}%", size=13, kind="mono", color=col, bold=True, align=PP_ALIGN.RIGHT, anchor=MSO_ANCHOR.MIDDLE)
        text(s, MX + Inches(6.0), y, Inches(0.9), Inches(0.55), it.get("period", ""), size=10, kind="mono", color=MUTED, align=PP_ALIGN.RIGHT, anchor=MSO_ANCHOR.MIDDLE)
        y += Inches(0.55)
        hline(s, MX, y, tw)
    bullets(s, MX + tw + Inches(0.5), Inches(1.95), W - 2 * MX - tw - Inches(0.5), Inches(4.6), c["materials"]["points"], size=14)


def international(deck: Deck, d: dict, m: dict, c: dict):
    s = deck.slide("Global Markets", "國際市場與匯率", c["international"]["title"])
    picks = []
    fx = d.get("exchange_rate") or {}
    if fx.get("usd_twd"):
        picks.append(("美元兌新台幣", fmt(fx["usd_twd"]), "", None))
    pool = [it for it in (m or {}).get("items", [])
            if it.get("group") in ("commodities", "intl_steel") and isinstance(it.get("value"), (int, float))]
    for word in ("鐵礦", "熱軋", "鋼筋", "煤"):
        hit = next((it for it in pool if word in it.get("name", "")), None)
        if hit and len(picks) < 4:
            picks.append((hit["name"], fmt(hit["value"]), hit.get("unit", ""), hit.get("change_pct")))
    cw = (W - 2 * MX - Inches(0.3) * 3) / 4
    for i, (name, val, unit, pct) in enumerate(picks[:4]):
        x = MX + (cw + Inches(0.3)) * i
        rect(s, x, Inches(1.95), cw, Inches(1.55), PAPER, LINE)
        text(s, x + Inches(0.25), Inches(2.1), cw - Inches(0.5), Inches(0.5), name, size=11.5, color=MUTED, line=1.15)
        text(s, x + Inches(0.25), Inches(2.6), cw - Inches(0.5), Inches(0.5), val, size=26, kind="mono")
        sub = unit + (f"  {pct:+.2f}%" if isinstance(pct, (int, float)) else "")
        text(s, x + Inches(0.25), Inches(3.12), cw - Inches(0.5), Inches(0.3), sub, size=10, color=COPPER if (pct or 0) > 0 else DOWN if (pct or 0) < 0 else MUTED, kind="mono")
    bullets(s, MX, Inches(3.9), W - 2 * MX, Inches(2.6), c["international"]["points"], size=15)


def news(deck: Deck, c: dict):
    s = deck.slide("News Analysis", "新聞分析", "今天值得注意的新聞")
    items = c["news"][:5]
    row_h = (H - Inches(1.95) - Inches(0.85)) / max(len(items), 1)
    y = Inches(1.9)
    for i, n in enumerate(items):
        text(s, MX, y + Inches(0.05), Inches(0.7), Inches(0.5), f"{i + 1:02d}", size=20, color=COPPER, kind="mono")
        text(s, MX + Inches(0.85), y + Inches(0.02), Inches(8.2), Inches(0.45), n["headline"], size=17, bold=True)
        text(s, W - MX - Inches(3.0), y + Inches(0.08), Inches(3.0), Inches(0.3), f"{n.get('source', '')}  {n.get('date', '')}".strip(),
             size=10, color=MUTED, align=PP_ALIGN.RIGHT, kind="mono")
        text(s, MX + Inches(0.85), y + Inches(0.5), W - 2 * MX - Inches(0.85), row_h - Inches(0.55), n["why"], size=13, color=MUTED, line=1.35)
        y += row_h
        if i < len(items) - 1:
            hline(s, MX + Inches(0.85), y - Inches(0.08), W - 2 * MX - Inches(0.85))


def risks(deck: Deck, c: dict):
    s = deck.slide("Risks & Watchlist", "風險與觀察", "可能讓預測失準的事")
    half = (W - 2 * MX - Inches(0.4)) / 2
    text(s, MX, Inches(1.85), half, Inches(0.3), "風險", size=11, color=DOWN, bold=True, spacing=200)
    text(s, MX + half + Inches(0.4), Inches(1.85), half, Inches(0.3), "接下來觀察", size=11, color=COPPER, bold=True, spacing=200)
    y = Inches(2.3)
    row_h = Inches(1.0)
    for r in c["risks"][:4]:
        hline(s, MX, y, W - 2 * MX)
        rect(s, MX, y + Inches(0.18), Inches(0.06), Inches(0.6), DOWN)
        text(s, MX + Inches(0.25), y + Inches(0.15), half - Inches(0.3), row_h - Inches(0.2), r["risk"], size=14, line=1.4)
        rect(s, MX + half + Inches(0.4), y + Inches(0.18), Inches(0.06), Inches(0.6), COPPER)
        text(s, MX + half + Inches(0.65), y + Inches(0.15), half - Inches(0.3), row_h - Inches(0.2), r["watch"], size=14, color=MUTED, line=1.4)
        y += row_h
    hline(s, MX, y, W - 2 * MX)


def actions(deck: Deck, acc: dict, c: dict):
    s = deck.slide("What It Means", "對採購與成本的意義", c["actions"]["title"])
    bullets(s, MX, Inches(1.95), Inches(8.0), Inches(4.4), c["actions"]["points"], size=16, gap=14)
    x = MX + Inches(8.6)
    w = W - MX - x
    rect(s, x, Inches(1.95), w, Inches(3.0), PAPER, LINE)
    o = (acc or {}).get("overall") or {}
    text(s, x + Inches(0.3), Inches(2.15), w - Inches(0.6), Inches(0.3), "過去預測準確度", size=11, color=MUTED, spacing=150)
    if o.get("total"):
        pct = round(100 * o.get("hits", 0) / o["total"])
        text(s, x + Inches(0.3), Inches(2.55), w - Inches(0.6), Inches(0.9), f"{pct}%", size=48, kind="mono", color=COPPER)
        text(s, x + Inches(0.3), Inches(3.55), w - Inches(0.6), Inches(1.2),
             f"月均價方向預測已驗證 {o['total']} 次，命中 {o.get('hits', 0)} 次。", size=12, color=MUTED, line=1.4)
    else:
        text(s, x + Inches(0.3), Inches(2.6), w - Inches(0.6), Inches(1.0), "累積驗證中", size=20, color=MUTED)
    text(s, MX, Inches(6.35), W - 2 * MX, Inches(0.45),
         "本簡報由 AI 依公開資料自動整理，僅供參考，不構成交易建議。資料來源：台灣金屬行情網、行政院主計總處、各市主計處、世界銀行、臺灣證券交易所、各家新聞媒體。",
         size=9.5, color=MUTED, line=1.3)


def build_deck(d: dict, m: dict, acc: dict, chart: dict, c: dict) -> Presentation:
    deck = Deck(d.get("date", ""))
    cover(deck, d, c)
    key_points(deck, c)
    price_table(deck, d, c)
    trend(deck, chart, c)
    forecast_table(deck, d, c)
    forecast_reasons(deck, d, c)
    materials_slide(deck, m, c)
    international(deck, d, m, c)
    news(deck, c)
    risks(deck, c)
    actions(deck, acc, c)
    return deck.prs


def prune(keep: Path):
    files = sorted(REPORTS.glob("steel-daily-*.pptx"))
    for f in files[:-KEEP_DAYS]:
        if f != keep:
            f.unlink()
            log(f"removed old deck {f.name}")


def main() -> int:
    d = load(DATA / "latest.json")
    if not d or not d.get("price_forecast"):
        log("latest.json has no finished analysis; skipping deck")
        return 0
    m = load(DATA / "materials.json", {})
    acc = load(DATA / "accuracy.json", {})
    chart = load(DATA / "chart-data.json", {})
    source = build_source(d, m, acc)
    log(f"source {len(source)} chars")
    content, model = write_content(source)
    if not content:
        log("could not get slide text that passes the checks; not publishing a deck today")
        return 0
    prs = build_deck(d, m, acc, chart, content)
    REPORTS.mkdir(exist_ok=True)
    date = d.get("date") or datetime.now(TW).strftime("%Y-%m-%d")
    name = f"steel-daily-{date}.pptx"
    path = REPORTS / name
    prs.save(path)
    (DATA / "report.json").write_text(json.dumps({
        "date": date,
        "file": f"reports/{name}",
        "slides": len(prs.slides),
        "size": path.stat().st_size,
        "title": content["cover"]["title"],
        "model": model,
        "generated_at": datetime.now(TW).isoformat(timespec="seconds"),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    prune(path)
    log(f"saved {path.relative_to(ROOT)} ({len(prs.slides)} slides, {path.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
