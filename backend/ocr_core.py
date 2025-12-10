# backend/ocr_core.py
import io, base64, fitz, pytesseract
from PIL import Image
from pytesseract import Output

def pil_to_base64(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("utf-8")

def pdf_to_images(pdf_bytes: bytes):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    imgs = []
    for page in doc:
        pix = page.get_pixmap()  # 可視需要調整解析度
        imgs.append(Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB"))
    doc.close()
    return imgs

def image_to_words(img: Image.Image, lang_code: str, conf_min: int = 10):
    data = pytesseract.image_to_data(img, lang=lang_code, output_type=Output.DICT)
    n = len(data["text"])
    words = []
    for i in range(n):
        txt = (data["text"][i] or "").strip()
        try:
            conf = int(float(data["conf"][i]))
        except:
            conf = -1
        if txt and conf >= conf_min:
            words.append({
                "id": f"w{i}",
                "text": txt,
                "conf": conf,
                "bbox": {
                    "x": data["left"][i],
                    "y": data["top"][i],
                    "w": data["width"][i],
                    "h": data["height"][i],
                }
            })
    return words

def run_ocr_on_file(file_bytes: bytes, filename: str, lang_code: str):
    # 判斷 PDF 或影像
    if filename.lower().endswith(".pdf"):
        pages = pdf_to_images(file_bytes)
    else:
        pages = [Image.open(io.BytesIO(file_bytes)).convert("RGB")]

    page_results = []
    full_text_list = []
    for page_idx, img in enumerate(pages):
        words = image_to_words(img, lang_code)
        full_text_list.append(" ".join([w["text"] for w in words]))
        page_results.append({
            "pageIndex": page_idx,
            "width": img.width,
            "height": img.height,
            "imageDataUrl": pil_to_base64(img),
            "words": words
        })

    return {
        "pages": page_results,
        "fullText": "\n".join(full_text_list)
    }
