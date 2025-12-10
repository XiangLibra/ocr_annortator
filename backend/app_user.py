import streamlit as st
from PIL import Image
import fitz, io, os, time, pytesseract
import ollama              # 本地 LLM
import llm_processor        # 你之前寫好的檔案
import re
from io import BytesIO
from docx import Document
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
import textwrap
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
import textwrap
import fitz, io, os, time, pytesseract, difflib
import streamlit.components.v1 as components
import difflib
from PIL import ImageDraw          # ⬅️ 新增
from PIL import ImageFont
import base64, json
from io import BytesIO






# ───────────────────────── OCR 助手 ────────────────────────── #
def initialize_ocr_models(*_):  # 佔位
    return {"Tesseract": None}
def perform_ocr(_, __, img, lang):  # 單一 Tesseract
    return pytesseract.image_to_string(img, lang=lang)
# ──────────────────────────────────────────────────────────── #

st.set_page_config(page_title="OCRInsight Multi-File", layout="wide")
st.title("🤖 Multi-Agent OCR 文件比對系統")

# ─── Sidebar • OCR 基本 ─── #
st.sidebar.header("OCR 設定")
device     = st.sidebar.radio("運算裝置", ["CPU", "GPU (CUDA)"])
language   = st.sidebar.selectbox("語系", ["繁體中文", "English"])
lang_code  = {"繁體中文": "chi_tra", "English": "eng"}[language]
ocr_models = st.sidebar.multiselect("OCR 引擎", ["Tesseract"], default=["Tesseract"])
save_output = st.sidebar.checkbox("OCR / LLM 輸出存檔", value=False)
# ─── Sidebar • Agent Hub ─── #
st.sidebar.header("Agent Hub")
if "agents" not in st.session_state:
    st.session_state.agents = {}
with st.sidebar.expander("➕ 新增 Agent"):
    new_name = st.text_input("角色名稱")
    new_desc = st.text_area("System Prompt")
    models = ["llama3.2:3b", "llama3.2:1b","llama3.2:1b", "gemma3:4b","deepseek-r1:1.5b","deepseek-r1:7b","deepseek-r1:8b"]
    new_model = st.selectbox("模型", models, index=0)
    new_temp  = st.slider("temperature", 0.0, 1.2, 0.0, 0.1)
    if st.button("建立 / 覆蓋 Agent") and new_name:
        st.session_state.agents[new_name] = {
            "system": "agents name:"+new_name+"System Prompt:"+new_desc or "你是有幫助的助理。",
            "model": new_model,
            "temp":  new_temp,
        }
        st.success(f"Agent「{new_name}」已建立")

# 預設 summarizer
if not st.session_state.agents:
    st.session_state.agents["Summarizer"] = {
        "system": "請摘要輸入內容。",
        "model":  "llama3.2:3b",
        "temp":   0.0,
    }




agent_name = st.sidebar.selectbox("使用 Agent", list(st.session_state.agents))
agent_cfg  = st.session_state.agents[agent_name]

# ─── 上傳多檔 ─── #
files = st.file_uploader("上傳 PDF / 圖檔（可多選）",
                         type=["pdf","png","jpg","jpeg"],
                         accept_multiple_files=True)

def get_chinese_font(size=20):
    # 常見 Linux 中文字型安裝位置
    possible_paths = [
        "/usr/share/fonts/truetype/TaipeiSansTCBeta-Regular.ttf"
    ]
    for path in possible_paths:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    # fallback
    return ImageFont.load_default()

