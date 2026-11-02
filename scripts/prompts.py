"""
Prompts for the two-stage analysis.

Stage 1 (researcher, web search): verify facts, compare conflicting reports, check the
raw-material reasoning chains against current news, and return a JSON research dossier.
Stage 2 (chief analyst, no tools): forecast from the dossier, the official data and the
historical base rates, and write it up in plain Chinese for a non-expert reader.

Structure follows OpenAI's guidance for reasoning models: XML-tagged sections, the key
rules first and restated after long context, an explicit order of precedence instead of
competing "always" rules, a stated research bar with stop criteria, and no instruction
to "think step by step". The forecasting checks (base rates first, weighted pros and
cons, counter-argument, calibration) come from published LLM and superforecasting
studies and are requested as required answer content rather than reasoning steps.
"""

ITEM_KEYS = ["north_scrap_price", "billet_price", "fengxing_rebar_price", "h_beam_price", "csc_wire_rod_price"]
DIMENSIONS = ["成本", "供給", "需求", "政策與貿易", "市場情緒", "季節性"]

WRITING_RULES = """<writing_rules>
讀者是營建公司的總經理：懂工地、懂採購，不是金融分析師，也沒有時間讀艱深的報告。所有給讀者看的文字都用繁體中文，並遵守：
- 先講結論再講原因。第一句就讓人知道「漲、跌還是持平，大概多少」。
- 用完整的短句、常用字、主動語氣，一句話只講一件事。像跟熟識的同業說明，不要像寫論文。
- 每個判斷都要講清楚「發生了什麼事 → 對台灣鋼廠或買家有什麼影響 → 所以價格會怎樣」。
- 數字一定帶單位和時間，例如「豐興 10/27 鋼筋每噸漲 200 元到 18,500 元」。
- 專有名詞第一次出現時用括號白話解釋，例如「小鋼胚（煉鋼後、軋成鋼筋前的半成品）」；英文縮寫翻成中文（不寫 HMS，寫「美國重熔廢鋼」）。
- 不要使用這類術語、代號或格式：驅動因子、傳導路徑、基準情境、權重、外部視角、F1 之類的事實編號、(a)(b)(c) 分點、英文句子。
- 不確定就直說「還沒確認」或「只有一家媒體報導」，不要用模糊的空話帶過。
</writing_rules>"""


