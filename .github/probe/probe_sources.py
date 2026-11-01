"""Probe round 4."""
import ast, base64, json, re
import requests
from bs4 import BeautifulSoup
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
      "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8", "Referer": "https://chart.metaltrade.tw/"}
S = requests.Session(); S.headers.update(UA)
def get(url, timeout=30, **kw):
    try: return S.get(url, timeout=timeout, **kw)
    except Exception as e: print(f"  ERR {url}: {str(e)[:160]}"); return None
def sec(n): print("\n" + "=" * 18 + f" {n} " + "=" * 18, flush=True)

def page_data(html):
    soup = BeautifulSoup(html, "lxml")
    tag = soup.find("script", {"type": "application/json", "id": "page-data"})
    if not tag: return None, soup
    a = json.loads(tag.string or "{}").get("a", "")
    if a.startswith(("b'", 'b"')): a = a[2:-1]
    return ast.literal_eval(base64.b64decode(a).decode("utf-8")), soup

sec("metaltrade series")
for path in [f"ste/domestic/{i}/" for i in range(1, 31)] + [f"ste/international/{i}/" for i in range(1, 12)]:
    r = get(f"https://chart.metaltrade.tw/{path}")
    if r is None or r.status_code != 200: print(path, getattr(r, "status_code", None)); continue
    r.encoding = r.apparent_encoding
    try:
        d, soup = page_data(r.text)
        h = soup.find(["h1", "h2", "h3"]); hs = h.get_text(" ", strip=True)[:50] if h else ""
        f = soup.find(id="formula"); fs = f.get_text(" ", strip=True)[:110] if f else ""
        if d is None: print(path, "| no page-data |", hs, "|", fs); continue
        keys = list(d.keys()) if isinstance(d, dict) else type(d)
        x = d.get("X1", []); y = d.get("Y1", {})
        yname = y.get("name") if isinstance(y, dict) else None
        ys = [k for k in d if k.startswith("Y")]
        extra = {k: (d[k].get("name") if isinstance(d[k], dict) else None) for k in ys}
        print(f"{path} | {hs} | keys={keys[:10]} | names={extra} | X1 {x[:1]}..{x[-1:]} n={len(x)} | last={(y.get('data') or [None])[-1] if isinstance(y, dict) else None} | {fs}")
    except Exception as e:
        print(path, "parse err", e)

sec("TWSE openapi")
r = get("https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL")
if r is not None:
    print("HTTP", r.status_code, "len", len(r.content))
    try:
        rows = r.json(); print("rows", len(rows), "fields", list(rows[0].keys()) if rows else None)
        for x in rows:
            if x.get("Code") in ("2002", "2015", "2006", "2014", "2023", "1101", "1102", "2027", "9958"):
                print("   ", x)
    except Exception as e: print("fail", e, r.text[:200])

sec("OpenRouter models")
r = get("https://openrouter.ai/api/v1/models")
if r is not None:
    ids = sorted(m["id"] for m in r.json().get("data", []))
    print("openai/gpt-6*:", [i for i in ids if i.startswith("openai/gpt-6")])
    for m in r.json()["data"]:
        if m["id"] in ("openai/gpt-6.1-terra", "openai/gpt-6-luna"):
            print("  ", m["id"], m.get("pricing"), m.get("context_length"), (m.get("supported_parameters") or [])[:30])

sec("BOT FX CSV")
r = get("https://rate.bot.com.tw/xrt/flcsv/0/day")
if r is not None:
    for l in r.content.decode("utf-8-sig", "replace").splitlines()[:20]: print("  ", l[:120])
