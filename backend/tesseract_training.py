"""
Utility helpers for preparing training data and fine-tuning Tesseract OCR
models using the corrected OCR outputs produced by the application.

This module can be invoked as a CLI to:

1. Convert saved OCR JSON payloads (stored under ``backend/output`` by default)
   into page-level image/text pairs suitable for Tesseract training
2. Generate ``*.lstmf`` training files by calling the Tesseract binary
3. Run ``lstmtraining`` to fine-tune an existing language model

Example:

.. code-block:: bash

    uv run python -m backend.tesseract_training \\
        --input-dir backend/output \\
        --output-dir backend/tess_train \\
        --language chi_tra \\
        --base-model chi_tra \\
        --max-iterations 800
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import math
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from PIL import Image


# ---------------------------------------------------------------------------
# Data model helpers
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class TrainingSample:
    """Represents a single page/image used for training."""

    name: str
    record_id: str
    page_index: int
    image_path: Path
    gt_path: Path
    text: str


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------


def _ensure_command(name: str, explicit: str | None = None) -> str:
    """
    Return the executable path for ``name`` (or an explicitly provided path).

    Raises RuntimeError if the command cannot be located.
    """
    if explicit:
        path = shutil.which(explicit)
        if not path:
            raise RuntimeError(f"Executable '{explicit}' not found on PATH.")
        return path

    path = shutil.which(name)
    if not path:
        raise RuntimeError(
            f"Executable '{name}' not found on PATH. "
            "Install Tesseract OCR with training tools."
        )
    return path


def _parse_data_url(data_url: str) -> bytes:
    """Decode a base64 data URL into raw bytes."""
    if not data_url.startswith("data:"):
        raise ValueError("Unsupported image data url format.")
    try:
        header, encoded = data_url.split(",", 1)
    except ValueError as exc:
        raise ValueError("Malformed data url.") from exc
    if ";base64" not in header:
        raise ValueError("Only base64-encoded data urls are supported.")
    return base64.b64decode(encoded)


def _group_words_into_lines(words: Sequence[dict]) -> list[list[dict]]:
    """Cluster OCR words into reading-order lines using Y proximity."""
    if not words:
        return []

    sorted_words = sorted(
        words,
        key=lambda w: (
            w.get("bbox", {}).get("y", 0),
            w.get("bbox", {}).get("x", 0),
        ),
    )

    heights = [w.get("bbox", {}).get("h", 0) for w in sorted_words]
    avg_height = sum(heights) / len(heights) if heights else 0
    tolerance = max(10.0, avg_height * 0.6)

    lines: list[list[dict]] = []
    current_line: list[dict] = []
    current_center_y = None

    for word in sorted_words:
        bbox = word.get("bbox") or {}
        cy = bbox.get("y", 0) + bbox.get("h", 0) / 2
        if current_line:
            assert current_center_y is not None
            if abs(cy - current_center_y) > tolerance:
                # close current line
                current_line.sort(key=lambda w: w.get("bbox", {}).get("x", 0))
                lines.append(current_line)
                current_line = []
                current_center_y = None

        if not current_line:
            current_center_y = cy
        else:
            current_center_y = (
                current_center_y * len(current_line) + cy
            ) / (len(current_line) + 1)

        current_line.append(word)

    if current_line:
        current_line.sort(key=lambda w: w.get("bbox", {}).get("x", 0))
        lines.append(current_line)

    return lines


def _join_tokens(tokens: list[str], language: str) -> str:
    """Join tokens according to language specific heuristics."""
    tokens = [t for t in tokens if t.strip()]
    if not tokens:
        return ""

    if language.startswith("chi"):
        # Tesseract chi_* returns single characters; keep dense text.
        return "".join(tokens)

    # Fallback: join with spaces, but collapse duplicated spaces.
    line = " ".join(tokens)
    return " ".join(line.split())


def _page_text(page: dict, language: str) -> str:
    """
    Build ground-truth text for a page using corrected words if available.

    Priority order:
    1. ``page["correctedText"]`` if present (user may supply per-page text)
    2. ``page["words"]`` aggregated by reading order
    3. (fallback) ``page.get("text")`` or empty string
    """
    corrected = page.get("correctedText")
    if isinstance(corrected, str) and corrected.strip():
        return corrected.strip()

    words = page.get("words") or []
    if words:
        lines = []
        for line_words in _group_words_into_lines(words):
            line_tokens = [w.get("text", "").strip() for w in line_words]
            lines.append(_join_tokens(line_tokens, language))
        lines = [ln for ln in lines if ln]
        if lines:
            return "\n".join(lines)

    fallback = page.get("text")
    return fallback.strip() if isinstance(fallback, str) else ""


def _save_page_image(page: dict, dest_path: Path) -> None:
    """Decode the page image DataURL and persist it to ``dest_path``."""
    image_b64 = page.get("imageDataUrl")
    if not isinstance(image_b64, str):
        raise ValueError("Page payload missing 'imageDataUrl'.")
    image_bytes = _parse_data_url(image_b64)
    with Image.open(io.BytesIO(image_bytes)) as img:
        img.convert("RGB").save(dest_path, format="PNG")


def discover_records(input_dir: Path) -> list[Path]:
    """Return all JSON files under ``input_dir`` sorted by name."""
    return sorted(Path(input_dir).glob("*.json"))


def extract_training_samples(
    input_dir: Path,
    samples_dir: Path,
    language: str,
    limit: int | None = None,
) -> list[TrainingSample]:
    """
    Convert OCR JSON payloads into page-level training samples.

    Returns a list of :class:`TrainingSample` items.
    """
    samples_dir.mkdir(parents=True, exist_ok=True)

    record_paths = discover_records(input_dir)
    samples: list[TrainingSample] = []

    for idx, record_path in enumerate(record_paths):
        if limit is not None and idx >= limit:
            break

        with open(record_path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)

        record_id = payload.get("fileId") or record_path.stem
        pages = payload.get("pages") or []

        for page in pages:
            page_index = int(page.get("pageIndex", len(samples)))
            text = _page_text(page, language)
            if not text.strip():
                # Skip pages without ground truth
                continue

            sample_name = f"{record_id}_p{page_index:04d}"
            image_path = samples_dir / f"{sample_name}.png"
            gt_path = samples_dir / f"{sample_name}.gt.txt"

            _save_page_image(page, image_path)
            gt_path.write_text(text, encoding="utf-8")

            samples.append(
                TrainingSample(
                    name=sample_name,
                    record_id=record_id,
                    page_index=page_index,
                    image_path=image_path,
                    gt_path=gt_path,
                    text=text,
                )
            )

    return samples


def split_train_eval(
    samples: Sequence[TrainingSample],
    eval_fraction: float,
) -> tuple[list[TrainingSample], list[TrainingSample]]:
    """Split samples into train/eval lists using the provided fraction."""
    if not samples:
        return [], []

    eval_fraction = min(max(eval_fraction, 0.0), 0.5)
    eval_count = max(1, math.floor(len(samples) * eval_fraction)) if len(samples) > 1 else 0
    eval_samples = list(samples[-eval_count:]) if eval_count else []
    train_samples = list(samples[:-eval_count]) if eval_count else list(samples)

    # Ensure we always keep at least one training sample
    if not train_samples and eval_samples:
        train_samples.append(eval_samples.pop())

    return train_samples, eval_samples


def generate_lstmf_files(
    samples: Sequence[TrainingSample],
    lstmf_dir: Path,
    language: str,
    tesseract_cmd: str | None,
    tessdata_dir: Path | None,
    psm: int,
    oem: int,
) -> list[Path]:
    """
    Call the ``tesseract`` executable to produce ``*.lstmf`` files.

    Returns list of generated lstmf paths.
    """
    if not samples:
        return []

    tess_bin = _ensure_command("tesseract", tesseract_cmd)
    lstmf_dir.mkdir(parents=True, exist_ok=True)

    generated: list[Path] = []
    for sample in samples:
        output_base = lstmf_dir / sample.name
        cmd = [
            tess_bin,
            str(sample.image_path),
            str(output_base),
            "--psm",
            str(psm),
            "--oem",
            str(oem),
            "-l",
            language,
            "lstm.train",
        ]
        if tessdata_dir:
            cmd.extend(["--tessdata-dir", str(tessdata_dir)])
        try:
            subprocess.run(
                cmd,
                check=True,
                cwd=sample.image_path.parent,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(
                "Tesseract failed while generating LSTMF for "
                f"{sample.image_path.name}:\n{exc.stderr or exc.stdout}"
            ) from exc
        generated.append(output_base.with_suffix(".lstmf"))

    return generated


def _resolve_traineddata_path(base_model: str, tessdata_dir: Path | None) -> Path:
    candidate_dirs: list[Path] = []

    if tessdata_dir:
        candidate_dirs.append(Path(tessdata_dir))

    env_prefix = os.environ.get("TESSDATA_PREFIX")
    if env_prefix:
        candidate_dirs.append(Path(env_prefix))

    candidate_dirs.extend(
        [
            Path("/usr/share/tesseract-ocr/5/tessdata"),
            Path("/usr/share/tesseract-ocr/4.00/tessdata"),
            Path("/usr/share/tesseract/tessdata"),
        ]
    )

    for directory in candidate_dirs:
        traineddata = directory / f"{base_model}.traineddata"
        if traineddata.exists():
            return traineddata

    raise FileNotFoundError(
        f"Unable to locate '{base_model}.traineddata'. "
        "Specify --tessdata-dir or ensure TESSDATA_PREFIX is set."
    )


def ensure_language_data(language: str, tessdata_dir: Path | None) -> None:
    """
    Verify that the required traineddata files for ``language`` exist.

    For Traditional Chinese (`chi_tra`), Tesseract also loads `chi_tra_vert`.
    """
    required = [language]
    if language.startswith("chi_"):
        required.append(f"{language}_vert")

    missing: list[str] = []
    for lang in required:
        try:
            _resolve_traineddata_path(lang, tessdata_dir)
        except FileNotFoundError:
            missing.append(lang)

    if missing:
        formatted = ", ".join(f"{lang}.traineddata" for lang in missing)
        raise SystemExit(
            "Missing Tesseract traineddata files: "
            f"{formatted}. Install the corresponding language package "
            "(e.g. `sudo apt install tesseract-ocr-script-vert`) or supply "
            "--tessdata-dir pointing to a directory that contains them."
        )


def run_lstm_training(
    train_list: Path,
    eval_list: Path | None,
    work_dir: Path,
    base_model: str,
    tessdata_dir: Path | None,
    lstmtraining_cmd: str | None,
    combine_cmd: str | None,
    model_name: str,
    max_iterations: int,
    learning_rate: float | None,
    debug_interval: int,
) -> Path:
    """
    Execute the LSTM fine-tuning steps and return the final traineddata path.
    """
    lstm_bin = _ensure_command("lstmtraining", lstmtraining_cmd)
    combine_bin = _ensure_command("combine_tessdata", combine_cmd)

    work_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir = work_dir / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    base_traineddata = _resolve_traineddata_path(base_model, tessdata_dir)
    tmp_traineddata = tmp_dir / f"{base_model}.traineddata"
    shutil.copyfile(base_traineddata, tmp_traineddata)

    base_lstm = tmp_dir / f"{base_model}.lstm"
    subprocess.run(
        [combine_bin, "-e", str(tmp_traineddata), str(base_lstm)],
        check=True,
    )

    model_dir = work_dir / "models"
    model_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_prefix = model_dir / model_name

    cmd = [
        lstm_bin,
        "--continue_from",
        str(base_lstm),
        "--traineddata",
        str(tmp_traineddata),
        "--model_output",
        str(checkpoint_prefix),
        "--max_iterations",
        str(max_iterations),
        "--debug_interval",
        str(debug_interval),
        "--training_listfile",
        str(train_list),
    ]
    if eval_list and eval_list.exists():
        cmd.extend(["--eval_listfile", str(eval_list)])
    if learning_rate:
        cmd.extend(["--learning_rate", str(learning_rate)])

    subprocess.run(cmd, check=True)

    checkpoint_path = checkpoint_prefix.with_suffix(".checkpoint")
    if not checkpoint_path.exists():
        raise RuntimeError(
            "lstmtraining did not produce a checkpoint file as expected."
        )

    final_model_path = model_dir / f"{model_name}.traineddata"
    stop_cmd = [
        lstm_bin,
        "--stop_training",
        "--continue_from",
        str(checkpoint_path),
        "--traineddata",
        str(tmp_traineddata),
        "--model_output",
        str(final_model_path),
    ]
    subprocess.run(stop_cmd, check=True)

    return final_model_path


# ---------------------------------------------------------------------------
# CLI Entrypoint
# ---------------------------------------------------------------------------


def _write_listfile(paths: Iterable[Path], dest: Path) -> None:
    lines = [str(p.resolve()) for p in paths]
    dest.write_text("\n".join(lines), encoding="utf-8")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare datasets and fine-tune Tesseract using saved OCR outputs.",
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=Path("backend/output"),
        help="Directory containing corrected OCR JSON payloads.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("backend/tess_training"),
        help="Working directory for generated artifacts.",
    )
    parser.add_argument(
        "--language",
        default="chi_tra",
        help="Language code to use when generating ground truth and lstmf files.",
    )
    parser.add_argument(
        "--base-model",
        default="chi_tra",
        help="Existing Tesseract model name to fine-tune from.",
    )
    parser.add_argument(
        "--tessdata-dir",
        type=Path,
        default=None,
        help="Optional override for TESSDATA directory.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Optional limit on number of JSON files processed.",
    )
    parser.add_argument(
        "--eval-fraction",
        type=float,
        default=0.1,
        help="Fraction of samples reserved for evaluation (0-0.5).",
    )
    parser.add_argument(
        "--psm",
        type=int,
        default=6,
        help="Tesseract page segmentation mode for lstmf generation.",
    )
    parser.add_argument(
        "--oem",
        type=int,
        default=1,
        help="Tesseract OCR engine mode for lstmf generation.",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=500,
        help="Maximum iterations for lstmtraining fine-tuning.",
    )
    parser.add_argument(
        "--learning-rate",
        type=float,
        default=None,
        help="Optional learning rate override for lstmtraining.",
    )
    parser.add_argument(
        "--debug-interval",
        type=int,
        default=100,
        help="How often (in iterations) to report training stats.",
    )
    parser.add_argument(
        "--model-name",
        default="custom_model",
        help="Base name for the fine-tuned model artifacts.",
    )
    parser.add_argument(
        "--tesseract-cmd",
        default=None,
        help="Optional explicit path to the tesseract binary.",
    )
    parser.add_argument(
        "--lstmtraining-cmd",
        default=None,
        help="Optional explicit path to the lstmtraining binary.",
    )
    parser.add_argument(
        "--combine-cmd",
        default=None,
        help="Optional explicit path to the combine_tessdata binary.",
    )
    parser.add_argument(
        "--prepare-only",
        action="store_true",
        help="Only prepare samples and lstmf files without running lstmtraining.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)

    samples_dir = args.output_dir / "samples"
    lstmf_dir = args.output_dir / "lstmf"
    work_dir = args.output_dir

    ensure_language_data(args.language, args.tessdata_dir)

    samples = extract_training_samples(
        input_dir=args.input_dir,
        samples_dir=samples_dir,
        language=args.language,
        limit=args.max_pages,
    )
    if not samples:
        raise SystemExit("No training samples generated. Ensure corrected JSON files exist.")

    train_samples, eval_samples = split_train_eval(samples, args.eval_fraction)

    train_lstmf = generate_lstmf_files(
        samples=train_samples,
        lstmf_dir=lstmf_dir / "train",
        language=args.language,
        tesseract_cmd=args.tesseract_cmd,
        tessdata_dir=args.tessdata_dir,
        psm=args.psm,
        oem=args.oem,
    )
    eval_lstmf = generate_lstmf_files(
        samples=eval_samples,
        lstmf_dir=lstmf_dir / "eval",
        language=args.language,
        tesseract_cmd=args.tesseract_cmd,
        tessdata_dir=args.tessdata_dir,
        psm=args.psm,
        oem=args.oem,
    )

    train_list = work_dir / "train_list.txt"
    eval_list = work_dir / "eval_list.txt"
    _write_listfile(train_lstmf, train_list)
    _write_listfile(eval_lstmf, eval_list)

    if args.prepare_only:
        return

    final_model = run_lstm_training(
        train_list=train_list,
        eval_list=eval_list if eval_lstmf else None,
        work_dir=work_dir,
        base_model=args.base_model,
        tessdata_dir=args.tessdata_dir,
        lstmtraining_cmd=args.lstmtraining_cmd,
        combine_cmd=args.combine_cmd,
        model_name=args.model_name,
        max_iterations=args.max_iterations,
        learning_rate=args.learning_rate,
        debug_interval=args.debug_interval,
    )

    print(f"Training complete. Model saved to: {final_model}")


if __name__ == "__main__":
    main()