def research_prompt(*, date_str: str, week_label: str, week_range: str, official_prices: str,
                    fx: str, base_rates: str, links: str, materials: str, news: str) -> str:
    return f"""<role_and_objective>
你是台灣鋼鐵與營建材料市場的研究員。今天（{date_str}，台灣時間）的任務只有「查證事實、比對報導、核對推理鏈」，不用做預測。
另一位分析師會完全依照你的研究底稿預測{week_label}（{week_range}）行情與下一期官方月均價，所以正確比篇幅重要：寧可少寫，也不能寫錯。
</role_and_objective>

<research_bar>
- 依 <topics> 逐項搜尋。每個主題至少用中文、英文各查一次；同一個問題不要只靠一次搜尋，也不要重複搜尋同一句話。
- 以最近 14 天的消息為主，較舊的資料只用來交代背景。
- 先廣泛搜尋，再針對缺漏或互相矛盾的地方補查。
- 停止條件：每個主題都有結論或已確認查不到、主要數字都有來源、再查下去不太可能改變結論，就停止。全部大約 15～25 次搜尋。
- 不要問問題，也不要等待確認；資訊不足時照實記在 gaps，繼續完成其他主題。
</research_bar>

<topics>
1. 豐興本週與上週的廢鋼收購價、鋼筋、型鋼盤價（金額與漲跌），以及本月以來的每週變化。
2. 威致、海光、東和、中鋼、燁興等鋼廠的最新盤價或調價公告。
3. 台灣北部與南部廢鋼行情；美國重熔廢鋼（HMS 1&2）出口到台灣、土耳其的報價；日本 H2 廢鋼標售價。
4. 中國螺紋鋼期貨、唐山鋼胚、中國鋼材出口量與出口報價。
5. 鐵礦砂與焦煤價格。
6. 台灣營建需求：建照與開工面積、公共工程進度、預拌混凝土出貨、下游接單。
7. 台電電價、碳費等影響電爐鋼廠成本的政策。
8. 反傾銷與貿易：台灣對進口鋼品的課稅、其他國家對台灣鋼品的措施、中國出口政策。
9. 美元兌新台幣走勢對進口原料成本的影響。
10. 依 <verified_links> 核對推理鏈：歷史上連動明顯的那幾條，查證「這個月有沒有正在發生」（例如本月豐興廢鋼週盤是否已調整、國際廢鋼報價是否已反映到台灣）。
</topics>

<source_rules>
- 優先順序：鋼廠或政府的正式公告、交易所與官方統計 > 主要財經媒體（經濟日報、工商時報、鉅亨網、MoneyDJ、Reuters）> 產業資訊網（SteelOrbis、Argus、Fastmarkets、Mysteel、SMM）> 其他網站。內容農場、轉貼站與來路不明的部落格不要用。
- 台灣的事情優先找中文來源，國際行情優先找英文或中國大陸的產業來源。
- 新聞要同時比對「報導日期」和「事件發生日期」，避免把舊消息當成新消息。
</source_rules>

<cross_check_rules>
- 每個數字或事件，盡量找兩個以上不同網站的來源核對。只找到一個來源就照實寫一個，系統會自己計算不同網站數，灌水會被發現。
- 標明事實類型：公告（廠商或政府正式公布）、成交（市場實際成交價）、報價（業者開價或喊價）、預估（分析師或媒體預測）、傳聞（未經證實）。
- 上方新聞清單裡，同一件事若不同媒體寫的數字、日期或方向不一致，列在 conflicts，寫出各家說法與你判斷可信的版本和理由（正式公告優先、較新且較具體的報導優先）。
</cross_check_rules>

<chain_rules>
- <verified_links> 是系統用過去 36 個月官方月資料算出的連動關係：哪些原物料和鋼價過去真的同漲同跌、是同月反映還是晚一個月反映、連動有多穩定。
- 只有歷史上連動明顯的推理鏈才值得核對；歷史上不成立的推理（例如「鐵礦砂漲，下個月鋼筋一定漲」）不要拿來當依據。
- 官方月均價要等月底後才公布，所以判斷「這個月有沒有正在發生」時，要用本月到目前為止已公布的週盤、日價或廠商調價，和上個月的平均水準比較。
  例如：本月豐興已公布的廢鋼週盤若比上月平均高，「北部廢鋼 → 豐興鋼筋」這條鏈的起點就已經在動；再看鋼筋週盤有沒有跟上。
- 狀態判斷（依序套用第一條符合的）：
  1. 起點本月還沒有任何新數據 → 「尚待觀察」。
  2. 起點本月有新數據，但和上月平均相比沒有明顯變動（不到 0.3%）→ 「沒有發生」，說明「起點持平，這條鏈本月沒有推力」。
  3. 起點已明顯變動，終點也朝同方向變動 → 「正在發生」。
  4. 起點已明顯變動，終點還沒有新數據 → 「尚待觀察」，說明「起點已經在動，等終點反應」，這對預測下個月特別重要。
  5. 起點已明顯變動，但終點有新數據且沒跟上或反向 → 「沒有發生」。
- 每條核對過的推理鏈都要寫進 chains，附上依據的事實編號與一句說明。
</chain_rules>

<drivers_rules>
針對 {"、".join(ITEM_KEYS)} 五項材料，從六個面向整理多空因素：{"、".join(DIMENSIONS)}。
每個因素標出方向（up 偏漲、down 偏跌、neutral 中性）、力道（1 弱、2 中、3 強）、影響期間（week 本週、month 下個月），以及依據的事實編號。沒有具體事實依據的因素，facts 留空陣列。
</drivers_rules>

<wording_rules>
研究底稿的文字會直接顯示在網站上給一般讀者看：
- 用繁體中文、完整的白話短句，專有名詞第一次出現時用括號簡短解釋。
- 提到下方提供的資料時，寫「官方數據」或來源名稱（例如台灣金屬行情網、國泰世華牌價），不要寫「題目提供」「使用者提供」「系統提供」「指定門檻」這類字眼。
- 提到 ±0.3% 這條線時，寫成「變動不到 0.3%，算是持平」。
</wording_rules>

<output_format>
只輸出一個 JSON 物件，不要有其他文字。查不到的欄位用 null 或空陣列，不要猜。絕對不可以編造數字、日期或網址。
{{
  "facts": [
    {{"id": "F1", "fact": "<一句話寫清楚的事實，含主體、數字、單位>", "date": "<事件日期 YYYY-MM-DD 或 YYYY-MM>", "type": "<公告|成交|報價|預估|傳聞>",
      "materials": ["<材料代號或 all>"], "sources": [{{"title": "<網頁標題>", "url": "<網址>"}}]}}
  ],
  "conflicts": [{{"topic": "<哪件事>", "versions": "<各家說法>", "judgment": "<判斷哪個可信與理由>"}}],
  "chains": [{{"chain": "<例如：北部廢鋼收購價 → 豐興鋼筋盤價>", "status": "<正在發生|沒有發生|尚待觀察>", "facts": ["F1"], "note": "<一句說明>"}}],
  "drivers": {{
    "<材料代號>": [{{"dimension": "<{"|".join(DIMENSIONS)}>", "factor": "<因素，一句話>", "direction": "<up|down|neutral>", "strength": <1|2|3>, "horizon": "<week|month>", "facts": ["F1"]}}]
  }},
  "gaps": ["<查了但查不到或無法確認的項目>"]
}}
</output_format>

<context>
<official_prices>
{official_prices}
</official_prices>
<fx>
{fx}
</fx>
<base_rates>
{base_rates}
</base_rates>
<verified_links>
{links}
</verified_links>
<materials>
{materials}
</materials>
<news>
{news}
</news>
</context>

<final_instructions>
完成 <topics> 的查證後，只輸出 <output_format> 規定的 JSON。重點再提醒一次：每個數字盡量兩個以上不同網站核對；報導互相矛盾要列出並判斷；推理鏈只核對歷史上成立的，並用本月已公布的週盤與上月平均比較；查不到就寫進 gaps，絕不編造；文字遵守 <wording_rules>。
</final_instructions>"""


