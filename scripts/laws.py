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
    # 水土保持及山坡地管理
    ("水土保持法", [C, D], None),
    ("水土保持法施行細則", [C, D], None),
    ("水土保持計畫審核監督辦法", [C, D], None),
    ("水土保持計畫審查收費標準", [C, D], None),
    ("水土保持保證金繳納及保管運用辦法", [C, D], None),
    ("特定水土保持區劃定與廢止準則", [C, D], None),
    ("特定水土保持區一定規模以上之地貌改變認定辦法", [C, D], None),
    ("山坡地保育利用條例", [C, D], None),
    ("山坡地保育利用條例施行細則", [C, D], None),
    # 營建營造：採購法子法
    ("招標期限標準", [C], None),
    ("最有利標評選辦法", [C], None),
    ("投標廠商資格與特殊或巨額採購認定標準", [C], None),
    ("押標金保證金暨其他擔保作業辦法", [C], None),
    ("採購履約爭議調解規則", [C], None),
    ("機關委託技術服務廠商評選及計費辦法", [C, D], None),
    ("採購評選委員會組織準則", [C], None),
    ("採購評選委員會審議規則", [C], None),
    ("統包實施辦法", [C], None),
    ("共同投標辦法", [C], None),
    ("中央機關未達公告金額採購招標辦法", [C], None),
    ("採購申訴審議規則", [C], None),
    ("工程施工查核小組作業辦法", [C], None),
    ("採購人員倫理準則", [C], None),
    # 營建營造：勞工與營造業管理
    ("勞工職業災害保險及保護法", [C, S], None),
    ("勞工保險條例", [C, S], None),
    ("營造業評鑑辦法", [C], None),
    ("營造業工地主任評定回訓及管理辦法", [C], None),
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
    # 建築設計：都更、危老與土地
    ("都市更新條例", [D, C], None),
    ("都市更新條例施行細則", [D, C], None),
    ("都市危險及老舊建築物加速重建條例", [D, C], None),
    ("都市危險及老舊建築物加速重建條例施行細則", [D, C], None),
    ("都市危險及老舊建築物建築容積獎勵辦法", [D, C], None),
    ("都市危險及老舊建築物結構安全性能評估辦法", [D, C], None),
    ("土地法", [D], None),
    ("土地法施行法", [D], None),
    ("促進民間參與公共建設法", [D, C], None),
    ("促進民間參與公共建設法施行細則", [D, C], None),
    ("都市計畫法臺灣省施行細則（89.12.29 訂定）", [D], None),
    ("都市計畫容積移轉實施辦法", [D], None),
    ("都市計畫定期通盤檢討實施辦法", [D], None),
    ("區域計畫法", [D], None),
    ("區域計畫法施行細則", [D], None),
    ("非都市土地使用管制規則", [D], None),
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


