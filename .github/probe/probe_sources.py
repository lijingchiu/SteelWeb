"""Probe round 3."""
import io, json, os, re
import requests
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
      "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8"}
S = requests.Session(); S.headers.update(UA)
def get(url, timeout=30, **kw):
    try: return S.get(url, timeout=timeout, **kw)
    except Exception as e: print(f"  ERR {url}: {str(e)[:160]}"); return None
def sec(n): print("\n" + "=" * 18 + f" {n} " + "=" * 18, flush=True)

sec("OpenAI")
key = os.environ.get("OPENAI_API_KEY", "")
print("OPENAI_API_KEY present:", bool(key), "len", len(key))
print("OPENROUTER_API_KEY present:", bool(os.environ.get("OPENROUTER_API_KEY")))
if key:
    r = requests.get("https://api.openai.com/v1/models", headers={"Authorization": f"Bearer {key}"}, timeout=30)
    print("models HTTP", r.status_code)
    if r.ok:
        ids = sorted(m["id"] for m in r.json().get("data", []))
        print("gpt-6* models:", [i for i in ids if i.startswith("gpt-6")])
        print("has gpt-6.1-terra:", "gpt-6.1-terra" in ids)
    else:
        print(r.text[:300])
    body = {"model": "gpt-6.1-terra", "input": "用一句話回答：今天台灣豐興鋼筋盤價的最新消息是什麼？請附來源網址。",
            "tools": [{"type": "web_search"}], "reasoning": {"effort": "medium"}, "max_output_tokens": 2000}
    r = requests.post("https://api.openai.com/v1/responses", headers={"Authorization": f"Bearer {key}"}, json=body, timeout=180)
    print("responses HTTP", r.status_code)
    try:
        j = r.json()
        print("keys:", list(j.keys())[:20], "status:", j.get("status"), "usage:", j.get("usage"))
        for item in j.get("output", []):
            print("  output item type:", item.get("type"))
            if item.get("type") == "message":
                for c in item.get("content", []):
                    print("   text:", (c.get("text") or "")[:600])
                    print("   annotations:", [a.get("url") for a in c.get("annotations", [])][:5])
        if not r.ok: print(r.text[:600])
    except Exception as e:
        print("parse fail", e, r.text[:300])

sec("PCC retry + NCHC CKAN mirror")
for u in ["http://pcic.pcc.gov.tw/pwc-web/api/service/opendata-file/document/鋼筋.csv",
          "https://pcic.pcc.gov.tw/pwc-web/api/service/opendata-file/document/鋼筋.csv"]:
    r = get(u, timeout=(60, 60)); print(getattr(r, "status_code", None), u)
for ds in ["best_wish6820", "best_wish7374"]:
    r = get(f"https://scidm.nchc.org.tw/api/3/action/package_show?id={ds}")
    if r is None: continue
    try:
        res = r.json()["result"]
        print(ds, "modified", res.get("metadata_modified"))
        for rs in res.get("resources", [])[:4]:
            print("   res:", rs.get("format"), rs.get("url"), rs.get("last_modified"))
            if rs.get("url"):
                rr = get(rs["url"]); print("     ->", getattr(rr, "status_code", None), (rr.content[:300] if rr is not None else b""))
    except Exception as e:
        print(ds, "fail", e, r.text[:200])

sec("DGBAS CCI XML items")
r = get("https://ws.dgbas.gov.tw/001/Upload/461/relfile/11525/230553/pr0501a1m.xml", 60)
if r is not None:
    r.encoding = "utf-8"
    obs = re.findall(r"<Item>(.*?)</Item><TIME_PERIOD>(.*?)</TIME_PERIOD>.*?<TYPE>(.*?)</TYPE>\s*<Item_VALUE>(.*?)</Item_VALUE>", r.text, re.S)
    items = {}
    for it, tp, ty, v in obs:
        if ty == "原始值": items[it] = (tp, v)
    print("distinct items:", len(items))
    for it, (tp, v) in list(items.items())[:80]: print(f"   {it} | {tp} = {v}")

