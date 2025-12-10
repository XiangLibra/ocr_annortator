# # ocr_engines.py

# import easyocr
# from doctr.io import DocumentFile
# from doctr.models import ocr_predictor
# from paddleocr import PaddleOCR
# import pytesseract
# import numpy as np
# import tempfile
# import os
# import cv2


# def initialize_ocr_models(ocr_models, language_code, device):
#     ocr_readers = {}
#     if "EasyOCR" in ocr_models:
#         ocr_readers["EasyOCR"] = easyocr.Reader(
#             [language_code], gpu=(device == "GPU (CUDA)")
#         )
#     if "DocTR" in ocr_models:
#         ocr_readers["DocTR"] = ocr_predictor(pretrained=True)
#     if "PaddleOCR" in ocr_models:
#         use_gpu = True if device == "GPU (CUDA)" else False
#         ocr_readers["PaddleOCR"] = PaddleOCR(lang=language_code, use_gpu=use_gpu)
#     if "Tesseract" in ocr_models:
#         # Update the Tesseract executable path if necessary
#         pytesseract.pytesseract.tesseract_cmd = (
#             r"C:\Program Files\Tesseract-OCR\tesseract.exe"
#         )
#     return ocr_readers


# def perform_ocr(model_name, ocr_readers, image, language_code):
#     text = ""
#     if model_name == "EasyOCR":
#         result = ocr_readers["EasyOCR"].readtext(np.array(image))
#         text = "\n".join([res[1] for res in result])
#     elif model_name == "DocTR":
#         with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp_file:
#             image.save(tmp_file, format="PNG")
#         file_path = tmp_file.name
#         doc = DocumentFile.from_images(file_path)
#         result = ocr_readers["DocTR"](doc)
#         text = "\n\n".join(
#             [
#                 "\n".join(
#                     [
#                         " ".join([word.value for word in line.words])
#                         for line in block.lines
#                     ]
#                 )
#                 for block in result.pages[0].blocks
#             ]
#         )
#         os.unlink(file_path)
#     elif model_name == "PaddleOCR":
#         result = ocr_readers["PaddleOCR"].ocr(np.array(image))
#         text = "\n".join([line[1][0] for line in result[0]])
#     elif model_name == "Tesseract":
#         # Convert PIL image to RGB if not already
#         if image.mode != "RGB":
#             image = image.convert("RGB")
#         # Convert image to OpenCV format
#         opencv_image = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
#         config = f"--oem 3 --psm 6 -l {language_code}"
#         text = pytesseract.image_to_string(opencv_image)  # , config=config
#     return text

# ocr_engines.py

# import easyocr
# from doctr.io import DocumentFile
# from doctr.models import ocr_predictor
# from paddleocr import PaddleOCR
# import pytesseract
# import numpy as np
# import tempfile
# import os
# import cv2


# def initialize_ocr_models(ocr_models, language_code, device):
#     ocr_readers = {}
#     if "EasyOCR" in ocr_models:
#         ocr_readers["EasyOCR"] = easyocr.Reader(
#             [language_code], gpu=(device == "GPU (CUDA)")
#         )
#     if "DocTR" in ocr_models:
#         ocr_readers["DocTR"] = ocr_predictor(pretrained=True)
#     if "PaddleOCR" in ocr_models:
#         use_gpu = True if device == "GPU (CUDA)" else False
#         ocr_readers["PaddleOCR"] = PaddleOCR(lang=language_code, use_gpu=use_gpu)
#     if "Tesseract" in ocr_models:
#         # Update the Tesseract executable path if necessary
#         pass
#         # pytesseract.pytesseract.tesseract_cmd = (
#         #     r"C:\Program Files\Tesseract-OCR\tesseract.exe"
#         # )
#     return ocr_readers


