import json
m = json.load(open("data/materials.json"))
print("== sources"); [print(" ", s) for s in m["sources_status"]]
print("== items", len(m["items"]))
for it in m["items"]:
    print(f"  [{it['group']}] {it['name']} | {it['region']} | {it['value']} {it['unit']} | {it['period']} | {it['freq']} | chg%={it['change_pct']} | stale={it['stale']} | hist={len(it['history'])}")
print("== news", len(m["news_feed"]))
for n in m["news_feed"][:8]: print("  ", n["date"], n["source"], n["title"])
c = json.load(open("data/chart-data.json"))
print("== chart months", c["months"][-8:])
for k in c:
    if k != "months": print("  ", k, c[k][-8:])
try:
    d = json.load(open("data/latest.json"))
    print("== latest", d["date"], d["model_used"], "citations", len(d.get("web_citations", [])))
    for c in d.get("web_citations", [])[:10]: print("   cite", c["url"])
    pf = d.get("price_forecast", {})
    print("  window", pf.get("week_label"), pf.get("week_range"), "targets", pf.get("targets"))
    for k, f in (pf.get("items") or {}).items():
        print(f"\n  [{k}] week={f['week']['direction']} {f['week']['change_estimate']}\n    {f['week']['reason']}\n    next_month={f['next_month']['direction']} {f['next_month']['change_estimate']}\n    {f['next_month']['reason']}\n    revision: {f.get('revision_note')}")
    print("\n  overall:", pf.get("overall_basis"))
    print("  materials_outlook:", d.get("materials_outlook"))
    print("  summary:", d.get("summary"))
    print("  production:", d["taiwan_prices"]["crude_steel_production"])
except Exception as e:
    print("latest.json not produced:", e)
a = json.load(open("data/accuracy.json")); print("== accuracy", a["overall"], "pending", a["pending"])
