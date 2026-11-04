#!/usr/bin/env python3
"""
Daily subscriber notifications.

Sends today's analysis once per day:
  - Web push through OneSignal (title: date, text: the journalist-style headline).
  - E-mail newsletter through Buttondown (double opt-in and unsubscribe handled there).
Both are scheduled for the configured delivery time (Taiwan time); when the analysis
finishes after that time they go out immediately. Each channel is skipped while its
App ID / username (notify-config.json) or API key (environment) is missing.
"""
import html
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

TW_TZ = timezone(timedelta(hours=8))
CONFIG_PATH = Path("notify-config.json")
STATE_PATH = Path("data/notify-state.json")
LATEST_PATH = Path("data/latest.json")
MATERIALS_PATH = Path("data/materials.json")
REPORT_PATH = Path("data/report.json")
ONESIGNAL_URL = "https://api.onesignal.com/notifications"
BUTTONDOWN_URL = "https://api.buttondown.com/v1/emails"

FORECAST_NAMES = [
    ("north_scrap_price", "北部廢鋼"),
    ("billet_price", "小鋼胚"),
    ("fengxing_rebar_price", "豐興鋼筋"),
    ("h_beam_price", "東鋼H型鋼"),
    ("csc_wire_rod_price", "中鋼棒線"),
]
HEADLINE_PRICES = [
    ("north_scrap_price", "北部廢鋼大盤收購價"),
    ("billet_price", "小鋼胚中級出廠價"),
    ("fengxing_rebar_price", "豐興鋼筋盤價"),
    ("h_beam_price", "東鋼H型鋼流通價"),
    ("csc_wire_rod_price", "中鋼棒線盤價"),
    ("crude_steel_production", "臺灣粗鋼產量"),
]
DIR_TEXT = {"up": "▲ 看漲", "down": "▼ 看跌", "stable": "◆ 持平"}
MOVER_GROUPS = {"cci_national", "commodities", "intl_steel"}


def log(msg: str):
    print(f"[{datetime.now(TW_TZ).strftime('%H:%M:%S')}] {msg}", flush=True)


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def fmt_num(v) -> str:
    if not isinstance(v, (int, float)):
        return "-"
    if abs(v) >= 1000:
        return f"{v:,.0f}"
    return f"{v:,.2f}".rstrip("0").rstrip(".")


def delivery_at(now: datetime, hhmm: str, target_date: str | None = None) -> datetime | None:
    """Today's delivery time in Taiwan, or None when it has already passed."""
    h, m = map(int, hhmm.split(":"))
    target = now.astimezone(TW_TZ).replace(hour=h, minute=m, second=0, microsecond=0)
    if target_date:
        day = datetime.fromisoformat(target_date).date()
        target = target.replace(year=day.year, month=day.month, day=day.day)
    return target if target > now else None


def headline_of(d: dict) -> tuple[str, str]:
    head = (d.get("headline") or "").strip()
    sub = (d.get("headline_sub") or "").strip()
    if not head:
        summary = (d.get("summary") or "").strip()
        head = re.split(r"[。；;]", summary)[0][:40] if summary else "今日鋼市行情更新"
    return head, sub


# ── Content ────────────────────────────────────────────────

def build_push(d: dict, site_url: str) -> dict:
    head, sub = headline_of(d)
    date = d.get("date", "")
    title = f"鋼市快報 {date[5:].replace('-', '/')}" if date else "鋼市快報"
    # from=push makes the site open today's top-stories briefing on arrival.
    return {"title": title, "text": head, "subtitle": sub, "url": site_url + "?from=push"}