# def perform_ocr(model_name, ocr_readers, image, language_code):
#     text = ""
#     if model_name == "EasyOCR":
#         result = ocr_readers["EasyOCR"].readtext(np.array(image))
#         text = "\n".join([res[1] for res in result])
#     elif model_name == "DocTR":
#         with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp_file:
#             image.save(tmp_file, format="PNG")
#         file_path = tmp_file.name
#         doc = DocumentFile.from_images(file_path)
#         result = ocr_readers["DocTR"](doc)
#         text = "\n\n".join(
#             [
#                 "\n".join(
#                     [
#                         " ".join([word.value for word in line.words])
#                         for line in block.lines
#                     ]
#                 )
#                 for block in result.pages[0].blocks
#             ]
#         )
#         os.unlink(file_path)
#     elif model_name == "PaddleOCR":
#         result = ocr_readers["PaddleOCR"].ocr(np.array(image))
#         text = "\n".join([line[1][0] for line in result[0]])
#     elif model_name == "Tesseract":
#         # Convert PIL image to RGB if not already
#         if image.mode != "RGB":
#             image = image.convert("RGB")
#         # Convert image to OpenCV format
#         opencv_image = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
#         config = f"--oem 3 --psm 6 -l {language_code}"
#         text = pytesseract.image_to_string(opencv_image, config=config)  # , config=config
#     return text




# ocr_engines.py

from typing import Any    # ← 新增這行
import easyocr
from doctr.io import DocumentFile
from doctr.models import ocr_predictor
from paddleocr import PaddleOCR
import pytesseract
import numpy as np
import tempfile
import os
import cv2

def initialize_ocr_models(
    ocr_models: list[str],
    lang_code_map: dict[str,str],
    device: str
) -> dict[str, Any]:
    """
    ocr_models:   ["Tesseract","EasyOCR",…]
    lang_code_map: {"Tesseract":"chi_tra","EasyOCR":"ch_tra",…}
    device:       "CPU" or "GPU (CUDA)"
    """
    ocr_readers: dict[str, Any] = {}

    # EasyOCR 需要一個 list of codes
    if "EasyOCR" in ocr_models:
        code = lang_code_map["EasyOCR"]
        ocr_readers["EasyOCR"] = easyocr.Reader(
            [code],
            gpu=(device == "GPU (CUDA)")
        )

    # DocTR 不分語言，直接載預訓練模型
    if "DocTR" in ocr_models:
        ocr_readers["DocTR"] = ocr_predictor(pretrained=True)

    # PaddleOCR 接受一個字串 code
    if "PaddleOCR" in ocr_models:
        code = lang_code_map["PaddleOCR"]
        use_gpu = (device == "GPU (CUDA)")
        ocr_readers["PaddleOCR"] = PaddleOCR(
            lang=code,
            use_gpu=use_gpu
        )

    # Tesseract 用 pytesseract，不需要 reader instance
    if "Tesseract" in ocr_models:
        # 如有需要指定 exe 路徑，可在這邊設定：
        # pytesseract.pytesseract.tesseract_cmd = "/usr/bin/tesseract"
        ocr_readers["Tesseract"] = None

    return ocr_readers


def perform_ocr(model_name: str, ocr_readers: dict, image, language_code: str) -> str:
    text = ""
    if model_name == "EasyOCR":
        result = ocr_readers["EasyOCR"].readtext(np.array(image))
        text = "\n".join([res[1] for res in result])

    elif model_name == "DocTR":
        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp_file:
            image.save(tmp_file, format="PNG")
        doc = DocumentFile.from_images(tmp_file.name)
        result = ocr_readers["DocTR"](doc)
        os.unlink(tmp_file.name)
        text = "\n\n".join(
            [
                "\n".join(
                    [" ".join([w.value for w in line.words]) for line in block.lines]
                )
                for block in result.pages[0].blocks
            ]
        )

    elif model_name == "PaddleOCR":
        result = ocr_readers["PaddleOCR"].ocr(np.array(image))
        text = "\n".join([line[1][0] for line in result[0]])

    elif model_name == "Tesseract":
        if image.mode != "RGB":
            image = image.convert("RGB")
        opencv_image = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
        config = f"--oem 3 --psm 6 -l {language_code}"
        text = pytesseract.image_to_string(opencv_image, config=config)

    return text
