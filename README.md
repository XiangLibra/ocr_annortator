# 🧠 OCR Insight Editor

整合 **OCR 辨識、AI 自動糾錯、結構化資料擷取、Google Sheets 匯出、自我訓練** 的智慧文件處理系統。

後端：FastAPI + Tesseract + Ollama（本地 LLM）  
前端：Vue 3（CDN）+ Konva.js 畫布標註

---

## ✨ 功能一覽

| 功能 | 說明 |
|------|------|
| 📄 OCR 辨識 | 上傳 PDF / 圖片，支援繁體中文、英文、自訓練模型 |
| ✏️ 畫布標註 | 在 Konva 畫布上直接拖曳、調整、新增 OCR 文字框 |
| 🤖 AI 自動糾錯 | EvaluatorAgent 評分 → CorrectorAgent 修正，一鍵採用 |
| 🔍 結構化擷取 | 自動從 OCR 結果提取公司名稱、地址、統編、聯絡人等欄位 |
| 📊 Google Sheets 匯出 | OAuth 授權後，直接將擷取欄位寫入指定試算表 |
| 🧠 訓練資料累積 | 每次人工修正自動儲存原文 / 修正對到 MongoDB |
| 🏋️ Tesseract 自訓練 | 累積足夠資料後，一鍵觸發 LSTM fine-tune，產生自訂模型 |
| 🗂 模型版本管理 | 歷史版本列表、一鍵切換啟用特定版本 |
| 🔀 多代理比對 | 多份文件 AI 比對分析 + 聊天問答 |
| 📚 歷史紀錄 | 所有 OCR 紀錄可查詢、重新比對、下載 |

---

## 🧩 專案架構

```
ocr_annortator/
├── app.py                  # FastAPI 主後端
├── llm_processor.py        # Ollama LLM 呼叫封裝
├── tesseract_trainer.py    # Tesseract LSTM fine-tune pipeline
├── setup_gsheet_auth.py    # Google OAuth 首次授權腳本
├── pyproject.toml          # uv 依賴設定
│
├── backend/
│   └── ocr_core.py         # Tesseract OCR 核心（支援自訓練模型）
│
├── frontend-vue/
│   ├── index.html          # Vue 3 + Konva 前端（免建置）
│   └── script.js           # 前端邏輯
│
├── output/                 # 自訓練模型輸出目錄
│   ├── chi_tra_custom.traineddata        # 目前啟用的自訓練模型
│   ├── chi_tra_custom_v<版本ID>.traineddata  # 版本備份
│   └── chi_tra_vert.traineddata          # 依賴語系
│
└── training_workspace/     # 訓練工作目錄（自動產生）
    ├── gt/                 # 行圖片 + .gt.txt
    ├── lstmf/              # .lstmf 訓練檔
    ├── model/              # checkpoint 檔
    └── tessdata_local/     # 訓練用 tessdata
```

---

## 🧰 環境需求