# Email body is HTML: Markdown tables are rendered inconsistently by email apps
# (and break if rows are separated by blank lines). Every element is written on
# its own unindented line so Buttondown's Markdown pass leaves it alone.
INK, MUTED, COPPER, DOWN, LINE = "#2a1f17", "#6d625a", "#7a4a28", "#9c5050", "#d9d6d3"
DIR_COLOR = {"up": COPPER, "down": DOWN, "stable": MUTED}
TD = f"padding:9px 6px;border-bottom:1px solid {LINE};vertical-align:top;"
TH = f"padding:6px;border-bottom:2px solid {INK};text-align:left;font-size:12px;color:{MUTED};font-weight:600;"
SMALL = f"font-size:12px;color:{MUTED};"


def esc(s) -> str:
    return html.escape(str(s if s is not None else ""))


def table(head: list[str], rows: list[list[str]]) -> str:
    out = ['<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
           'style="border-collapse:collapse;width:100%;font-size:14px;line-height:1.45;">',
           "<tr>" + "".join(f'<th style="{TH}">{esc(h)}</th>' for h in head) + "</tr>"]
    out += ["<tr>" + "".join(f'<td style="{TD}">{c}</td>' for c in r) + "</tr>" for r in rows]
    out.append("</table>")
    return "\n".join(out)


def report_paths(report: dict | None, date: str) -> tuple[str, str] | None:
    if not report or report.get('date') != date or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', date or ''):
        return None
    stem = f'reports/steel-daily-{date}'
    pptx, pdf = report.get('file'), report.get('pdf_file')
    return (pptx, pdf) if pptx == stem + '.pptx' and pdf == stem + '.pdf' else None


def local_report_ready(report: dict | None, date: str) -> bool:
    paths = report_paths(report, date)
    if not paths:
        return False
    hashes = ((report.get('content') or {}).get('sha256'), report.get('pdf_sha256'))
    try:
        return all(expected and hashlib.sha256(Path(path).read_bytes()).hexdigest() == expected
                   for path, expected in zip(paths, hashes))
    except OSError:
        return False