if files:
    ocr_texts = {}         # {filename: ocr文字}
    page_imgs = {}         # {filename: [PIL images]}
    ocr_boxes   = {}               # ⬅️ 新增：{filename: [ (page_idx, box_list) ]}

    with st.spinner("OCR 處理中…"):
        for f in files:
            # 讀成影像
            if f.type == "application/pdf":
                pdf = fitz.open(stream=f.read(), filetype="pdf")
                imgs = [Image.open(io.BytesIO(p.get_pixmap().tobytes("png")))
                        for p in pdf]
                pdf.close()
            else:
                imgs = [Image.open(f)]



            page_imgs[f.name] = imgs
            page_boxes = []        # ⬅️ 儲存每頁的 bounding box
            text = ""
            for pg, img in enumerate(imgs, 1):
                # ① 取得 OCR 文字
                text += perform_ocr(None, None, img, lang_code)

                # ② 取得 OCR 位置資料
                data = pytesseract.image_to_data(
                    img, lang=lang_code, output_type=pytesseract.Output.DICT
                )
                boxes = []

                n = len(data["text"])
                for i in range(n):
                    if int(data["conf"][i]) > 10 and data["text"][i].strip():
                        x, y, w, h = (
                            data["left"][i],
                            data["top"][i],
                            data["width"][i],
                            data["height"][i],
                        )
                        text_small=data["text"][i]
                        boxes.append((x, y, w, h,text_small))
                page_boxes.append(boxes)
            ocr_boxes[f.name] = page_boxes   # ⬅️ 存起來
            ocr_texts[f.name] = text
    st.success("OCR 完成 ✅")

    corrected_texts = {}

   
    corrected_texts = {n: ocr_texts[n] for n in page_imgs.keys()}   # 預設
    for name, imgs in page_imgs.items():
        with st.expander(f"📄 {name}（共 {len(imgs)} 頁）"):
            for idx, img in enumerate(imgs, 1):
                st.write(f"── 原圖：Page {idx}")
                st.image(img, use_container_width=True)

                # ③ 在影像上畫紅框
                overlay = img.convert("RGBA")
                draw    = ImageDraw.Draw(overlay)
                page_texts = []      # 存每一框的文字，待會顯示在側邊
                for (x, y, w, h,text) in ocr_boxes[name][idx-1]:
                    draw.rectangle([(x, y), (x+w, y+h)], outline="red", width=2)
                    font = get_chinese_font(size=20)  # 每張圖只需要 call 一次也可以
                    draw.text((x, y-20), text, font=font, fill="red")
                    # draw.text((x, y-12), text, fill="red")  # y-12 讓文字在框上方

                st.write(f"── 標註後：Page {idx}")
                st.image(overlay.convert("RGB"), use_container_width=True)

            # ④ 校正文字
            edited = st.text_area(
                f"🔎 校正 OCR 結果：{name}",
                value=corrected_texts[name],
                height=200,
                key=f"ocr_edit_{name}"
            )
            corrected_texts[name] = edited


    if st.button("💾 儲存校正結果", key="save_correct"):
        st.session_state["ocr_corrected_texts"] = corrected_texts.copy()
        st.success("校正結果已儲存！以下為差異高亮比較：")

        # 建立 HtmlDiff（注意參數名稱 tabsize）
        hd = difflib.HtmlDiff(tabsize=4, wrapcolumn=80)

        for name in page_imgs.keys():
            orig = ocr_texts[name].splitlines()
            corr = corrected_texts[name].splitlines()

            st.write(f"### {name} 差異比較")
            html_table = hd.make_table(
                orig, corr,
                fromdesc="原始 OCR",
                todesc="校正後 OCR",
                context=True,      
                numlines=5
            )

            # 插入自訂 CSS：強調 header row，並微調新增/刪除行顏色
            custom_style = """
    <style>
    table.diff { width:100%; border-collapse: collapse; }
    .diff_header { background:#fff2cc !important; font-weight:bold; }

    /* 刪除行 (原有但被移除) */
    .diff_sub { background:#f8d4d4 !important; }
    /* 新增行 (校正後才有) */
    .diff_add { background:#d4f8d4 !important; }
    /* ⚡ 取代行內文字 (a → b) */
 
    .diff_chg { background: #fff59d !important; }

    /* 其餘 */
    .diff_next { background:#f0f0f0 !important; }
    table.diff, table.diff th, table.diff td { border:1px solid #ccc; }
    </style>

    """
            # 最終嵌入
            components.html(custom_style + html_table, height=400, scrolling=True)



    # 在送入 LLM 前，先選出最終要用的文字來源
    texts_to_use = st.session_state.get("ocr_corrected_texts", ocr_texts)

    # ───────── Task 選擇 ───────── #
    task = st.radio("選擇任務", ["摘要每份文件", "比較兩份文件"])
    if task == "比較兩份文件" and len(files) < 2:
        st.warning("請至少上傳兩個檔案才能比較")
    else:
        if task == "比較兩份文件":
            cols = list(texts_to_use.keys())  # ← 這裡改成用 texts_to_use
            col1, col2 = st.columns(2)
            with col1:
                f1 = st.selectbox("文件 A", cols, key="cmp1")
            with col2:
                options_b = [name for name in cols if name != f1]
                f2 = st.selectbox("文件 B", options_b, key="cmp2")
            if f1 == f2:
                st.error("A 與 B 不可相同")
                st.stop()

        if st.button("🚀 交給 Agent"):
            # 建立 prompt 時，都改用 texts_to_use 而非 ocr_texts
            if task == "摘要每份文件":
                prompt = "請逐份文件摘要重點：\n\n"
                for n, _ in texts_to_use.items():
                    prompt += f"### {n}\n{texts_to_use[n]}\n\n"
            else:
                prompt = (
                    f"請比較以下兩份文件的差異與共同點：\n\n"
                    f"--- {f1} ---\n{texts_to_use[f1]}\n\n"
                    f"--- {f2} ---\n{texts_to_use[f2]}\n\n"
                )

            # LLM 呼叫
            with st.spinner("Agent 思考中…"):
                res = llm_processor.process_with_llm(
                    model=agent_cfg["model"],
                    system_prompt=agent_cfg["system"],
                    user_prompt=prompt,
                    temperature=agent_cfg["temp"]
                )
                # 1.2 存到 session_state，让页面刷新后还能保留
            st.session_state["last_llm_response"] = res
            st.session_state["last_llm_prompt"]   = prompt
            st.subheader("🎯 Agent 回應")
            st.text_area("Result", res, height=300)
            # 建立 chat_history
            # st.session_state.chat_history = [
            #     {"role":"system","content":agent_cfg["system"]},
            #     {"role":"assistant","content":res}
            # ]


            st.session_state.chat_history = [
                {"role":"system",   "content": agent_cfg["system"]},
                {"role":"user",     "content": prompt},
                {"role":"assistant","content": res},
            ]
            st.session_state.chat_agent = agent_name
            st.success("進入對話模式👇")

        # ─────── 永远渲染：只要有 last_llm_response，就显示原始 & 校正區 ───────
        if "last_llm_response" in st.session_state:
            res = st.session_state["last_llm_response"]

            st.subheader("🎯 原始 Agent 回應（只讀）")
            st.text_area("orig_llm", value=res, height=200, disabled=True)

            st.subheader("✏️ 校正 Agent 回應（請標記錯誤並修改）")
            corrected_response = st.text_area(
                "edit_llm",
                value=res,
                height=200,
                key="llm_edit_area"
            )

            if st.button("✅ 確認校正回應", key="save_llm_feedback"):
                # 把用户校正的结果存起来
                st.session_state["llm_corrected_response"] = corrected_response
                st.success("你的校正已儲存，下次我會參考這份回饋！")
                    # 2. 同步把這段校正視為「用戶訊息」加入 chat_history
                if "chat_history" not in st.session_state:
                    st.session_state.chat_history = []
                st.session_state.chat_history.append({
                    "role": "user",
                    "content": f"【校正回應】\n{corrected_response}"
                })



            else:
                system = agent_cfg["system"]

