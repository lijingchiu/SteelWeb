# 各類施工規範／公共工程施工綱要規範（工程會體系）— 實測備忘

- 列表頁 `pcic.pcc.gov.tw/pwc-web/service/tec0301`：經 Google DoH 解析可達、HTTP 200，
  但**静态 HTML 僅為前端 shell（無直連）**，列表內容由前端 JS 呼叫 API 載入
  （實測 API 端點回 401），屬正常现象，依指示照實回報；列表頁 HTML 已抓存留証：
  [工程施工規範網（列表頁…）_7cd92b.html](工程施工規範網（列表頁，JS 動態；静态 HTML 無直連，屬正常）_7cd92b.html)（附 .txt）。
- 工程會**靜態下載端點可直連**（實測樣本，公開免費）：
  [公共工程技術資料庫及以公共工程推廣循環經濟之作法…_8f6faf.pdf](公共工程技術資料庫及以公共工程推廣循環經濟之作法（工程會靜態下載端點實測樣本）_8f6faf.pdf)（附 .txt）。
- `www.pcc.gov.tw` 公開爬蟲（列表頁 JS、既有爬蟲自 `upload/` 直連成功落檔於 02 目錄者非本 shard 產出）；
  `tcsj`／`tycp`／`attach` 子站中僅 `attach.pcc.gov.tw` 可經 DoH 解析。
- 公共工程施工綱要規範（90% 等）正式電子檔經 JS 列表後端提供，無可驗證之靜態直連，
  以官方列表頁為連結：https://pcic.pcc.gov.tw/pwc-web/service/tec0301
- 逐筆機器可讀明細見 [`../../00_索引/shard_01.jsonl`](../../00_索引/shard_01.jsonl)。