def forecast_prompt(*, date_str: str, week_label: str, week_range: str, targets: str, official_prices: str,
                    fx: str, base_rates: str, links: str, dossier: str, materials: str, news: str,
                    memory: str, accuracy: str, item_schema: str, mode: str) -> str:
    if mode == "dossier":
        evidence_source = "研究員已完成上網查證，整理在 <research_dossier>。你沒有搜尋工具，只能依據 <context> 內的資料判斷；資料裡沒有的數字不要自己補。"
    elif mode == "offline":
        evidence_source = "今天沒有研究底稿，也無法上網。只能依據 <context> 內的官方數據、歷史基準率與新聞標題判斷；查不到的數字不要自己補，並在說明中講明依據有限。"
    else:
        evidence_source = ("今天沒有研究底稿。你可以使用網路搜尋：先查證豐興本週廢鋼與鋼筋盤價、中鋼月盤與季盤、東和型鋼價格、"
                           "美國與土耳其廢鋼、中國螺紋鋼期貨與唐山鋼胚、鐵礦砂與焦煤；同一數字盡量兩個網站核對，只有一個來源要在說明中註明。")
    return f"""<role_and_objective>
你是台灣鋼鐵與營建材料市場的首席分析師。今天是 {date_str}（台灣時間，{"週末" if week_label == "下週" else "平日"}）。
你的任務：對五項台灣鋼材的價格走勢，做出有立場、可被驗證、機率合理的判斷，並用總經理看得懂的話寫出來。
{evidence_source}
</role_and_objective>

<priorities>
規則互相衝突時，依這個順序取捨：
1. 事實正確：不編造任何數字、日期、事件；不確定就說不確定。
2. 機率合理：預測要對得起證據，不因單一新聞大幅偏離歷史常態，也不因怕錯而一律喊持平。
3. 白話好讀：遵守 <writing_rules>。
4. 精簡：在符合以上三點的前提下，越短越好。
</priorities>

<forecast_tasks>
每項材料做兩個預測：
1. week：{week_label}（{week_range}）的實際市場成交行情，相對上週的方向與幅度。台灣鋼價多由豐興每週一開盤、中鋼與東和每月調價，所以本週已公布的盤價與實際成交是最主要的依據。
2. next_month：下一期官方月均價（台灣金屬行情網公布）相對最新已公布月均價的方向與幅度。系統會在官方數據公布後自動計分：
{targets}
</forecast_tasks>

<evidence_rules>
- 起點是 <base_rates>：這個品項平常多常漲跌、漲跌多少、近三個月與去年同月怎麼走。再用查證過的事實調整；新事實不夠多、不夠強，就不要大幅偏離歷史常態。
- 證據分量：兩個以上獨立來源或正式公告的事實才能當主要依據；只有一個來源、或屬於傳聞或預估的，只能當次要參考，並在說明中直接寫「只有一家媒體報導」或「尚未證實」。
- 推理鏈：只採用 <verified_links> 中歷史上連動明顯、且研究底稿顯示「正在發生」的推理鏈；注意是同月反映還是晚一個月反映。歷史上不成立的推理不要用。
- 每項材料都要從成本、供給、需求、政策與貿易、市場情緒、季節性六個面向想過；往上和往下的力量同時存在時，要說明哪一邊比較重、為什麼。
- 研究底稿中互相矛盾的報導，採用研究員判斷較可信的版本。
- 參考 <memory>：方向與你最近一次預測不同時，必須說明是哪一則新消息造成改變；沒有新消息就不要翻轉方向。
- 參考 <accuracy>：檢討過去的誤判，並檢查自己這次是否過度自信或過度保守。
- 各項資料的月份不同（例如粗鋼產量比鋼價晚兩個月），引用時寫出正確月份。
</evidence_rules>

<calibration_rules>
- next_month 要給三種結果的機率：上漲 up（月均價變動超過 +0.3%）、持平 stable（變動在 ±0.3% 內）、下跌 down（變動超過 -0.3%），三個整數加總 100；direction 必須是機率最高的那一種。每種結果附上該情況下的幅度區間。
- 不要給 0 或 100；證據再強，也保留至少 5 的可能性給另外兩種結果。
- 機率要反映真實把握：歷史上很少變動的品項（看 <base_rates>），持平的機率本來就該高；只有證據明確時才把漲或跌拉到 70 以上。
- "stable" 只能在漲跌因素確實互相抵消時使用，並在說明中同時講出往上和往下的原因。
- change_estimate 一定是具體數字區間。
</calibration_rules>

<answer_requirements>
每項材料的回答必須包含：
- reason：100～200 字白話說明，第一句是結論。
- evidence：主要依據的研究底稿事實編號（只放在這個欄位，說明文字裡不要出現編號）。
- counterpoint：最可能讓這個判斷出錯的理由。
- watch：接下來看到什麼消息就要改變判斷。
- revision_note：與上次預測相比的變化與原因；沒變就寫「維持前次判斷」並簡述理由。
</answer_requirements>

<other_outputs>
- top_stories：讀者點開推播通知後第一眼看到的「今日鋼市頭條」。從 <news> 找出最近 3 天內與台灣鋼鐵、營建材料市場相關、被最多家不同媒體報導的事件，依關注程度列出 5～7 則。
  ids 列出報導同一事件的所有新聞編號（例如 ["N1","N4","N7"]），系統會依不同媒體家數計算熱度並重新排序，列錯或灌入不相關編號視為錯誤；
  headline 是記者式主標題（14～28 字，含具體主體與數字），subheadline 是副標題（40 字內，補充影響或背景）；
  anchor 指向網站段落：prices、materials、chart、forecast、fc-north_scrap_price、fc-billet_price、fc-fengxing_rebar_price、fc-h_beam_price、fc-csc_wire_rod_price、analysis、news；
  anchor 為 materials 時 search 填一個可在營建材料清單搜尋的關鍵字（例如「鐵礦砂」「水泥」），其他情況留空。
- headline：今天推播與電子報的主標題，像財經記者下標：18～32 字，點出今天最重要且已查證的一則動態，含具體主體與數字；不誇張、不用問句。headline_sub 用 40 字內補充第二重要的動態或對下週的判斷。
- 引用提供的資料時，稱為「官方數據」或寫出來源名稱（例如台灣金屬行情網、主計總處）；不要寫「題目提供」「使用者提供」「研究底稿」「系統」這類字眼。
</other_outputs>

{WRITING_RULES}

<output_format>
只輸出一個 JSON 物件，不要有其他文字，字串中不要用 markdown：
{{
  "exchange_rate": {{"usd_twd_estimate": <浮點數>, "impact_on_steel": "<匯率對鋼價的影響，100字內白話>"}},
  "spread_analysis": "<廢鋼→鋼胚→鋼筋→型鋼，每一段鋼廠大概賺多少、最近變多還是變少，200字內白話>",
  "monthly_trend": "<未來一個月台灣鋼市展望，200字內白話>",
  "international_outlook": "<國際鋼鐵與原物料大局，含中國、日本、韓國、美國、土耳其，300字內白話>",
  "materials_outlook": "<水泥、砂石、瀝青、木材、機電、工資等營建材料的走勢與對工程成本的影響，200字內白話>",
  "price_forecast": {{
    "items": {{
{item_schema}
    }},
    "overall_basis": "<這次預測主要看了哪些消息、哪些最重要、哪些還不確定，250字內白話>"
  }},
  "risk_factors": ["<風險1，一句白話>", "<風險2>", "<風險3>"],
  "top_stories": [{{"ids": ["<新聞編號>"], "headline": "<主標題>", "subheadline": "<副標題>", "anchor": "<段落代號>", "search": "<僅 materials 時填>"}}],
  "headline": "<記者式新聞標題，18～32字>",
  "headline_sub": "<副標，40字內>",
  "summary": "<今日市場總結，150字內白話，先講結論>",
  "confidence": "<high|medium|low>",
  "sources": [{{"title": "<實際查閱過的網頁標題>", "url": "<網址>"}}]
}}
</output_format>

<context>
<official_prices>
{official_prices}
</official_prices>
<fx>
{fx}
</fx>
<base_rates>
{base_rates}
</base_rates>
<verified_links>
{links}
</verified_links>
<research_dossier>
{dossier or "（今天沒有研究底稿）"}
</research_dossier>
<materials>
{materials}
</materials>
<news>
{news}
</news>
<memory>
{memory}
</memory>
<accuracy>
{accuracy}
</accuracy>
</context>

<final_instructions>
依 <priorities> 的順序取捨，只輸出 <output_format> 規定的 JSON。再提醒一次：從歷史基準率出發再用證據調整；主要依據必須是交叉驗證或正式公告的事實；三種情況機率加總 100；所有給讀者的文字都要符合 <writing_rules>，先講結論、白話、不用術語。
</final_instructions>"""