L = "地方自治法規"
# Selected official city regulations; a failed refresh keeps the last verified copy.
LOCAL: list[tuple[str, str, str, str]] = [
    # (city, system, id, expected name)
    ("臺北市", "tpe", "FL004106", "臺北市建築管理自治條例"),
    ("臺北市", "tpe", "FL003962", "臺北市土地使用分區管制自治條例"),
    ("新北市", "ntpc", "1C0170035", "新北市建築管理規則"),
    ("新北市", "ntpc", "1C0150108", "都市計畫法新北市施行細則"),
    ("新北市", "ntpc", "1C0170194", "新北市營建剩餘土石方管理自治條例"),
    ("臺中市", "tc", "GL002282", "臺中市建築管理自治條例"),
    ("臺中市", "tc", "GL002020", "都市計畫法臺中市施行自治條例"),
    ("臺中市", "tc", "GL001704", "臺中市營建賸餘土石方管理自治條例"),
    ("高雄市", "kcg", "GL000537", "高雄市建築管理自治條例"),
    ("高雄市", "kcg", "GL000627", "都市計畫法高雄市施行細則"),
    ("高雄市", "kcg", "GL001111", "高雄市營建工程剩餘土石方管理自治條例"),
    ("基隆市", "kl", "GL000501", "基隆市營建剩餘土石方資源處理及收容處理場所設置管理自治條例"),
    ("新竹市", "hc", "FL030211", "新竹市營建剩餘土石方處理自治條例"),
    ("苗栗縣", "ml", "FL033808", "苗栗縣營建工程剩餘土石方處理及資源堆置處理場設置管理自治條例"),
    ("彰化縣", "ch", "FL038757", "彰化縣營建剩餘土石方管理自治條例"),
    ("南投縣", "nt", "GL000179", "南投縣營建工程賸餘土石方處理及資源堆置處理場設置管理自治條例"),
    ("金門縣", "km", "FL038759", "金門縣營建工程剩餘土石方處理自治條例"),
    ("新竹縣", "hcc", "GL000253", "新竹縣營建工程剩餘土石方管理自治條例"),
    ("嘉義市", "cyi", "FL026378", "嘉義市營建工程剩餘土石方管理自治條例"),
    ("嘉義縣", "cyc", "FL037406", "嘉義縣營建剩餘土石方管理自治條例"),
    ("屏東縣", "pt", "GL000060", "屏東縣營建剩餘土石方管理自治條例"),
    ("澎湖縣", "ph", "FL038758", "澎湖縣營建剩餘土石方管理自治條例"),
    ("花蓮縣", "hl", "FL048840", "花蓮縣營建工程剩餘土石方管理自治條例"),
    ("臺東縣", "tt", "GL000274", "臺東縣營建剩餘土石方管理自治條例"),
    ("桃園市", "ty", "GL001477", "桃園市營建剩餘土石方管理自治條例"),
    ("新竹縣", "hcc", "FL026964", "新竹縣建築管理自治條例"),
    ("嘉義市", "cyi", "FL022491", "嘉義市建築管理自治條例"),
    ("嘉義縣", "cyc", "FL026925", "嘉義縣建築管理自治條例"),
    ("屏東縣", "pt", "FL026602", "屏東縣建築管理自治條例"),
    ("澎湖縣", "ph", "FL026758", "澎湖縣建築管理自治條例"),
    ("花蓮縣", "hl", "FL026603", "花蓮縣建築管理自治條例"),
    ("臺東縣", "tt", "FL021926", "臺東縣建築管理自治條例"),
    ("桃園市", "ty", "GL001431", "桃園市建築管理自治條例"),
    ("基隆市", "kl", "GL000079", "基隆市建築管理自治條例"),
    ("金門縣", "km", "FL030625", "金門縣建築管理自治條例"),
    ("新竹市", "hc", "FL022481", "新竹市建築管理自治條例"),
    ("苗栗縣", "ml", "FL026450", "苗栗縣建築管理自治條例"),
    ("彰化縣", "ch", "FL026531", "彰化縣建築管理自治條例"),
    ("南投縣", "nt", "FL021919", "南投縣建築管理自治條例"),
]
LOCAL_URLS = {
    "tpe": "https://laws.gov.taipei/Law/LawSearch/LawArticleContent/{id}",
    "ntpc": "https://web.law.ntpc.gov.tw/Scripts/FLAWDAT01.aspx?lncode={id}",
    "tc": "https://lawsearch.taichung.gov.tw/LawContent.aspx?id={id}",
    "kcg": "https://outlaw.kcg.gov.tw/LawContent.aspx?id={id}",
    "kl": "https://exlaw.klcg.gov.tw/LawContent.aspx?id={id}",
    "hc": "https://law.hccg.gov.tw/LawContent.aspx?id={id}",
    "ml": "https://law.miaoli.gov.tw/glrsnewsout/LawContent.aspx?id={id}",
    "ch": "https://lawsearch.chcg.gov.tw/GLRSNEWSOUT/LawContent.aspx?id={id}",
    "nt": "https://glrs.nantou.gov.tw/LawContent.aspx?id={id}",
    "km": "https://law.kinmen.gov.tw/LawContent.aspx?id={id}",
    "hcc": "https://hclaw.hsinchu.gov.tw/law/LawContent.aspx?id={id}",
    "cyi": "https://law.chiayi.gov.tw/LawContent.aspx?id={id}",
    "cyc": "https://law.cyhg.gov.tw/LawContent.aspx?id={id}",
    "pt": "https://ptlaw.pthg.gov.tw/LawContent.aspx?id={id}",
    "ph": "https://law.penghu.gov.tw/glrsnewsout/LawContent.aspx?id={id}",
    "hl": "https://glrs.hl.gov.tw/glrsout/LawContent.aspx?id={id}",
    "tt": "https://law.taitung.gov.tw/LawContent.aspx?id={id}",
    "ty": "https://law.tycg.gov.tw/LawContent.aspx?id={id}",
}


