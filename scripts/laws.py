"""
Construction, building-design and steel-industry regulations for the site assistant.

Source: 全國法規資料庫 open data (Ministry of Justice), released under the
政府資料開放授權條款第1版. Statute text is not protected by copyright
(著作權法第9條). CNS standards and design manuals are copyrighted and are not
included.

Writes, for each catalogued law, data/laws/<pcode>.json with every article,
plus data/laws/index.json (catalogue the assistant reads) and data/laws/README.md.
Run monthly; laws that are amended are picked up automatically.
"""

from __future__ import annotations

import io
import json
import re
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "laws"
TW = timezone(timedelta(hours=8))
SOURCES = {
    "Law": "https://law.moj.gov.tw/api/Ch/Law/JSON",
    "Order": "https://law.moj.gov.tw/api/Ch/Order/JSON",
}
C, D, S = "營建營造", "建築設計", "鋼鐵製造"

# (exact name in the MOJ data, categories, optional article ranges to keep)
CATALOG: list[tuple[str, list[str], list[tuple[int, int]] | None]] = [
    # 營建營造
    ("營造業法", [C], None),
    ("營造業法施行細則", [C], None),
    ("營造業承攬工程造價限額工程規模範圍申報淨值及一定期間承攬總額認定辦法", [C], None),
    ("政府採購法", [C], None),
    ("政府採購法施行細則", [C], None),
    ("技師法", [C, D], None),
    ("技師法施行細則", [C, D], None),
    ("公共工程專業技師簽證規則", [C, D], None),
    ("民法", [C], [(125, 128), (490, 514)]),  # 消滅時效、承攬
    ("職業安全衛生法", [C, S], None),
    ("職業安全衛生法施行細則", [C, S], None),
    ("職業安全衛生設施規則", [C, S], None),
    ("營造安全衛生設施標準", [C], None),
    ("職業安全衛生管理辦法", [C, S], None),
    ("職業安全衛生教育訓練規則", [C, S], None),
    ("危險性工作場所審查及檢查辦法", [C, S], None),
    ("起重升降機具安全規則", [C, S], None),
    ("勞工作業環境監測實施辦法", [C, S], None),
    ("高溫作業勞工作息時間標準", [C, S], None),
    ("勞動基準法", [C, S], None),
    ("勞動基準法施行細則", [C, S], None),
    ("就業服務法", [C, S], None),
    ("外國人從事就業服務法第四十六條第一項第八款至第十款工作資格及審查標準", [C, S], None),
    ("廢棄物清理法", [C, S], None),
    ("空氣污染防制法", [C, S], None),
    ("營建工程空氣污染防制設施管理辦法", [C], None),
    ("噪音管制法", [C], None),
    # 建築設計
    ("建築法", [D, C], None),
    ("建築師法", [D], None),
    ("建築師法施行細則", [D], None),
    ("建築技術規則總則編", [D, C], None),
    ("建築技術規則建築設計施工編", [D, C], None),
    ("建築技術規則建築構造編", [D, C], None),
    ("建築技術規則建築設備編", [D, C], None),
    ("都市計畫法", [D], None),
    ("國土計畫法", [D], None),
    ("消防法", [D], None),
    ("各類場所消防安全設備設置標準", [D, C], None),
    ("建築物室內裝修管理辦法", [D, C], None),
    ("建築物使用類組及變更使用辦法", [D], None),
    ("建築物公共安全檢查簽證及申報辦法", [D], None),
    ("公寓大廈管理條例", [D], None),
    # 鋼鐵製造
    ("工廠管理輔導法", [S], None),
    ("工廠管理輔導法施行細則", [S], None),
    ("鋼鐵業燒結工場空氣污染物排放標準", [S], None),
    ("鋼鐵業集塵灰高溫冶煉設施戴奧辛管制及排放標準", [S], None),
    ("水污染防治法", [S], None),
    ("氣候變遷因應法", [S], None),
    ("碳費收費辦法", [S], None),
    ("能源管理法", [S], None),
    ("商品檢驗法", [S], None),
    ("關稅法", [S], None),
    ("平衡稅及反傾銷稅課徵實施辦法", [S], None),
    ("毒性及關注化學物質管理法", [S], None),
]
# Steel-specific environmental rules whose exact titles vary; matched by name.
EXTRA_PATTERNS = [(re.compile(r"電弧爐"), [S])]


def log(msg: str):
    print(f"[laws] {msg}", flush=True)


def download(kind: str, url: str) -> list[dict]:
    """The files are large (the regulations file is ~25 MB); curl resumes broken transfers."""
    path = Path(tempfile.gettempdir()) / f"moj-{kind}.zip"
    path.unlink(missing_ok=True)
    for attempt in range(6):
        rc = subprocess.run(["curl", "-sSL", "--retry", "5", "--retry-all-errors", "--max-time", "600",
                             "-C", "-", "-o", str(path), url]).returncode
        if rc == 0:
            break
        log(f"{kind}: curl exit {rc}, retrying ({attempt + 1})")
    raw = path.read_bytes()
    if raw[:2] == b"PK":
        z = zipfile.ZipFile(io.BytesIO(raw))
        name = next(n for n in z.namelist() if n.lower().endswith(".json"))
        raw = z.read(name)
    data = json.loads(raw.decode("utf-8-sig"))
    log(f"{kind}: {len(data.get('Laws') or [])} items, source updated {data.get('UpdateDate')}")
    return data.get("Laws") or [], data.get("UpdateDate")


