"""
Tesseract LSTM Fine-tuning Pipeline
====================================
從 MongoDB 的訓練資料對，切割行圖片 → 生成 .lstmf → fine-tune chi_tra → 輸出新 traineddata

執行方式：
    uv run python tesseract_trainer.py
"""
import os
import sys
import json
import shutil
import subprocess
import uuid
import numpy as np
from datetime import datetime, timezone
from pathlib import Path
from pymongo import MongoClient

# ── 路徑設定 ──────────────────────────────────────────────────
BASE_DIR      = Path(__file__).parent
TRAIN_DIR     = BASE_DIR / "training_workspace"
GT_DIR        = TRAIN_DIR / "gt"          # 行圖片 + .gt.txt
LSTMF_DIR     = TRAIN_DIR / "lstmf"      # .lstmf 檔
MODEL_DIR     = TRAIN_DIR / "model"      # 訓練輸出
OUTPUT_DIR    = BASE_DIR / "output"

TESSDATA_SYS   = Path("/usr/share/tesseract-ocr/5/tessdata")
TESSDATA_LOCAL = TRAIN_DIR / "tessdata_local"   # 含 chi_tra + chi_tra_vert
LANG           = "chi_tra"
MAX_ITER      = 400                       # 微調迭代次數（可依資料量調整）
LINE_MARGIN   = 8                         # 行裁切上下 padding（像素）
LINE_GAP_RATIO = 0.6                      # 行間距閾值（相對於平均字高）

# ── MongoDB ───────────────────────────────────────────────────
MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")
MONGO_DB  = "ocr_insight"


def run(cmd: list[str], cwd=None, check=True, extra_env=None):
    print(f"  $ {' '.join(str(c) for c in cmd)}")
    env = os.environ.copy()
    env["TESSDATA_PREFIX"] = str(TESSDATA_LOCAL)
    if extra_env:
        env.update(extra_env)
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, env=env)
    if result.stdout.strip():
        print("   ", result.stdout.strip()[:500])
    if result.stderr.strip():
        print("   STDERR:", result.stderr.strip()[:500])
    if result.returncode != 0 and check:
        raise RuntimeError(f"指令失敗: {' '.join(str(c) for c in cmd)}")
    return result


def cluster_lines(words: list[dict]) -> list[list[dict]]:
    """依 y 座標將 words 分群成「行」"""
    if not words:
        return []
    sorted_words = sorted(words, key=lambda w: w["bbox"]["y"])
    avg_h = np.mean([w["bbox"]["h"] for w in sorted_words])
    gap_thresh = avg_h * LINE_GAP_RATIO

    lines, cur_line = [], [sorted_words[0]]
    for w in sorted_words[1:]:
        prev_cy = cur_line[-1]["bbox"]["y"] + cur_line[-1]["bbox"]["h"] / 2
        curr_cy = w["bbox"]["y"] + w["bbox"]["h"] / 2
        if abs(curr_cy - prev_cy) > gap_thresh:
            lines.append(cur_line)
            cur_line = [w]
        else:
            cur_line.append(w)
    lines.append(cur_line)
    return lines


def crop_line_image(img_array, line_words: list[dict], img_h: int, img_w: int):
    """從 numpy 圖片裁出一行的區域"""
    xs = [w["bbox"]["x"] for w in line_words]
    ys = [w["bbox"]["y"] for w in line_words]
    x2s = [w["bbox"]["x"] + w["bbox"]["w"] for w in line_words]
    y2s = [w["bbox"]["y"] + w["bbox"]["h"] for w in line_words]

    x1 = max(0, min(xs) - LINE_MARGIN)
    y1 = max(0, min(ys) - LINE_MARGIN)
    x2 = min(img_w, max(x2s) + LINE_MARGIN)
    y2 = min(img_h, max(y2s) + LINE_MARGIN)

    return img_array[y1:y2, x1:x2]


def get_corrected_words(words: list[dict], corrected_text: str) -> list[dict]:
    """
    用 corrected_text 中的 token 順序替換 words 的文字。
    若字數不吻合就保留原始 text。
    """
    tokens = corrected_text.split()
    if len(tokens) != len(words):
        return words  # 不強行對齊
    result = []
    for w, tok in zip(words, tokens):
        w2 = dict(w)
        w2["text"] = tok
        result.append(w2)
    return result


