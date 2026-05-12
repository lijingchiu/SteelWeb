# 台灣鋼鐵市場每日分析網站

每日自動爬取 [steelnews.com.tw](https://steelnews.com.tw) 新聞，透過 OpenRouter 免費 AI 模型分析台灣廢鋼、鋼筋、型鋼市場行情，並自動更新至 GitHub Pages。

## 功能特色

- **每日自動化**：GitHub Actions 每天早上 8:00（台灣時間）自動執行
- **AI 分析**：使用 OpenRouter 免費模型（LLaMA 3.3 70B）分析新聞
- **完整報告**：公告價預測、利差試算、本週走勢、國際大局觀、風險因素
- **價格走勢圖**：Chart.js 繪製近 30 天歷史走勢
- **匯率影響**：考慮 USD/TWD 匯率貶值對鋼價的影響

## 快速設定

### 1. Fork 或 Clone 此倉庫

```bash
git clone https://github.com/lijingchiu/steelweb.git
```

### 2. 設定 OpenRouter API Key

1. 前往 [openrouter.ai](https://openrouter.ai) 註冊帳號（免費）
2. 取得 API Key
3. 在 GitHub 倉庫 → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**
4. 名稱：`OPENROUTER_API_KEY`，值貼上你的 API Key

### 3. 啟用 GitHub Pages

1. 前往倉庫 **Settings** → **Pages**
2. Source 選擇：**Deploy from a branch**
3. Branch 選擇：`main`，目錄：`/ (root)`
4. 點擊 **Save**
5. 等待約 1 分鐘後，網站將發佈於 `https://<你的帳號>.github.io/steelweb/`

### 4. 手動觸發測試

1. 前往 **Actions** → **Daily Steel Price Analysis**
2. 點擊 **Run workflow** → **Run workflow**
3. 等待約 2-3 分鐘完成
4. 重新整理網站即可看到最新分析

## 檔案結構

```
├── index.html                    # 主要儀表板頁面
├── assets/
│   ├── style.css                 # 樣式（深色鋼鐵工業主題）
│   └── app.js                    # 前端資料載入與圖表邏輯
├── data/
│   ├── latest.json               # 最新分析結果（每日更新）
│   ├── chart-data.json           # 歷史價格數據（用於圖表）
│   ├── history-index.json        # 歷史日期索引
│   └── history/
│       └── YYYY-MM-DD.json       # 每日歷史存檔
├── scripts/
│   ├── analyze.py                # 主要分析腳本
│   └── requirements.txt          # Python 依賴套件
└── .github/
    └── workflows/
        └── daily-analysis.yml    # GitHub Actions 排程工作流程
```

## 分析內容說明

| 項目 | 說明 |
|------|------|
| 廢鋼 | 電爐廢鋼收購報價估計與預測 |
| 鋼筋 | 螺紋鋼（Rebar）現貨報價與走勢 |
| 型鋼 | H 型鋼等結構型鋼報價 |
| 利差試算 | 廢鋼→成品鋼加工利差分析 |
| 本週走勢 | 未來 5-7 天價格預測 |
| 國際大局觀 | 中、日、韓、美鋼鐵市場動態 |
| 風險因素 | 需關注的市場風險提示 |

## 使用的 AI 模型

預設使用 OpenRouter 免費模型：`meta-llama/llama-3.3-70b-instruct:free`

如需更換模型，修改 `scripts/analyze.py` 中的 `MODEL` 變數即可。

> **免責聲明**：本報告由 AI 自動生成，僅供參考，不構成任何投資建議。
