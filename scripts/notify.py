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


def delivery_at(now: datetime, hhmm: str) -> datetime | None:
    """Today's delivery time in Taiwan, or None when it has already passed."""
    h, m = map(int, hhmm.split(":"))
    target = now.astimezone(TW_TZ).replace(hour=h, minute=m, second=0, microsecond=0)
    return target if target > now + timedelta(minutes=2) else None


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


def build_email(d: dict, materials: dict, site_url: str, report: dict | None = None) -> dict:
    head, sub = headline_of(d)
    date = d.get("date", "")
    lines = [f"# {head}"]
    if sub:
        lines.append(f"*{sub}*")
    lines.append(f"{date} · 台灣鋼鐵市場每日快報")
    if d.get("summary"):
        lines += ["## 今日重點", d["summary"]]
    if report and report.get("date") == date and report.get("file"):
        deck_url = site_url.rstrip("/") + "/" + report["file"]
        lines.append(f"[下載今日電子報簡報（PPTX，{report.get('slides', '')} 頁）→]({deck_url})")

    pf = d.get("price_forecast") or {}
    items = pf.get("items") or {}
    if items:
        week = pf.get("week_label", "本週")
        month = next(iter((pf.get("targets") or {}).values()), {}).get("target_month", "下一期")
        lines += ["## 盤價預測", f"| 品項 | {week}行情 | {month} 月均價 |", "|---|---|---|"]
        for key, name in FORECAST_NAMES:
            f = items.get(key) or {}
            cell = lambda g: f"{DIR_TEXT.get((g or {}).get('direction'), '-')} {(g or {}).get('change_estimate', '')}".strip()
            lines.append(f"| {name} | {cell(f.get('week'))} | {cell(f.get('next_month'))} |")

    tp = d.get("taiwan_prices") or {}
    lines += ["## 最新報價", "| 品項 | 報價 | 資料期間 | 較前期 |", "|---|---|---|---|"]
    for key, name in HEADLINE_PRICES:
        it = tp.get(key) or {}
        if it.get("value") is None:
            continue
        mom = it.get("mom_change")
        mom_s = "-" if mom is None else (f"+{fmt_num(mom)}" if mom > 0 else fmt_num(mom))
        lines.append(f"| {name} | {fmt_num(it['value'])} {it.get('unit', '')} | {it.get('month', '')} | {mom_s} |")
    fx = d.get("exchange_rate") or {}
    if fx.get("usd_twd"):
        lines.append(f"| 美元兌新台幣 | {fx['usd_twd']} | {date} | - |")

    movers = [it for it in materials.get("items", [])
              if it.get("group") in MOVER_GROUPS and not it.get("stale") and isinstance(it.get("change_pct"), (int, float))]
    movers = sorted(movers, key=lambda it: abs(it["change_pct"]), reverse=True)[:6]
    if movers:
        lines += ["## 營建材料與原物料變動焦點"]
        for it in movers:
            lines.append(f"- {it['name']}：{fmt_num(it['value'])} {it['unit']}（{it['period']}，{it['change_pct']:+.2f}%）")

    news = [n for n in d.get("news_sources", []) if str(n.get("url", "")).startswith("http") and n.get("title")][:8]
    if news:
        lines += ["## 新聞標題"]
        for n in news:
            meta = "，".join(x for x in (n.get("source"), n.get("date")) if x)
            lines.append(f"- [{n['title']}]({n['url']})" + (f"（{meta}）" if meta else ""))

    lines += [f"[查看完整分析與 97 項營建材料行情 →]({site_url})",
              "---",
              "本快報由 AI 依公開資料自動分析產生，僅供參考，不構成交易建議。"]
    return {"subject": f"【鋼市快報 {date[5:].replace('-', '/')}】{head}", "body": "\n\n".join(lines)}


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
    today = now.strftime("%Y-%m-%d")
    cfg = load_json(CONFIG_PATH, {})
    d = load_json(LATEST_PATH, {})
    if d.get("date") != today:
        log(f"latest.json is for {d.get('date')}, not {today}; nothing sent")
        return 0
    state = load_json(STATE_PATH, {})
    site_url = cfg.get("site_url", "https://lijingchiu.github.io/SteelWeb/")
    at = delivery_at(now, cfg.get("delivery_time", "08:00"))
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
                result = send_email(key, build_email(d, load_json(MATERIALS_PATH, {}), site_url,
                                                     load_json(REPORT_PATH, {})), at)
            state[ch] = {"date": today, "sent_at": now.isoformat(), **result}
            log(f"{ch}: OK {result}")
        except Exception as e:
            failed = True
            log(f"{ch}: FAILED {e}")
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