ART_NO = re.compile(r"第\s*(\d+)(?:\s*-\s*(\d+))?\s*條")


def article_key(no: str) -> tuple[int, int] | None:
    m = ART_NO.search(no or "")
    return (int(m.group(1)), int(m.group(2) or 0)) if m else None


def fmt_date(s: str) -> str:
    s = str(s or "")
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if re.fullmatch(r"\d{8}", s) else s


def convert(law: dict, cats: list[str], ranges) -> dict:
    pcode = re.search(r"pcode=([A-Za-z0-9]+)", law.get("LawURL") or "").group(1)
    chapter = ""
    articles = []
    for a in law.get("LawArticles") or []:
        if a.get("ArticleType") == "C":
            chapter = re.sub(r"\s+", " ", a.get("ArticleContent") or "").strip()
            continue
        key = article_key(a.get("ArticleNo"))
        if ranges and (not key or not any(lo <= key[0] <= hi for lo, hi in ranges)):
            continue
        no = re.sub(r"\s+", "", a.get("ArticleNo") or "")
        articles.append({
            "no": no,                                   # 第19條 / 第5-1條
            "n": f"{key[0]}-{key[1]}" if key and key[1] else (str(key[0]) if key else ""),
            "chapter": chapter,
            "text": (a.get("ArticleContent") or "").strip(),
        })
    return {
        "name": law["LawName"],
        "pcode": pcode,
        "level": law.get("LawLevel"),
        "moj_category": law.get("LawCategory"),
        "categories": cats,
        "modified": fmt_date(law.get("LawModifiedDate")),
        "effective_note": law.get("LawEffectiveNote") or "",
        "url": law.get("LawURL"),
        "partial": bool(ranges),
        "articles": articles,
    }


def main() -> int:
    items, updates = {}, []
    for kind, url in SOURCES.items():
        laws, upd = download(kind, url)
        updates.append(upd)
        for law in laws:
            if not law.get("LawAbandonNote"):
                items.setdefault(law["LawName"], law)
    if len(items) < 5000:
        log(f"only {len(items)} laws downloaded; refusing to overwrite the existing data")
        return 1

    wanted = list(CATALOG)
    for name in items:
        for pat, cats in EXTRA_PATTERNS:
            if pat.search(name) and not any(name == w[0] for w in wanted):
                wanted.append((name, cats, None))

    OUT.mkdir(parents=True, exist_ok=True)
    index, missing = [], []
    for name, cats, ranges in wanted:
        law = items.get(name)
        if not law:
            missing.append(name)
            continue
        doc = convert(law, cats, ranges)
        (OUT / f"{doc['pcode']}.json").write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        index.append({k: doc[k] for k in ("name", "pcode", "level", "categories", "modified", "url", "partial")}
                     | {"articles": len(doc["articles"])})
    for name in missing:
        log(f"MISSING: {name}")
    if len(index) < len(CATALOG) * 0.8:
        log(f"only {len(index)} of {len(CATALOG)} laws found; not writing the index")
        return 1

    keep = {f"{x['pcode']}.json" for x in index} | {"index.json", "README.md"}
    for f in OUT.iterdir():
        if f.name not in keep:
            f.unlink()

    now = datetime.now(TW).isoformat(timespec="seconds")
    (OUT / "index.json").write_text(json.dumps({
        "updated_at": now,
        "source": "全國法規資料庫開放資料（法務部）",
        "source_updated": updates,
        "license": "政府資料開放授權條款第1版；法律條文依著作權法第9條不得為著作權之標的",
        "laws": index,
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    lines = ["# 法規資料", "",
             f"來源：全國法規資料庫開放資料（法務部），資料日期 {', '.join(str(u) for u in updates)}；本次整理 {now}。",
             "授權：政府資料開放授權條款第1版；法律條文依著作權法第9條不得為著作權之標的。",
             "每月自動更新。CNS 國家標準與設計規範解說等有著作權的文件不在此列。", ""]
    for cat in (C, D, S):
        lines += [f"## {cat}", "", "| 法規 | 位階 | 最新修正 | 條數 |", "|---|---|---|---|"]
        for x in index:
            if x["categories"][0] == cat:
                note = "（僅收錄消滅時效、承攬相關條文）" if x["partial"] else ""
                lines.append(f"| [{x['name']}]({x['url']}){note} | {x['level']} | {x['modified']} | {x['articles']} |")
        lines.append("")
    (OUT / "README.md").write_text("\n".join(lines), encoding="utf-8")
    total = sum(x["articles"] for x in index)
    size = sum(f.stat().st_size for f in OUT.iterdir())
    log(f"wrote {len(index)} laws, {total} articles, {size // 1024} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