def build_email(d: dict, materials: dict, site_url: str, report: dict | None = None) -> dict:
    head, sub = headline_of(d)
    date = d.get("date", "")
    h2 = f'<h2 style="font-size:19px;margin:26px 0 10px;color:{INK};">'
    parts = [f'<h1 style="font-size:22px;line-height:1.4;margin:0 0 6px;color:{INK};">{esc(head)}</h1>']
    if sub:
        parts.append(f'<p style="margin:0 0 6px;font-size:15px;color:{MUTED};">{esc(sub)}</p>')
    parts.append(f'<p style="margin:0;{SMALL}">{esc(date)} · 台灣鋼鐵市場每日快報</p>')
    if d.get("summary"):
        parts += [f"{h2}今日重點</h2>", f'<p style="margin:0;font-size:15px;line-height:1.7;">{esc(d["summary"])}</p>']
    paths = report_paths(report, date)
    if paths:
        buttons = []
        for label, path in zip(('PPTX 簡報', 'PDF 文件'), paths):
            url = site_url.rstrip('/') + '/' + path
            buttons.append(f'<a href="{esc(url)}" style="display:inline-block;margin:0 8px 8px 0;padding:10px 18px;'
                           f'background:{INK};color:#ffffff;border-radius:999px;text-decoration:none;font-weight:600;font-size:14px;">'
                           f'下載 {label}</a>')
        parts.append(f'<p style="margin:18px 0 0;">今日電子報（{esc(report.get("slides", ""))} 頁）</p>'
                     + '<p style="margin:8px 0 0;">' + ''.join(buttons) + '</p>')

    pf = d.get("price_forecast") or {}
    items = pf.get("items") or {}
    if items:
        week = pf.get("week_label", "本週")
        month = next(iter((pf.get("targets") or {}).values()), {}).get("target_month", "下一期")

        def cell(g):
            g = g or {}
            color = DIR_COLOR.get(g.get("direction"), MUTED)
            return (f'<span style="color:{color};font-weight:700;">{esc(DIR_TEXT.get(g.get("direction"), "-"))}</span>'
                    f'<br><span style="{SMALL}">{esc(g.get("change_estimate", ""))}</span>')
        rows = [[f"<b>{esc(name)}</b>", cell((items.get(key) or {}).get("week")), cell((items.get(key) or {}).get("next_month"))]
                for key, name in FORECAST_NAMES]
        parts += [f"{h2}盤價預測</h2>", table(["品項", f"{week}行情", f"{month} 月均價"], rows)]

    tp = d.get("taiwan_prices") or {}
    rows = []
    for key, name in HEADLINE_PRICES:
        it = tp.get(key) or {}
        if not isinstance(it, dict) or it.get("value") is None:
            continue
        mom = it.get("mom_change")
        mom_s = "-" if mom is None else (f"+{fmt_num(mom)}" if mom > 0 else fmt_num(mom))
        color = COPPER if (mom or 0) > 0 else DOWN if (mom or 0) < 0 else MUTED
        rows.append([f"<b>{esc(name)}</b>",
                     f'{esc(fmt_num(it["value"]))} <span style="{SMALL}">{esc(it.get("unit", ""))}</span>'
                     f'<br><span style="{SMALL}">{esc(it.get("month", ""))}</span>',
                     f'<span style="color:{color};font-weight:700;">{esc(mom_s)}</span>'])
    fx = d.get("exchange_rate") or {}
    if fx.get("usd_twd"):
        rows.append(["<b>美元兌新台幣</b>", f'{esc(fx["usd_twd"])}<br><span style="{SMALL}">{esc(date)}</span>', "-"])
    if rows:
        parts += [f"{h2}最新報價</h2>", table(["品項", "報價", "較前期"], rows)]

    movers = [it for it in materials.get("items", [])
              if it.get("group") in MOVER_GROUPS and not it.get("stale") and isinstance(it.get("change_pct"), (int, float))]
    movers = sorted(movers, key=lambda it: abs(it["change_pct"]), reverse=True)[:6]
    if movers:
        rows = []
        for it in movers:
            color = COPPER if it["change_pct"] > 0 else DOWN if it["change_pct"] < 0 else MUTED
            rows.append([esc(it["name"]),
                         f'{esc(fmt_num(it["value"]))} <span style="{SMALL}">{esc(it.get("unit", ""))}</span>'
                         f'<br><span style="{SMALL}">{esc(it.get("period", ""))}</span>',
                         f'<span style="color:{color};font-weight:700;">{it["change_pct"]:+.2f}%</span>'])
        parts += [f"{h2}營建材料與原物料變動焦點</h2>", table(["品項", "最新", "較前期"], rows)]

    news = [n for n in d.get("news_sources", []) if str(n.get("url", "")).startswith("http") and n.get("title")][:8]
    if news:
        parts.append(f"{h2}新聞標題</h2>")
        for n in news:
            meta = "，".join(x for x in (n.get("source"), n.get("date")) if x)
            parts.append(f'<p style="margin:0 0 10px;font-size:14px;line-height:1.5;">'
                         f'<a href="{esc(n["url"])}" style="color:{COPPER};">{esc(n["title"])}</a>'
                         + (f'<br><span style="{SMALL}">{esc(meta)}</span>' if meta else "") + "</p>")

    parts += [f'<p style="margin:24px 0 0;"><a href="{esc(site_url)}" style="color:{COPPER};font-weight:600;">查看完整分析與 97 項營建材料行情 →</a></p>',
              f'<hr style="border:none;border-top:1px solid {LINE};margin:20px 0 10px;">',
              f'<p style="margin:0;{SMALL}">本快報由 AI 依公開資料自動分析產生，僅供參考，不構成交易建議。</p>']
    return {"subject": f"【鋼市快報 {date[5:].replace('-', '/')}】{head}", "body": "\n".join(parts)}


# ── Senders ────────────────────────────────────────────────