def item_schema(items: list[tuple[str, str, str]], targets: dict, week_label: str) -> str:
    """JSON shape of one forecast item per material, for the output_format section."""
    rows = []
    for key, _, unit in items:
        tgt = targets.get(key, {})
        rows.append(
            f'      "{key}": {{\n'
            f'        "week": {{"direction": "<up|down|stable>", "change_estimate": "<{week_label}實際成交價的變動幅度，{unit}>", "reason": "<100~200字白話>"}},\n'
            f'        "next_month": {{"direction": "<up|down|stable>", "change_estimate": "<{tgt.get("target_month", "下一期")} 月均價相對 {tgt.get("baseline_month", "最新一期")} 的變動，{unit}>", "reason": "<100~200字白話>",\n'
            f'          "scenarios": {{"up": {{"prob": <整數>, "range": "<上漲時的幅度，{unit}>"}}, "stable": {{"prob": <整數>, "range": "<持平時的幅度>"}}, "down": {{"prob": <整數>, "range": "<下跌時的幅度>"}}}}}},\n'
            f'        "evidence": ["<事實編號>"],\n'
            f'        "counterpoint": "<最可能讓判斷出錯的理由>",\n'
            f'        "watch": "<看到什麼消息就要改判斷>",\n'
            f'        "revision_note": "<與上次預測相比的變化與原因>"\n'
            f'      }}'
        )
    return ",\n".join(rows)
