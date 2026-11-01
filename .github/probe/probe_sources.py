"""One-off probe: test candidate price sources from a GitHub runner (full internet)."""
import json, re, sys, time
import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
      "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8"}
S = requests.Session(); S.headers.update(UA)
OUT = {}

def get(url, **kw):
    try:
        r = S.get(url, timeout=30, **kw)
        return r
    except Exception as e:
        print(f"  ERR {url}: {e}")
        return None

def section(name):
    print("\n" + "=" * 20 + f" {name} " + "=" * 20, flush=True)

# 1. data.gov.tw dataset metadata for candidate IDs
section("data.gov.tw dataset metadata")
ids = list(range(6575, 6583)) + list(range(6815, 6823)) + [21027, 21028, 21029, 13633]
for i in ids:
    r = get(f"https://data.gov.tw/api/v2/rest/dataset/{i}")
    if r is None: continue
    try:
        j = r.json(); res = j.get("result", j)
        title = res.get("title"); org = res.get("publisher") or res.get("organization")
        freq = res.get("accrualPeriodicity") or res.get("updateFrequency")
        print(f"[{i}] HTTP {r.status_code} | {title} | {org} | freq={freq} | modified={res.get('modified')}")
        for d in (res.get("distribution") or [])[:6]:
            print(f"     - {d.get('resourceFormat')} {d.get('resourceDescription','')[:40]} -> {d.get('resourceDownloadUrl')}")
        OUT[f"dgt_{i}"] = res
    except Exception as e:
        print(f"[{i}] HTTP {r.status_code} non-json: {r.text[:200]!r}")

# 2. data.gov.tw keyword search (frontend API)
section("data.gov.tw keyword search")
for kw in ["大宗資材", "營造工程物價指數", "砂石價格", "預拌混凝土", "水泥價格", "營建物價", "鋼筋價格"]:
    body = {"bool": [{"fulltext": {"value": kw}}], "filter": [], "page_num": 1, "page_limit": 15, "tids": [], "sort": "_score_desc"}
    try:
        r = S.post("https://data.gov.tw/api/front/dataset/list", json=body, timeout=30)
        j = r.json()
        items = (j.get("payload") or {}).get("search_result") or j.get("result") or []
        print(f"[{kw}] HTTP {r.status_code}, {len(items)} hits")
        for it in items[:15]:
            print(f"     {it.get('nid') or it.get('identifier')} | {it.get('title')} | {it.get('agency_name') or it.get('publisher')} | {it.get('update_freq') or ''}")
    except Exception as e:
        print(f"[{kw}] search failed: {e}; body={getattr(r,'text','')[:200]!r}")

# 3. FRED CSV (no key)
section("FRED fredgraph.csv")
fred = ["DCOILBRENTEU","DCOILWTICO","DHHNGSP","PIORECRUSDM","PCOPPUSDM","PALUMUSDM","PZINCUSDM","PNICKUSDM","PCOALAUUSDM",
        "WPU101","WPU1017","WPU133301","PCU327310327310","WPU1321","WPU0811","WPU13","WPU1073","WPU05810306","PCU331110331110","WPU101704"]
for sid in fred:
    r = get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}")
    if r is None: continue
    lines = [l for l in r.text.strip().splitlines() if l]
    t = get(f"https://fred.stlouisfed.org/series/{sid}")
    title = ""
    if t is not None:
        m = re.search(r"<title>(.*?)</title>", t.text, re.S); title = (m.group(1).strip()[:90] if m else "")
    print(f"[{sid}] HTTP {r.status_code} rows={len(lines)} last={lines[-2:] if len(lines)>1 else lines} | {title}")

# 4. World Bank commodity markets page -> monthly xlsx link
section("World Bank Pink Sheet")
r = get("https://www.worldbank.org/en/research/commodity-markets")
if r is not None:
    links = sorted(set(re.findall(r'https?://[^"\']+?CMO-Historical-Data-Monthly\.xlsx', r.text)))
    print("landing HTTP", r.status_code, "xlsx links:", links[:5])
    if links:
        x = get(links[0]); print("xlsx HTTP", x.status_code if x is not None else None, "bytes", len(x.content) if x is not None else 0)

# 5. steelnews: list page + search for 豐興 weekly price articles
section("steelnews")
r = get("https://steelnews.com.tw/")
if r is not None:
    r.encoding = r.apparent_encoding
    print("home HTTP", r.status_code, "len", len(r.text))
    arts = re.findall(r'href="([^"]*news/content\?id=\d+)"[^>]*>([^<]{6,80})<', r.text)
    print("article links found:", len(arts))
    for href, title in arts[:40]:
        print("   ", href, "|", title.strip())
    target = next(((h, t) for h, t in arts if any(k in t for k in ("豐興", "廢鋼", "鋼筋", "盤價"))), arts[0] if arts else None)
    if target:
        u = target[0] if target[0].startswith("http") else "https://steelnews.com.tw/" + target[0].lstrip("/")
        a = get(u)
        if a is not None:
            a.encoding = a.apparent_encoding
            txt = re.sub(r"<script.*?</script>|<style.*?</style>", "", a.text, flags=re.S)
            txt = re.sub(r"<[^>]+>", "\n", txt); txt = re.sub(r"\n\s*\n+", "\n", txt)
            print("ARTICLE", u, "len", len(txt)); print(txt[:2500])
for q in ["豐興", "鋼筋", "廢鋼"]:
    r = get(f"https://steelnews.com.tw/news/search?keyword={q}")
    print(f"search {q}: HTTP {getattr(r,'status_code',None)} len {len(r.text) if r is not None else 0}")

# 6. Other candidates
section("misc")
for u in ["https://rate.bot.com.tw/xrt/flcsv/0/day",
          "https://www.cnyes.com/futures/basicmetal.aspx",
          "https://stooq.com/q/d/l/?s=hg.f&i=d",
          "https://www.dgbas.gov.tw/",
          "https://nstatdb.dgbas.gov.tw/dgbasall/webMain.aspx?k=dgmain",
          "https://www.gsmma.gov.tw/",
          "https://pcces.pcc.gov.tw/",
          "https://www.pcc.gov.tw/"]:
    r = get(u); print(f"{getattr(r,'status_code',None)}  len={len(r.content) if r is not None else 0}  {u}")

json.dump(OUT, open("probe_out.json", "w"), ensure_ascii=False, indent=1)
