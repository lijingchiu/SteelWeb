"""Probe round 2: inspect contents of candidate sources."""
import io, json, re
import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
      "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8"}
S = requests.Session(); S.headers.update(UA)

def get(url, timeout=40, **kw):
    try:
        return S.get(url, timeout=timeout, **kw)
    except Exception as e:
        print(f"  ERR {url}: {e}"); return None

def sec(n): print("\n" + "=" * 18 + f" {n} " + "=" * 18, flush=True)

def show_csv(url, n_head=6, n_tail=4):
    r = get(url)
    if r is None: return
    raw = r.content
    for enc in ("utf-8-sig", "big5", "cp950"):
        try: txt = raw.decode(enc); break
        except Exception: continue
    lines = txt.splitlines()
    print(f"HTTP {r.status_code} bytes={len(raw)} lines={len(lines)} enc={enc}")
    for l in lines[:n_head]: print("   H|", l[:220])
    print("   ...")
    for l in lines[-n_tail:]: print("   T|", l[:220])

sec("PCC 大宗資材 CSVs")
base = "https://pcic.pcc.gov.tw/pwc-web/api/service/opendata-file/document/"
for name in ["鋼筋", "H型鋼", "鋼板", "預拌混凝土", "瀝青混凝土", "砂石"]:
    print(f"\n--- {name}")
    show_csv(base + name + ".csv", 8, 6)

sec("data.gov.tw 7374 / 8246 / city CCI metadata")
for i in [7374, 8246, 125690, 145784, 101850, 167838, 101001]:
    r = get(f"https://data.gov.tw/api/v2/rest/dataset/{i}")
    if r is None: continue
    res = r.json().get("result", {})
    print(f"[{i}] {res.get('title')} freq={res.get('accrualPeriodicity') or res.get('updateFrequency')}")
    for d in (res.get("distribution") or [])[:4]:
        u = d.get("resourceDownloadUrl"); fmt = d.get("resourceFormat")
        print(f"   - {fmt} {u}")
    dist = res.get("distribution") or []
    pick = next((d for d in dist if (d.get("resourceFormat") or "").upper() in ("CSV", "JSON")), dist[0] if dist else None)
    if pick:
        u = pick["resourceDownloadUrl"]
        if (pick.get("resourceFormat") or "").upper() == "CSV":
            show_csv(u, 5, 4)
        else:
            rr = get(u)
            if rr is not None: print(f"   HTTP {rr.status_code} {rr.text[:700]!r}")

sec("World Bank monthly xlsx")
try:
    import openpyxl
    r = get("https://thedocs.worldbank.org/en/doc/74e8be41ceb20fa0da750cda2f6b9e4e-0050012026/related/CMO-Historical-Data-Monthly.xlsx", 60)
    wb = openpyxl.load_workbook(io.BytesIO(r.content), read_only=True, data_only=True)
    print("sheets:", wb.sheetnames)
    ws = wb["Monthly Prices"]
    rows = list(ws.iter_rows(values_only=True))
    for i, row in enumerate(rows[:8]): print("  R", i, [c for c in row[:80] if c is not None][:80])
    print("  last rows:")
    for row in rows[-3:]: print("  L", row[:5], "...")
    hdr = rows[4] if len(rows) > 4 else rows[0]
    for kw in ["Iron ore", "Coal", "Copper", "Aluminum", "Zinc", "Nickel", "Crude oil, Brent", "Natural gas", "Steel", "Logs", "Sawnwood", "Urea", "Tin"]:
        idx = [i for i, h in enumerate(hdr) if h and kw.lower() in str(h).lower()]
        for i in idx: print(f"   col {i}: {hdr[i]!r} unit={rows[5][i] if len(rows)>5 else None} last={rows[-1][i]} ({rows[-1][0]})")
except Exception as e:
    print("WB parse failed:", repr(e))

sec("FRED retry (60s)")
for sid in ["DCOILBRENTEU", "WPU1017", "WPU133301"]:
    r = get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}", 60)
    if r is not None: print(sid, r.status_code, r.text.strip().splitlines()[-2:])

sec("stooq daily")
for s in ["hg.f", "cl.f", "cb.f", "ng.f", "ali.f", "usdtwd"]:
    r = get(f"https://stooq.com/q/d/l/?s={s}&i=d")
    if r is not None: print(s, r.status_code, r.text.strip().splitlines()[:1], r.text.strip().splitlines()[-2:])

sec("steelnews index.php")
r = get("https://steelnews.com.tw/index.php")
if r is not None:
    r.encoding = r.apparent_encoding
    print("HTTP", r.status_code, "len", len(r.text))
    arts = re.findall(r'href="([^"]*content\?id=\d+)"[^>]*>\s*([^<]{6,80})<', r.text)
    print("links:", len(arts))
    for h, t in arts[:30]: print("   ", h, "|", t.strip())
    tgt = next(((h, t) for h, t in arts if "豐興" in t or "廢鋼" in t), arts[0] if arts else None)
    if tgt:
        u = tgt[0] if tgt[0].startswith("http") else "https://steelnews.com.tw/" + tgt[0].lstrip("/")
        a = get(u); a.encoding = a.apparent_encoding
        t = re.sub(r"<script.*?</script>|<style.*?</style>", "", a.text, flags=re.S)
        t = re.sub(r"<[^>]+>", "\n", t); t = re.sub(r"\n\s*\n+", "\n", t)
        i = t.find(tgt[1].strip()[:8]); print("ARTICLE", u); print(t[max(0, i):max(0, i) + 2000])