def prepare_ground_truth(pairs: list[dict], records_col) -> list[Path]:
    """
    產生行圖片（.png）和對應 ground truth（.gt.txt）。
    回傳所有行圖片路徑列表。
    """
    try:
        from PIL import Image
    except ImportError:
        raise SystemExit("請先 `uv add Pillow`")

    GT_DIR.mkdir(parents=True, exist_ok=True)
    line_images = []
    skipped = 0

    for pair_idx, pair in enumerate(pairs):
        file_id = pair["fileId"]
        corrected_text = pair.get("corrected_text", "")
        doc = records_col.find_one({"_id": file_id})
        if not doc:
            skipped += 1
            continue

        for page in doc.get("pages", []):
            img_path = page.get("imagePath")
            if not img_path or not Path(img_path).exists():
                skipped += 1
                continue

            words = page.get("words", [])
            if not words:
                skipped += 1
                continue

            try:
                pil_img = Image.open(img_path).convert("RGB")
                img_arr = np.array(pil_img)
                img_h, img_w = img_arr.shape[:2]
            except Exception as e:
                print(f"  ⚠️  圖片讀取失敗 {img_path}: {e}")
                skipped += 1
                continue

            lines = cluster_lines(words)
            # 用 corrected_text 的行逐行對應
            corrected_lines = corrected_text.strip().split("\n")

            for line_idx, line_words in enumerate(lines):
                # 取對應的修正文字（行數可能不等就跳過）
                if line_idx < len(corrected_lines):
                    gt_text = corrected_lines[line_idx].strip()
                else:
                    gt_text = " ".join(w["text"] for w in line_words)

                if not gt_text:
                    continue

                crop = crop_line_image(img_arr, line_words, img_h, img_w)
                if crop.size == 0:
                    continue

                name = f"pair{pair_idx:04d}_p{page.get('pageIndex',0)}_l{line_idx:03d}"
                png_path = GT_DIR / f"{name}.png"
                gt_path  = GT_DIR / f"{name}.gt.txt"

                Image.fromarray(crop).save(png_path)
                gt_path.write_text(gt_text, encoding="utf-8")
                line_images.append(png_path)

    print(f"  ✅ 產生 {len(line_images)} 行圖片（略過 {skipped} 筆）")
    return line_images


def generate_lstmf(line_images: list[Path]) -> Path:
    """對每個行圖片生成 WordStr .box 再產生 .lstmf"""
    from PIL import Image as PILImage
    LSTMF_DIR.mkdir(parents=True, exist_ok=True)
    lstmf_paths = []
    skipped = 0

    for png in line_images:
        gt_src = GT_DIR / f"{png.stem}.gt.txt"
        gt_text = gt_src.read_text(encoding="utf-8").strip()
        if not gt_text:
            skipped += 1
            continue

        dst_png = LSTMF_DIR / png.name
        shutil.copy(png, dst_png)

        # 取得圖片尺寸
        try:
            img = PILImage.open(dst_png)
            w, h = img.size
        except Exception:
            skipped += 1
            continue

        # 生成 WordStr box 檔（整行圖片對應一段文字）
        box_path = LSTMF_DIR / f"{png.stem}.box"
        box_path.write_text(
            f"WordStr 0 0 {w} {h} 0 #{gt_text}\n\t 0 0 {w} {h} 0\n",
            encoding="utf-8"
        )

        base = LSTMF_DIR / png.stem
        result = run(
            ["tesseract", str(dst_png), str(base),
             "--psm", "6", "-l", LANG,
             "lstm.train"],
            check=False
        )
        lstmf = base.with_suffix(".lstmf")
        if lstmf.exists():
            lstmf_paths.append(lstmf)
        else:
            skipped += 1

    list_file = TRAIN_DIR / "train_list.txt"
    list_file.write_text("\n".join(str(p) for p in lstmf_paths), encoding="utf-8")
    print(f"  ✅ 產生 {len(lstmf_paths)} 個 .lstmf（略過 {skipped} 個）")
    return list_file


def extract_lstm() -> Path:
    """從 chi_tra.traineddata 提取 LSTM 模型"""
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    src_traineddata = TESSDATA_LOCAL / f"{LANG}.traineddata"
    lstm_out = MODEL_DIR / f"{LANG}.lstm"
    run(["combine_tessdata", "-e", str(src_traineddata), str(lstm_out)])
    print(f"  ✅ 提取 LSTM → {lstm_out}")
    return lstm_out


def fine_tune(lstm_path: Path, list_file: Path) -> Path:
    """執行 lstmtraining fine-tune，即時串流 stderr 輸出（含訓練指標）"""
    src_traineddata = TESSDATA_LOCAL / f"{LANG}.traineddata"
    checkpoint_prefix = MODEL_DIR / f"{LANG}_ft"

    cmd = [
        "lstmtraining",
        f"--model_output={checkpoint_prefix}",
        f"--continue_from={lstm_path}",
        f"--traineddata={src_traineddata}",
        f"--train_listfile={list_file}",
        f"--max_iterations={MAX_ITER}",
        "--debug_interval=0",
    ]
    print(f"  $ {' '.join(str(c) for c in cmd)}")
    env = os.environ.copy()
    env["TESSDATA_PREFIX"] = str(TESSDATA_LOCAL)

    # lstmtraining 把訓練進度（At iteration...）輸出到 stderr，需要即時串流才能被上層捕捉
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,   # 合併 stderr → stdout，方便逐行讀取
        text=True,
        env=env,
    )
    for line in proc.stdout:
        line = line.rstrip()
        if line:
            print(line, flush=True)
    proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(f"lstmtraining 失敗（exit code {proc.returncode}）")

    checkpoint = Path(f"{checkpoint_prefix}_checkpoint")
    if not checkpoint.exists():
        # lstmtraining 有時用 _checkpoint 後綴
        candidates = list(MODEL_DIR.glob(f"{LANG}_ft*checkpoint*"))
        if candidates:
            checkpoint = candidates[0]
        else:
            raise RuntimeError("找不到 checkpoint 檔案")

    print(f"  ✅ Fine-tune 完成，checkpoint: {checkpoint}")
    return checkpoint