- Python 3.10+
- [uv](https://github.com/astral-sh/uv)
- Tesseract OCR 5.x（含繁體中文語言包）
- MongoDB（本地或遠端）
- Ollama（本地 LLM，建議 llama3.2:3b）
- RTX 3060 12GB 以上（Ollama 推論用）

---

## ⚙️ 安裝與啟動

### Step 1. 安裝系統依賴

```bash
# Tesseract OCR
sudo apt install tesseract-ocr tesseract-ocr-chi-tra

# MongoDB
sudo apt install mongodb
sudo systemctl start mongodb

# Ollama
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.2:3b
```

### Step 2. 安裝 Python 依賴

```bash
# 安裝 uv（若尚未安裝）
curl -LsSf https://astral.sh/uv/install.sh | sh

cd ocr_annortator
uv sync
```

### Step 3. 啟動後端

```bash
# 啟動 Ollama（若尚未在背景執行）
nohup ollama serve > ollama.log 2>&1 &

# 啟動 FastAPI
uv run uvicorn app:app --reload --port 8000

# 或背景執行
fuser -k 8000/tcp; nohup uv run uvicorn app:app --port 8000 > app.log 2>&1 &
```

後端位址：`http://127.0.0.1:8000`  
API 文件：`http://127.0.0.1:8000/docs`

### Step 4. 開啟前端

直接用瀏覽器開啟 `frontend-vue/index.html`，或啟動本地伺服器：

```bash
cd frontend-vue
python -m http.server 4173
# 開啟 http://127.0.0.1:4173
```

> 前端會自動連向同主機的 8000 埠，遠端部署時可在頁面右上角調整 API 位址。

---

## 🤖 AI 自動糾錯

OCR 辨識完成後，點「一鍵 AI 糾錯」：

1. **EvaluatorAgent**：評估 OCR 品質，給出 0–10 分與錯誤清單
2. **CorrectorAgent**：根據評估結果生成修正版本
3. 左欄顯示原始 OCR，右欄顯示 AI 建議（可編輯）
4. 點「採用 AI 建議」確認後，修正資料自動存入訓練資料庫

使用的 LLM：Ollama 本地模型（預設 `llama3.2:3b`）

---

## 📊 Google Sheets 匯出

### 首次授權

```bash
uv run python setup_gsheet_auth.py
```

按提示完成 OAuth 授權，`token.json` 會儲存在專案目錄。

### 使用方式

OCR 完成後點「擷取欄位」→「匯出至 Google Sheets」，系統自動填入：

- 公司名稱、地址、統一編號、聯絡人、電話、傳真、稅務

> 需先在 Google Cloud Console 啟用 Sheets API 與 Drive API。

---

## 🏋️ Tesseract 自訓練

### 訓練流程

每次人工修正 OCR 結果並儲存，系統自動累積訓練資料（`ocr_training_pairs` collection）。

累積達門檻後，在「歷史紀錄」頁的訓練狀態面板點「🚀 觸發訓練」，或手動執行：

```bash
uv run python tesseract_trainer.py
```

**Pipeline 步驟：**

1. 從 MongoDB 讀取訓練資料對
2. 依 y 座標分群切割行圖片，生成 `.gt.txt` ground truth
3. 生成 WordStr `.box` 檔 → 執行 `tesseract lstm.train` → 產生 `.lstmf`
4. `combine_tessdata -e` 提取原始 LSTM
5. `lstmtraining` 進行 fine-tune（預設 400 次迭代）
6. 將最佳 checkpoint 組合回 `chi_tra_custom.traineddata`
7. 版本 metadata 寫入 MongoDB，備份帶版本號的 traineddata

**輸出模型位置：**`output/chi_tra_custom.traineddata`

**手動測試模型：**

```bash
TESSDATA_PREFIX=/path/to/ocr_annortator/output \
  tesseract input.png out -l chi_tra_custom
```

### tessdata 依賴設定

```bash
# 複製語系檔到訓練用目錄
mkdir -p training_workspace/tessdata_local
cp /usr/share/tesseract-ocr/5/tessdata/chi_tra.traineddata training_workspace/tessdata_local/
cp /usr/share/tesseract-ocr/5/tessdata/configs training_workspace/tessdata_local/ -r

# chi_tra_vert（從 tesseract-ocr/tessdata GitHub 下載）
wget -O training_workspace/tessdata_local/chi_tra_vert.traineddata \
  https://github.com/tesseract-ocr/tessdata/raw/main/chi_tra_vert.traineddata
```

---

## 🗂 模型版本管理

在「歷史紀錄」頁的「OCR 模型版本管理」面板：

- 查看所有歷史訓練版本（訓練時間、筆數、最佳 Loss、迭代次數）
- 綠色「啟用中」標示目前使用的版本
- 點「切換啟用」可將任一舊版本設為目前使用的 `chi_tra_custom` 模型

---

## 🔌 主要 API

| Method | Endpoint | 說明 |
|--------|----------|------|
| POST | `/api/ocr` | 上傳檔案進行 OCR |
| POST | `/api/auto_correct` | AI 自動糾錯 |
| POST | `/api/extract` | 結構化欄位擷取 |
| POST | `/api/export/gsheet` | 匯出至 Google Sheets |
| POST | `/api/training/add` | 新增訓練資料對 |
| GET | `/api/training/status` | 查詢訓練資料累積狀態 |
| POST | `/api/training/trigger` | 觸發模型訓練 |
| GET | `/api/ocr/models` | 查詢可用 OCR 模型清單 |
| GET | `/api/ocr/model_versions` | 查詢自訓練版本歷史 |
| POST | `/api/ocr/model_versions/activate` | 切換啟用指定模型版本 |

---

## 🗄 MongoDB Collections

| Collection | 說明 |
|------------|------|
| `ocr_records` | OCR 辨識結果（含頁面圖片路徑、word bbox） |
| `ocr_batches` | 批次上傳紀錄 |
| `ocr_training_pairs` | 訓練資料對（原始 OCR ↔ 人工修正） |
| `ocr_model_versions` | 自訓練模型版本 metadata |

---

## 🖥 Tab 說明

**OCR 標註**
- 上傳辨識（支援動態選擇 OCR 模型）
- Konva 畫布標註（拖曳框線、新增/刪除字詞）
- AI 自動糾錯
- 多代理文件比對與聊天問答

**歷史紀錄**
- OCR 訓練資料狀態（累積進度 + 觸發訓練按鈕）
- OCR 模型版本管理（版本歷史 + 切換啟用）
- 歷史檔案查詢、比對、下載
