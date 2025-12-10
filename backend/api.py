# backend/api.py
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from typing import List, Dict, Any
import uuid, os, json

from ocr_core import run_ocr_on_file

LANG_MAP = {
    "繁體中文": "chi_tra",
    "English": "eng"
}

app = FastAPI(title="OCRInsight API")

# CORS：開放本機前端（可依需要限制網域）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 開發階段先全開
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STORE: Dict[str, Any] = {}
OUTPUT_DIR = os.path.join(os.getcwd(), "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# 靜態前端（Vue + CDN），直接掛在根路徑
FRONT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend-vue"))
if os.path.isdir(FRONT_DIR):
    app.mount("/static", StaticFiles(directory=FRONT_DIR), name="static")

    @app.get("/", include_in_schema=False)
    async def index():
        return FileResponse(os.path.join(FRONT_DIR, "index.html"))

@app.post("/api/ocr")
async def ocr(files: List[UploadFile] = File(...),
              language: str = Form("繁體中文")):
    lang_code = LANG_MAP.get(language, "chi_tra")
    results = []
    for f in files:
        file_id = str(uuid.uuid4())
        content = await f.read()
        ocr_result = run_ocr_on_file(content, f.filename, lang_code)
        payload = {
            "fileId": file_id,
            "filename": f.filename,
            **ocr_result
        }
        STORE[file_id] = payload
        results.append(payload)
    return {"items": results}

@app.post("/api/save")
async def save(fileId: str = Form(...),
               correctedFullText: str = Form(None),
               wordEdits: str = Form(None)):
    """
    wordEdits: JSON 字串，如:
      [{"wordId":"w12","newText":"臺灣"}]
    """
    record = STORE.get(fileId)
    if not record:
        return {"ok": False, "msg": "fileId not found"}

    if correctedFullText is not None:
        record["correctedFullText"] = correctedFullText

    if wordEdits:
        edits = json.loads(wordEdits)
        # 逐頁逐詞替換
        word_map = {w["id"]: w
                    for p in record["pages"]
                    for w in p["words"]}
        for e in edits:
            wid = e.get("wordId")
            new_text = e.get("newText", "")
            if wid in word_map:
                word_map[wid]["text"] = new_text

    # 簡單存檔（可換成 DB / 產生 PDF / diff）
    out_path = os.path.join(OUTPUT_DIR, f"{fileId}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)

    return {"ok": True, "path": out_path}