def log(msg: str):
    print(f"[laws] {msg}", flush=True)


def download(kind: str, url: str) -> list[dict]:
    """The files are large (the regulations file is ~25 MB): curl resumes broken
    transfers, and a response that is not a valid archive is fetched again."""
    path = Path(tempfile.gettempdir()) / f"moj-{kind}.zip"
    for full_try in range(4):
        path.unlink(missing_ok=True)
        for attempt in range(6):
            rc = subprocess.run(["curl", "-sSL", "--retry", "5", "--retry-all-errors", "--max-time", "600",
                                 "-C", "-", "-o", str(path), url]).returncode
            if rc == 0:
                break
            log(f"{kind}: curl exit {rc}, retrying ({attempt + 1})")
        try:
            raw = path.read_bytes()
            if raw[:2] == b"PK":
                z = zipfile.ZipFile(io.BytesIO(raw))
                raw = z.read(next(n for n in z.namelist() if n.lower().endswith(".json")))
            data = json.loads(raw.decode("utf-8-sig"))
            log(f"{kind}: {len(data.get('Laws') or [])} items, source updated {data.get('UpdateDate')}")
            return data.get("Laws") or [], data.get("UpdateDate")
        except Exception as e:
            size = path.stat().st_size if path.exists() else 0
            log(f"{kind}: bad download ({type(e).__name__}, {size} bytes), fetching again")
            subprocess.run(["sleep", str(30 * (full_try + 1))])
    raise RuntimeError(f"{kind}: could not download a valid file")


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


# ── Local regulations ─────────────────────────────────────

