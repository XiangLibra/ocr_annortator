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
├── backend/ # FastAPI 後端
│ ├── api.py # 主後端程式
│ └── pyproject.toml # 使用 uv 管理的依賴設定
├── ocr-annotator/ # React + Vite 前端
│ ├── src/
│ ├── package.json
│ └── vite.config.ts
└── README.md



---

## 🧰 環境需求

- **Python 3.10+**
- **[uv](https://github.com/astral-sh/uv)**（取代 pipenv / venv）
- **Node.js 18+**
- **npm 或 yarn**
- **Tesseract OCR** (可選)
- **Linux / macOS / WSL** 環境

---

## ⚙️ 安裝與啟動步驟

### 🧱 Step 1. 後端（FastAPI + uv）



1️⃣ 安裝 uv

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh

```

安裝完成後重啟終端機，確認版本：

```bash
uv --version

```



2️⃣ 初始化與安裝依賴

```bash
uv init
```

指定pyhton版本3.10
```bash
uv python install 3.10
```


```bash
uv add fastapi uvicorn python-multipart pillow pytesseract
```
或是直接同步環境就好
```bash
uv sync
```
3️⃣ 啟動後端伺服器
```bash
uv run uvicorn app:app --reload --port 8000
```

後端將運行於：

http://127.0.0.1:8000

可透過 Swagger 檢視 API：

http://127.0.0.1:8000/docs

## 也可以將網站運行到終端後台來使用（可選）
```bash
fuser -k 8000/tcp; nohup uv run uvicorn app:app --port 8000 > app.log 2>&1 &
```


💡 若需 OCR 支援
```bash
sudo apt install tesseract-ocr
sudo apt install tesseract-ocr-chi-tra   # 繁體中文語言包
```



### 🟢 新前端：Vue + CDN（免建置）

不想用 React？在 `frontend-vue/index.html` 提供一份以 Vue 3（CDN 版）+ Konva 的前端，直接打開即可使用，免安裝依賴。

1. 先啟動 FastAPI 後端（預設 http://127.0.0.1:8000）。
2. 任選方式開啟前端：
   - 直接用瀏覽器打開 `frontend-vue/index.html`，或
   - 用簡單的本地伺服器：
     ```bash
     cd frontend-vue
     python -m http.server 4173
     # 打開 http://127.0.0.1:4173
     ```
3. 頁面右上角可調整 API 位址，預設指向 `http://127.0.0.1:8000`。

功能與 React 版一致：上傳 PDF/影像進行 OCR、檢視/編輯紅框文字、拖曳與縮放框線、加入新框、儲存修正、查看差異與下載包含 TXT+影像的 ZIP 匯出。
