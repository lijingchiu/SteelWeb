# 台灣鋼鐵市場每日分析網站

每日自動爬取 [steelnews.com.tw](https://steelnews.com.tw) 新聞，透過 OpenRouter 免費 AI 模型分析台灣廢鋼、鋼筋、型鋼市場行情，並自動更新至 GitHub Pages。

## 功能特色

- **每日自動化**：GitHub Actions 每天早上 8:00（台灣時間）自動執行
- **AI 分析**：使用 OpenRouter 免費模型（LLaMA 3.3 70B）分析新聞
- **完整報告**：公告價預測、利差試算、本週走勢、國際大局觀、風險因素
- **價格走勢圖**：Chart.js 繪製近 30 天歷史走勢
- **匯率影響**：考慮 USD/TWD 匯率貶值對鋼價的影響

## 快速設定

### 1. 設定 OpenRouter API Key（免費）

1. 前往 [openrouter.ai](https://openrouter.ai) 註冊帳號
2. 取得 API Key
3. 在 GitHub 倉庫 → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**
4. 名稱：`OPENROUTER_API_KEY`，值貼上你的 API Key

### 2. 啟用 GitHub Pages

1. 前往倉庫 **Settings** → **Pages**
2. Source 選擇：**Deploy from a branch**
3. Branch 選擇：`main`，目錄：`/ (root)`
4. 點擊 **Save**
5. 等待約 1 分鐘後，網站將發佈於 `https://lijingchiu.github.io/steelweb/`

### 3. 手動觸發測試（選用）

1. 前往 **Actions** → **Daily Steel Price Analysis**
2. 點擊 **Run workflow** → **Run workflow**
3. 等待約 2-3 分鐘完成

## 每日自動化流程

```
每天 08:00 台灣時間
    ↓
GitHub Actions 觸發
    ↓
爬取 steelnews.com.tw 新聞
    ↓
送交 OpenRouter (llama-3.3-70b-instruct:free)
    ↓
AI 分析回傳 JSON（價格預測、利差、走勢、國際觀）
    ↓
更新 data/latest.json + data/chart-data.json
    ↓
自動 commit + push → GitHub Pages 即時更新
```

## 檔案結構

```
├── index.html                    # 主要儀表板頁面
├── assets/
│   ├── style.css                 # 樣式
│   └── app.js                    # 前端邏輯
├── data/
│   ├── latest.json               # 最新分析（每日更新）
│   ├── chart-data.json           # 歷史圖表數據
│   ├── history-index.json        # 歷史索引
│   └── history/YYYY-MM-DD.json   # 每日存檔
├── scripts/
│   ├── analyze.py                # 分析腳本
│   └── requirements.txt
└── .github/workflows/
    └── daily-analysis.yml        # 排程工作流程
```

> **免責聲明**：本報告由 AI 自動生成，僅供參考，不構成任何投資建議。
