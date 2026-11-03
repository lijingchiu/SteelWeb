# Temporary: inspect the MOJ law open data and find exact names.
import io, json, re, zipfile, requests
CANDS = """營造業法 營造業法施行細則 建築法 建築師法 技師法 政府採購法 政府採購法施行細則 職業安全衛生法 職業安全衛生法施行細則
職業安全衛生設施規則 營造安全衛生設施標準 職業安全衛生管理辦法 職業安全衛生教育訓練規則 危險性工作場所審查及檢查辦法
勞動基準法 就業服務法 外國人從事就業服務法第四十六條第一項第八款至第十一款工作資格及審查標準 廢棄物清理法 空氣污染防制法
營建工程空氣污染防制設施管理辦法 噪音管制法 民法 建築技術規則總則編 建築技術規則建築設計施工編 建築技術規則建築構造編
建築技術規則建築設備編 都市計畫法 國土計畫法 消防法 各類場所消防安全設備設置標準 建築物室內裝修管理辦法 建築物使用類組及變更使用辦法
建築物公共安全檢查簽證及申報辦法 工廠管理輔導法 水污染防治法 氣候變遷因應法 能源管理法 商品檢驗法 平衡稅及反傾銷稅課徵實施辦法
關稅法 鋼鐵業燒結工場空氣污染物排放標準 電弧爐煉鋼業空氣污染物排放標準 鋼鐵業集塵灰 高溫作業勞工作息時間標準 勞工作業環境監測實施辦法
起重升降機具安全規則 施工架 模板 公共工程 採購契約 營建剩餘土石方 營造業承攬工程造價限額工程規模範圍申報淨值及一定期間承攬總額認定辦法
營造業專業工程特定施工項目應置之技術士種類比率或人數標準表 建築物耐震 無障礙 綠建築 碳費收費辦法 公寓大廈管理條例 毒性及關注化學物質管理法""".split()
import subprocess
for kind in ("Order",):
    url = f"https://law.moj.gov.tw/api/Ch/{kind}/JSON"
    for attempt in range(6):
        rc = subprocess.run(["curl", "-sSL", "--retry", "5", "--retry-all-errors", "-C", "-", "-o", f"{kind}.zip", url]).returncode
        print(kind, "curl rc", rc)
        if rc == 0: break
    raw = open(f"{kind}.zip", "rb").read()
    print(kind, "bytes", len(raw))
    if raw[:2] == b"PK":
        z = zipfile.ZipFile(io.BytesIO(raw)); print(" zip:", z.namelist()); raw = z.read(z.namelist()[0])
    data = json.loads(raw.decode("utf-8-sig"))
    laws = data.get("Laws") or []
    print(" keys:", list(data.keys()), "count", len(laws), "update", data.get("UpdateDate"))
    if laws:
        l = laws[0]; print(" law keys:", list(l.keys()))
        arts = l.get("LawArticles") or []
        print(" article keys:", list(arts[0].keys()) if arts else None, "types:", sorted({a.get("ArticleType") for a in arts}))
        print(" sample:", json.dumps({k: l[k] for k in l if k not in ("LawArticles", "LawHistories")}, ensure_ascii=False)[:500])
        print(" sample art:", json.dumps(arts[:3], ensure_ascii=False)[:400])
    names = {l["LawName"]: l for l in laws}
    for c in CANDS:
        if c in names:
            l = names[c]; print(f"  EXACT {kind} {c} | {l.get('LawLevel')} | {l.get('LawModifiedDate')} | arts {len(l.get('LawArticles') or [])} | {l.get('LawURL')} | abandon={bool(l.get('LawAbandonNote'))}")
        else:
            near = [n for n in names if c in n][:6]
            if near: print(f"  NEAR  {kind} {c} -> {near}")

# rerun