def find_best_checkpoint() -> Path:
    """找最佳 checkpoint（accuracy 最高的，格式為 lang_ft_<loss>_<iter>_<total>.checkpoint）"""
    candidates = list(MODEL_DIR.glob(f"{LANG}_ft_*_*_*.checkpoint"))
    if not candidates:
        # 退而求其次用最終 checkpoint
        final = MODEL_DIR / f"{LANG}_ft_checkpoint"
        if final.exists():
            return final
        raise RuntimeError("找不到任何 checkpoint")
    # 依 loss 數值升序取最低 loss（accuracy 最高）
    def loss_key(p: Path):
        try:
            return float(p.stem.split("_")[3])
        except Exception:
            return float("inf")
    return min(candidates, key=loss_key)


def export_traineddata(checkpoint: Path = None, training_pairs: int = 0) -> Path:
    """
    將 best checkpoint 合併回 traineddata，並同時存一份帶版本號的備份。
    版本 metadata 寫入 MongoDB ocr_model_versions collection。
    """
    src_traineddata = TESSDATA_LOCAL / f"{LANG}.traineddata"
    out_traineddata = OUTPUT_DIR / f"{LANG}_custom.traineddata"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    best_ckpt = find_best_checkpoint()
    print(f"  使用 best checkpoint: {best_ckpt.name}")

    # 解析 loss（格式：lang_ft_<loss>_<iter>_<total>.checkpoint）
    best_loss = None
    try:
        best_loss = float(best_ckpt.stem.split("_")[3])
    except Exception:
        pass

    # combine_tessdata -o 依副檔名決定替換的元件類型（.lstm → lstm 元件）
    lstm_src = MODEL_DIR / f"{LANG}_best_for_export.lstm"
    shutil.copy(best_ckpt, lstm_src)

    shutil.copy(src_traineddata, out_traineddata)
    run(["combine_tessdata", "-o", str(out_traineddata), str(lstm_src)])

    # 儲存帶版本號的備份
    version_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    lang_code  = f"{LANG}_custom"
    versioned_name = f"{lang_code}_v{version_id}.traineddata"
    versioned_path = OUTPUT_DIR / versioned_name
    shutil.copy(out_traineddata, versioned_path)

    # chi_tra_vert 依賴
    vert_src = TESSDATA_LOCAL / "chi_tra_vert.traineddata"
    if vert_src.exists():
        shutil.copy(vert_src, OUTPUT_DIR / "chi_tra_vert.traineddata")

    # 寫版本 metadata 到 MongoDB
    meta = {
        "version_id": version_id,
        "lang_code": lang_code,
        "display_name": f"繁體中文自訓練 v{version_id}",
        "file": versioned_name,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "training_pairs": training_pairs,
        "best_loss": best_loss,
        "max_iterations": MAX_ITER,
        "is_active": True,
    }
    client = MongoClient(MONGO_URL)
    col = client[MONGO_DB]["ocr_model_versions"]
    col.update_many({}, {"$set": {"is_active": False}})  # 舊版本清除 active
    col.insert_one(meta)
    client.close()

    print(f"\n  新模型: {out_traineddata}")
    print(f"  版本備份: {versioned_path}")
    print(f"  版本 ID: {version_id}")
    return out_traineddata


def main():
    print("=" * 55)
    print("  Tesseract LSTM Fine-tuning Pipeline")
    print("=" * 55)

    client = MongoClient(MONGO_URL)
    db = client[MONGO_DB]
    pairs = list(db["ocr_training_pairs"].find({}))
    records_col = db["ocr_records"]
    training_pairs_count = len(pairs)

    if not pairs:
        print("❌ 沒有訓練資料，請先透過前端累積修正資料")
        sys.exit(1)

    print(f"\n[1/5] 讀取 {len(pairs)} 筆訓練資料")
    print(f"[2/5] 產生行圖片與 ground truth")
    line_images = prepare_ground_truth(pairs, records_col)

    if not line_images:
        print("❌ 沒有有效的行圖片，請確認原始圖片路徑正確")
        sys.exit(1)

    print(f"\n[3/5] 生成 .lstmf 訓練檔")
    list_file = generate_lstmf(line_images)

    print(f"\n[4/5] 提取並 fine-tune chi_tra LSTM（{MAX_ITER} 次迭代）")
    lstm_path = extract_lstm()
    checkpoint = fine_tune(lstm_path, list_file)

    print(f"\n[5/5] 匯出新 traineddata")
    new_model = export_traineddata(checkpoint, training_pairs=training_pairs_count)

    print("\n" + "=" * 55)
    print(f"  完成！新模型位置：")
    print(f"  {new_model}")
    print()
    print("  使用方式（測試）：")
    print(f"  tesseract input.png out -l chi_tra_custom --tessdata-dir {OUTPUT_DIR}")
    print("=" * 55)


if __name__ == "__main__":
    main()