def send_push(app_id: str, key: str, push: dict, at: datetime | None) -> dict:
    body = {
        "app_id": app_id,
        "target_channel": "push",
        "included_segments": ["Total Subscriptions"],
        "headings": {"en": push["title"], "zh-Hant": push["title"]},
        "contents": {"en": push["text"], "zh-Hant": push["text"]},
        "url": push["url"],
        "chrome_web_icon": push["url"].split("?")[0] + "assets/icon-192.png",
    }
    if push.get("subtitle"):
        body["subtitle"] = {"en": push["subtitle"], "zh-Hant": push["subtitle"]}
    if at:
        body["send_after"] = at.strftime("%Y-%m-%d %H:%M:%S GMT+0800")
    r = requests.post(ONESIGNAL_URL, json=body, timeout=30,
                      headers={"Authorization": f"Key {key}", "Content-Type": "application/json"})
    log(f"OneSignal HTTP {r.status_code}: {r.text[:300]}")
    r.raise_for_status()
    j = r.json()
    if j.get("errors"):
        raise RuntimeError(f"OneSignal errors: {j['errors']}")
    return {"id": j.get("id"), "scheduled": at.isoformat() if at else None}


def send_email(key: str, email: dict, at: datetime | None) -> dict:
    body = {"subject": email["subject"], "body": email["body"], "email_type": "public"}
    if at:
        body.update(status="scheduled", publish_date=at.isoformat())
    else:
        body["status"] = "about_to_send"
    r = requests.post(BUTTONDOWN_URL, json=body, timeout=30, headers={
        "Authorization": f"Token {key}",
        "X-Buttondown-Live-Dangerously": "true",
    })
    log(f"Buttondown HTTP {r.status_code}: {r.text[:300]}")
    r.raise_for_status()
    return {"id": r.json().get("id"), "scheduled": at.isoformat() if at else None}


def main(now: datetime | None = None) -> int:
    now = now or datetime.now(TW_TZ)
    today = os.environ.get("RESEARCH_DATE") or now.strftime("%Y-%m-%d")
    cfg = load_json(CONFIG_PATH, {})
    d = load_json(LATEST_PATH, {})
    if d.get("date") != today:
        log(f"latest.json is for {d.get('date')}, not {today}; nothing sent")
        return 0
    state = load_json(STATE_PATH, {})
    site_url = cfg.get("site_url", "https://lijingchiu.github.io/SteelWeb/")
    at = delivery_at(now, cfg.get("delivery_time", "07:00"), today)
    log(f"Delivery: {'scheduled ' + at.isoformat() if at else 'immediate'}")

    channels = {
        "push": (cfg.get("onesignal_app_id"), os.environ.get("ONESIGNAL_REST_API_KEY")),
        "email": (cfg.get("buttondown_username"), os.environ.get("BUTTONDOWN_API_KEY")),
    }
    failed = False
    for ch, (public_id, key) in channels.items():
        prev = state.get(ch) or {}
        if prev.get("date") == today:
            log(f"{ch}: already sent today ({prev.get('id')}); skipping")
            continue
        if not public_id or not key:
            log(f"{ch}: not configured; skipping")
            continue
        try:
            if ch == "push":
                result = send_push(public_id, key, build_push(d, site_url), at)
            else:
                report = load_json(REPORT_PATH, {})
                if not local_report_ready(report, today):
                    raise RuntimeError('今日 PPTX 或 PDF 尚未完成或檔案校驗不符；暫不寄出郵件。')
                if os.environ.get('REPORT_PUBLIC_READY') != 'true':
                    raise RuntimeError('兩種電子報尚未確認公開可下載；暫不寄出郵件。')
                result = send_email(key, build_email(d, load_json(MATERIALS_PATH, {}), site_url, report), at)
            state[ch] = {"date": today, "sent_at": now.isoformat(), **result}
            log(f"{ch}: OK {result}")
        except Exception as e:
            failed = True
            log(f"{ch}: FAILED {e}")
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