CN_DIGIT = {"零": 0, "〇": 0, "一": 1, "二": 2, "兩": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def cn_int(t: str) -> int | None:
    t = t.replace(" ", "")
    if t.isdigit():
        return int(t)
    total = cur = 0
    for ch in t:
        if ch in CN_DIGIT:
            cur = CN_DIGIT[ch]
        elif ch == "十":
            total += (cur or 1) * 10; cur = 0
        elif ch == "百":
            total += (cur or 1) * 100; cur = 0
        else:
            return None
    return total + cur


def roc_date(text: str, label: str) -> str:
    m = re.search(label + r"[：:]\s*民國\s*(\d+)\s*年\s*(\d+)\s*月\s*(\d+)\s*日", text)
    return f"{int(m.group(1)) + 1911}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else ""


def plain_html(fragment: str) -> str:
    import html as H
    t = re.sub(r"<br\s*/?>|</(?:p|div|li|tr)>", "\n", fragment, flags=re.I)
    t = H.unescape(re.sub(r"<[^>]+>", "", t)).replace("\xa0", " ")
    return "\n".join(re.sub(r"[ \t\u3000]+", " ", line).strip() for line in t.splitlines())


ART_HEAD = re.compile(r"^\s*第\s*([0-9一二三四五六七八九十百零〇兩 ]+?)\s*條(?:\s*之\s*([0-9一二三四五六七八九十]+))?\s*", re.M)
CHAPTER = re.compile(r"^\s*第\s*[0-9一二三四五六七八九十百 ]+\s*[章節編]\s*\S.*$", re.M)


def split_articles(text: str) -> list[dict]:
    """Splits plain text into articles at lines starting with 第X條; tracks chapter headings.

    Text in the city systems is wrapped mid-sentence, so a line can start with a
    cross-reference such as 「第一百零一條規定…」. Only headings whose number follows
    on from the previous article are accepted; the rest stay part of the text."""
    heads, prev = [], 0
    for m in ART_HEAD.finditer(text):
        n = cn_int(m.group(1))
        if n is None:
            continue
        if (not heads and n <= 3) or (heads and prev <= n <= prev + 10):
            heads.append((m, n))
            prev = n
    out, chapter = [], ""
    for i, (m, n) in enumerate(heads):
        before = text[heads[i - 1][0].end() if i else 0:m.start()]
        ch = CHAPTER.findall(before)
        if ch:
            chapter = re.sub(r"\s+", " ", ch[-1]).strip()
        end = heads[i + 1][0].start() if i + 1 < len(heads) else len(text)
        body = re.sub(r"\n{2,}", "\n", CHAPTER.sub("", text[m.end():end])).strip()
        sub = cn_int(m.group(2)) if m.group(2) else None
        if not body:
            continue
        key = f"{n}-{sub}" if sub else str(n)
        out.append({"no": f"第{key}條", "n": key, "chapter": chapter, "text": body})
    return out


def extract_local_article_text(page: str) -> str:
    """Extract only the official article container, including nested markup."""
    from html.parser import HTMLParser
    class ArticleParser(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.active = False
            self.finished = False
            self.depth = 0
            self.parts = []
        def handle_starttag(self, tag, attrs):
            if self.finished:
                return
            attrs = dict(attrs)
            ident = attrs.get("id", "")
            if not self.active:
                if tag in {"div", "table"} and (ident.endswith("divLawContent08") or ident.endswith("tableLawArticleBasic")):
                    self.active = True
                    self.depth = 1
                return
            if tag not in {"br", "img", "input", "hr", "meta", "link"}:
                self.depth += 1
            if tag == "br":
                self.parts.append("\n")
        def handle_endtag(self, tag):
            if not self.active:
                return
            if tag in {"td", "tr", "div", "p", "li"}:
                self.parts.append("\n")
            if tag not in {"br", "img", "input", "hr", "meta", "link"}:
                self.depth -= 1
                if self.depth == 0:
                    self.active = False
                    self.finished = True
        def handle_data(self, data):
            if self.active:
                self.parts.append(data)
    parser = ArticleParser()
    parser.feed(page)
    if parser.finished:
        return "".join(parser.parts).replace("\xa0", " ")
    m = re.search(r'class="law-reg-content law-article">(.*?)<div class="(?:btnZone|law-reg-footer)', page, re.S)
    return plain_html(m.group(1)) if m else ""


def fetch_local(system: str, lid: str, expected_name: str = "") -> tuple[str, str, list[dict]]:
    import requests
    ua = {"User-Agent": "Mozilla/5.0 (compatible; SteelWeb regulations mirror)"}
    url = LOCAL_URLS[system].format(id=lid)
    request_timeout = 12 if expected_name else 60
    if system == "ntpc":
        s = requests.Session()
        r = s.get(url, headers=ua, timeout=60)
        r.raise_for_status()
        form = dict(re.findall(r'<input type="hidden" name="([^"]+)"[^>]*value="([^"]*)"', r.text))
        import html as H
        form = {k: H.unescape(v) for k, v in form.items()}
        form["ctl00$cph_content$B5"] = "所有條文"
        r = s.post(url, data=form, headers=ua, timeout=60)
    else:
        r = requests.get(url, headers=ua, timeout=request_timeout)
    r.raise_for_status()
    page = r.text
    import html as H
    flat = re.sub(r"\s+", " ", H.unescape(re.sub(r"<[^>]+>", " ", page)))
    if system in {"kl", "hc", "ml", "ch", "nt", "km", "hcc", "cyi", "cyc", "pt", "ph", "hl", "tt", "ty"} and expected_name:
        if re.sub(r"\s+", "", expected_name) not in re.sub(r"\s+", "", flat):
            raise ValueError("official page title does not match expected regulation")
        if re.search(r"法規名稱\s*[：:]\s*廢", flat):
            raise ValueError("regulation is marked abolished")
    if system == "tpe":
        name = re.search(r"<title>([^<|]+)", page)
        items = re.findall(r'<li class="chapter[^"]*">(.*?)</li>|<div class="col-no">(.*?)</div>\s*<div class="col-data">(.*?)</div>\s*</div>\s*<div class="col-link">', page, re.S)
        arts, chapter = [], ""
        for ch, no, data in items:
            if ch:
                chapter = plain_html(ch).strip(); continue
            m = re.search(r"第\s*([0-9]+)(?:\s*-\s*([0-9]+))?\s*條", H.unescape(no))
            if not m:
                continue
            key = f"{m.group(1)}-{m.group(2)}" if m.group(2) else m.group(1)
            arts.append({"no": f"第{key}條", "n": key, "chapter": chapter, "text": plain_html(data).strip()})
        modified = roc_date(flat, "修正日期") or roc_date(flat, "公發布日")
        if not modified:
            try:
                ex = requests.get(f"https://laws.gov.taipei/Law/LawSearch/LawExport/{lid}?type=0", headers=ua, timeout=60, stream=True)
                m = re.search(r"-(\d{4})(\d{2})(\d{2})-", requests.utils.unquote(ex.headers.get("content-disposition", "")))
                ex.close()
                modified = f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else ""
            except Exception:
                modified = ""
    elif system == "ntpc":
        # The 「所有條文」 button leads to a table: one row per article, chapter rows between.
        arts, chapter = [], ""
        for ch, no, data in re.findall(r'<td colspan="2" class="ch0\d">(.*?)</td>|<td class="col-th">(.*?)</td>\s*<td class="col-td">\s*<pre>(.*?)</pre>', page, re.S):
            if ch:
                chapter = re.sub(r"\s+", " ", plain_html(ch)).strip(); continue
            m = re.search(r"第\s*([0-9]+)(?:\s*-\s*([0-9]+))?\s*條", H.unescape(no).replace("\xa0", " "))
            if not m:
                continue
            key = f"{m.group(1)}-{m.group(2)}" if m.group(2) else m.group(1)
            arts.append({"no": f"第{key}條", "n": key, "chapter": chapter, "text": H.unescape(re.sub(r"<[^>]+>", "", data)).strip()})
        m = re.search(r"民國\s*(\d+)\s*年\s*(\d+)\s*月\s*(\d+)\s*日\s*(?:修正|公發布|發布|制定)", flat)
        modified = f"{int(m.group(1)) + 1911}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else roc_date(flat, "公發布時間")
    else:
        block = extract_local_article_text(page)
        if not block:
            raise ValueError("unable to isolate official article content")
        arts = split_articles(block)
        modified = roc_date(flat, "修正日期") or roc_date(flat, "公發布日")
    for a in arts:
        a["text"] = re.split(r"\s*:::\s*", a["text"])[0].strip()
    return url, modified, arts


def build_local(existing: dict) -> list[dict]:
    """Fetches each local regulation; on failure keeps the previously stored copy."""
    docs = []
    for city, system, lid, name in LOCAL:
        pcode = f"{system.upper()}-{lid}"
        try:
            url, modified, arts = fetch_local(system, lid, name if system in {"kl", "hc", "ml", "ch", "nt", "km", "hcc", "cyi", "cyc", "pt", "ph", "hl", "tt", "ty"} else "")
            if len(arts) < 5:
                raise RuntimeError(f"only {len(arts)} articles parsed")
            if system in {"kl", "hc", "ml", "ch", "nt", "km", "hcc", "cyi", "cyc", "pt", "ph", "hl", "tt", "ty"} and "施行" not in arts[-1]["text"]:
                raise RuntimeError("final article or enactment clause missing")
            doc = {"name": name, "pcode": pcode, "level": "地方法規", "moj_category": city, "categories": [L, D],
                   "region": city, "modified": modified, "effective_note": "", "url": url, "partial": False, "articles": arts}
            log(f"{city} {name}: {len(arts)} articles, modified {modified}")
        except Exception as e:
            doc = existing.get(pcode)
            log(f"{city} {name}: FAILED ({e}); {'keeping previous copy' if doc else 'no previous copy'}")
        if doc:
            docs.append(doc)
    return docs


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
    civil_path = ROOT / "scripts" / "civil_laws_catalog.json"
    civil = json.loads(civil_path.read_text(encoding="utf-8"))
    seen_names = {entry[0] for entry in wanted}
    for name in civil["names"]:
        if name not in seen_names:
            wanted.append((name, [C, D], None))
            seen_names.add(name)
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
        index.append({k: doc[k] for k in ("name", "pcode", "level", "categories", "modified", "url", "partial", "effective_note")}
                     | {"articles": len(doc["articles"])})
    for name in missing:
        log(f"MISSING: {name}")
    missing_civil = sorted(set(missing) & set(civil["names"]))
    if missing_civil:
        log(f"{len(missing_civil)} catalogued civil laws are absent from the source; refusing to replace the index pending review")
        return 1
    if len(index) < len(CATALOG) * 0.8:
        log(f"only {len(index)} of {len(CATALOG)} laws found; not writing the index")
        return 1

    existing = {}
    for f in OUT.glob("*.json"):
        if "-" in f.stem:
            try:
                existing[f.stem] = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                pass
    for doc in build_local(existing):
        (OUT / f"{doc['pcode']}.json").write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        index.append({k: doc[k] for k in ("name", "pcode", "level", "categories", "modified", "url", "partial", "effective_note")}
                     | {"articles": len(doc["articles"]), "region": doc["region"]})

    keep = {f"{x['pcode']}.json" for x in index} | {"index.json", "README.md"}
    for f in OUT.iterdir():
        if f.is_file() and f.name not in keep:
            f.unlink()

    now = datetime.now(TW).isoformat(timespec="seconds")
    reference_path = OUT / "reference-archive" / "index.json"
    reference = None
    if reference_path.exists():
        catalog = json.loads(reference_path.read_text(encoding="utf-8"))
        reference = {"index": "data/laws/reference-archive/index.json",
                     "manifest": "data/laws/reference-archive/MANIFEST.md",
                     "categories": [{"name": c["category"], "count": c["count"]} for c in catalog["categories"]],
                     "note": "參考資料，不代表現行法規；部分含 OCR 或不完整內容。"}
    (OUT / "index.json").write_text(json.dumps({
        "updated_at": now,
        "source": "全國法規資料庫開放資料（法務部）",
        "source_updated": updates,
        "license": "政府資料開放授權條款第1版；法律條文依著作權法第9條不得為著作權之標的",
        "laws": index,
        **({"reference_archive": reference} if reference else {}),
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    lines = ["# 法規資料", "",
             f"來源：全國法規資料庫開放資料（法務部），資料日期 {', '.join(str(u) for u in updates)}；本次整理 {now}。",
             "授權：政府資料開放授權條款第1版；法律條文依著作權法第9條不得為著作權之標的。",
             "地方自治法規取自各縣市政府法規查詢系統；僅收錄已取得並核對的部分法規，其他縣市請使用官方查詢入口。",
             "每月自動更新。CNS 國家標準與設計規範解說等有著作權的文件不在此列。", ""]
    for cat in (C, D, S, L):
        lines += [f"## {cat}", "", "| 法規 | 位階 | 最新修正 | 條數 |", "|---|---|---|---|"]
        for x in index:
            if x["categories"][0] == cat:
                note = "（僅收錄消滅時效、承攬相關條文）" if x["partial"] else ""
                lines.append(f"| [{x['name']}]({x['url']}){note} | {x.get('region') or x['level']} | {x['modified']} | {x['articles']} |")
        lines.append("")
    (OUT / "README.md").write_text("\n".join(lines), encoding="utf-8")
    total = sum(x["articles"] for x in index)
    size = sum(f.stat().st_size for f in OUT.iterdir())
    log(f"wrote {len(index)} laws, {total} articles, {size // 1024} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
