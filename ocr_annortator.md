# 🧠 OCRInsight LLM Match

這是一個整合 **前端 OCR 標註介面（React + Vite）** 與 **後端 OCR / LLM 分析系統（FastAPI）** 的專案。

使用者可：
- 上傳 PDF / 圖片。
- 透過後端進行 OCR 辨識。
- 在前端介面中以紅框顯示 OCR 結果並可直接編輯。
- 儲存修正、比較差異，並匯出成 ZIP 檔（包含文字與影像）。

---

## 🧩 專案架構

OCRInsight-LLM-match/
├── api/ # FastAPI 後端
│ ├── api.py # 主後端程式
│ └── requirements.txt # 後端依賴
├── ocr-annotator/ # React + Vite 前端
│ ├── src/
│ ├── package.json
│ └── vite.config.ts
└── README.md



---

## 🧰 環境需求

- **Python 3.10+**
- **Node.js 18+**
- **npm 或 yarn**
- **Tesseract OCR** (可選)
- **Linux / macOS / WSL** 環境

---

## ⚙️ 安裝步驟

### 1️⃣ 後端安裝（FastAPI）
```bash
cd api
pip install -r requirements.txt

```
若沒有 requirements.txt，可以安裝以下常用套件：
```
pip install fastapi uvicorn python-multipart pillow pytesseract
```

2️⃣ 前端安裝（Vite + React）

``` bash
cd ocr-annotator
npm install
```


啟動方式
🧩 Step 1. 啟動後端 FastAPI

```bash

cd api
uvicorn api:app --reload --port 8000

```
後端將會運行在：

http://127.0.0.1:8000

可透過 Swagger 檢視 API：

http://127.0.0.1:8000/docs


🧩 Step 2. 啟動前端 Vite

```bash
cd ocr-annotator
npm run dev
```

前端預設運行在：

http://127.0.0.1:5173