sec("Taichung CCI JSON resources")
for rid in ["617a393b-264d-49b5-968b-c198193ad119", "a6b46258-5e30-4268-a89a-c74037dd53ad", "a0a8d65c-5ee1-4a9a-b404-8bc6e7470da7"]:
    r = get(f"https://newdatacenter.taichung.gov.tw/api/v1/no-auth/resource.download?rid={rid}", 60)
    if r is None: continue
    try:
        j = r.json(); print(rid, "rows", len(j))
        last = max(x["資料時間日期"] for x in j)
        print("  latest", last, "項目:", sorted(set(x["項目"] for x in j))[:6])
        for x in [x for x in j if x["資料時間日期"] == last][:40]: print("   ", x["項目"][:30], "|", x["欄位名稱"], "=", x["數值"])
    except Exception as e: print(rid, "fail", e, r.text[:200])

sec("Kaohsiung CSV")
r = get("https://data.kcg.gov.tw/File/directDownload/749dbc28-c2a8-45d1-9fc3-ad47449fcc3a", (60, 60))
if r is not None: print(r.status_code, r.content[:500].decode("utf-8", "replace"))

sec("Google News RSS")
for q in ["豐興 鋼筋 盤價", "豐興 廢鋼 收購價", "中鋼 盤價", "水泥 漲價", "預拌混凝土 價格", "砂石 價格", "東和鋼鐵 H型鋼"]:
    r = get("https://news.google.com/rss/search", params={"q": q + " when:14d", "hl": "zh-TW", "gl": "TW", "ceid": "TW:zh-Hant"})
    if r is None: continue
    items = re.findall(r"<item><title>(.*?)</title>.*?<pubDate>(.*?)</pubDate>", r.text, re.S)
    print(f"[{q}] HTTP {r.status_code} items={len(items)}")
    for t, d in items[:6]: print("    ", d[5:16], "|", t[:90])

sec("metaltrade other series")
for path in [f"ste/domestic/{i}/" for i in list(range(1, 9)) + list(range(15, 31))] + ["ste/international/1/", "ste/international/2/", "ste/international/3/", "ste/"]:
    r = get(f"https://chart.metaltrade.tw/{path}")
    if r is None: continue
    r.encoding = r.apparent_encoding
    t = re.search(r"<title>(.*?)</title>", r.text, re.S); f = re.search(r'<p id="formula">(.*?)</p>', r.text, re.S)
    print(f"{r.status_code} {path} | {(t.group(1).strip() if t else '')[:60]} | {(re.sub('<[^>]+>','',f.group(1)).strip() if f else '')[:90]}")
r = get("https://chart.metaltrade.tw/ste/")
if r is not None:
    links = sorted(set(re.findall(r'href="(/ste/[^"]+)"', r.text)))
    print("ste links:", links[:80])

sec("steelnews price-table pages")
r = get("https://steelnews.com.tw/index.php"); r.encoding = r.apparent_encoding
for name in ["豐興盤價表", "中鋼盤價", "台灣一週鋼市", "原物料走勢表", "LME金屬期貨", "中國鋼市行情表"]:
    m = re.search(r'href="([^"]+)"[^>]*>\s*' + re.escape(name), r.text)
    if not m: print(name, "no link"); continue
    u = m.group(1) if m.group(1).startswith("http") else "https://steelnews.com.tw/" + m.group(1).lstrip("/")
    a = get(u); a.encoding = a.apparent_encoding
    member = "會員限定" in a.text or "請先" in a.text and "登入" in a.text
    nums = re.findall(r"\d{2,3},\d{3}|\d{4,5}", re.sub(r"<[^>]+>", " ", a.text))
    print(f"{name}: {u} HTTP {a.status_code} member_only={member} numbers={nums[:12]}")