def sanitize_for_docx(s: str) -> str:
    # 保留 \n、\t；移除其余控制字符
    return re.sub(r'[\x00-\x08\x0B-\x0C\x0E-\x1F]', '', s)


# ❶ Word：把整段對話組成 markdown 字串後一次寫入
def export_docx_markdown(history):
    md_lines = []
    for m in history[1:]:                             # 跳過 system
        role = "**User**" if m["role"] == "user" else "**Assistant**"
        md_lines.append(f"{role}: {m['content']}")
        md_lines.append("")                           # 空行
    md_text = "\n".join(md_lines)

    # 先 sanitize 掉非法 XML 字符
    md_text = sanitize_for_docx(md_text)
    print("md_text為",md_text)



    doc = Document()
    doc.add_paragraph(md_text)                        # 直接貼整段 Markdown
    buf = BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf

# ❷ PDF：使用中文字體避免亂碼

# 註冊內建 CJK 字型
pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))

def export_pdf_chinese(history):
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    c.setFont("STSong-Light", 11)   # 用內建字型
    w, h = letter
    y = h - 72
    for m in history[1:]:
        text = f"{m['role'].title()}: {m['content']}"
        for line in textwrap.wrap(text, 88):
            c.drawString(40, y, line)
            y -= 15
            if y < 50:
                c.showPage()
                c.setFont("STSong-Light", 11)
                y = h - 72
    c.save()
    buf.seek(0)
    return buf


#────────── Chat 介面（永遠顯示，若已建立對話） ──────────#
if st.session_state.get("chat_history") and \
   st.session_state.get("chat_agent") == agent_name:

    st.divider()
    st.subheader("💬 與 Agent 對話")
    id_count=1
    # 顯示歷史訊息
    for msg in st.session_state.chat_history[1:]:  # 不顯示 system
        st.chat_message(msg["role"]).write(msg["content"])
        
        col1, col2, _ = st.columns([1,1,8])
        pdf_key  = f"download_pdf_{agent_name}_{id_count}"
        docx_key = f"download_word_{agent_name}_{id_count}"
        with col2:
            st.download_button(
                "📄 下載 PDF",
                export_pdf_chinese(st.session_state.chat_history),
                file_name="chat_history.pdf",
                mime="application/pdf",
                key=pdf_key,               # 唯一 key
            )
        with col1:
            st.download_button(
                "💾 下載 Word (Markdown 內容)",
                export_docx_markdown(st.session_state.chat_history),
                file_name="chat_history.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                key=docx_key,              # 唯一 key
            )
        id_count+=1
    # 使用者輸入
    user_msg = st.chat_input("✍️ 請輸入訊息…")
    if user_msg:
        st.session_state.chat_history.append({"role": "user", "content": user_msg})

        with st.spinner("Agent 思考中…"):
            resp = ollama.chat(
                model=agent_cfg["model"],
                messages=st.session_state.chat_history,
                options={"temperature": agent_cfg["temp"]},
            )
        reply = resp["message"]["content"]
        st.session_state.chat_history.append({"role":"assistant","content":resp["message"]["content"]})
        # st.session_state.chat_history.append({"role": "assistant", "content": reply})

        # 立刻重新 render 顯示新訊息
        st.rerun()