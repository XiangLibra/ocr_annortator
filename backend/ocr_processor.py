import pytesseract
from PIL import Image, ImageDraw
import fitz  # PyMuPDF
import io
import os

def process_image_ocr(filepath, lang='chi_tra'):
    """
    處理圖片或 PDF 進行 OCR 識別
    返回格式: [{'id': 1, 'x': 100, 'y': 50, 'width': 120, 'height': 30, 'text': '文字', 'confidence': 95}]
    """
    results = []
    
    # 判斷檔案類型
    if filepath.lower().endswith('.pdf'):
        # 處理 PDF
        pdf_document = fitz.open(filepath)
        images = []
        for page_num in range(pdf_document.page_count):
            page = pdf_document[page_num]
            pix = page.get_pixmap()
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            images.append(img)
        pdf_document.close()
    else:
        # 處理一般圖片
        images = [Image.open(filepath)]
    
    box_id = 1
    for page_idx, img in enumerate(images):
        # 使用 Tesseract 取得詳細資料
        data = pytesseract.image_to_data(
            img, 
            lang=lang, 
            output_type=pytesseract.Output.DICT
        )
        
        n = len(data['text'])
        for i in range(n):
            confidence = int(data['conf'][i])
            text = data['text'][i].strip()
            
            # 只保留信心度 > 10 且有文字的區塊
            if confidence > 10 and text:
                results.append({
                    'id': box_id,
                    'page': page_idx,
                    'x': data['left'][i],
                    'y': data['top'][i],
                    'width': data['width'][i],
                    'height': data['height'][i],
                    'text': text,
                    'confidence': confidence
                })
                box_id += 1
    
    return results