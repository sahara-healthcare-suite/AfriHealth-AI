"""Run reproducible ASR inference on the imported AfriSwitch pilot."""

import argparse
import csv
import json
from pathlib import Path
from time import perf_counter

from benchmark_suite import calculate_entity_accuracy, calculate_wer

MODEL_CHECKPOINTS = {
    "whisper-tiny": "openai/whisper-tiny",
    "whisper-base": "openai/whisper-base",
    "whisper-small": "openai/whisper-small",
}


def load_rows(root: Path, configs: list[str], limit: int | None) -> list[dict[str, str]]:
    rows = []
    for config in configs:
        manifest = root / "manifests" / f"{config}.csv"
        if not manifest.is_file():
            raise FileNotFoundError(f"Manifest not found: {manifest}")
        with manifest.open(encoding="utf-8", newline="") as handle:
            config_rows = list(csv.DictReader(handle))
        rows.extend(config_rows[:limit] if limit else config_rows)
    return rows


def transcribe_rows(root: Path, rows: list[dict[str, str]], checkpoint: str) -> list[dict]:
    try:
        import soundfile as sf
        from transformers import pipeline
    except ImportError as error:
        raise SystemExit(
            "Install ASR dependencies with: python -m pip install -r requirements.txt"
        ) from error

    recognizer = pipeline(
        "automatic-speech-recognition",
        model=MODEL_CHECKPOINTS[checkpoint],
        chunk_length_s=30,
        device=-1,
    )
    results = []
    started = perf_counter()
    for index, row in enumerate(rows, start=1):
        audio_path = root / row["local_audio"]
        audio, sample_rate = sf.read(audio_path)
        output = recognizer({"raw": audio, "sampling_rate": sample_rate})
        hypothesis = output["text"].strip()
        results.append(
            {
                "config": row["config"],
                "local_audio": row["local_audio"],
                "reference": row["transcription"],
                "hypothesis": hypothesis,
                "wer": calculate_wer(row["transcription"], hypothesis),
                "entity_accuracy": calculate_entity_accuracy(row["transcription"], hypothesis),
            }
        )
        if index % 10 == 0:
            print(f"{checkpoint}: transcribed {index}/{len(rows)}")
    elapsed = perf_counter() - started
    return results, elapsed


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate three ASR checkpoints on AfriSwitch.")
    parser.add_argument("--root", default="./clinical_validation/afriswitch")
    parser.add_argument("--configs", nargs="+", default=["amharic", "oromo"])
    parser.add_argument("--limit-per-config", type=int, default=10)
    parser.add_argument(
        "--models",
        nargs="+",
        choices=sorted(MODEL_CHECKPOINTS),
        default=list(MODEL_CHECKPOINTS),
    )
    parser.add_argument("--output", default="./clinical_validation/afriswitch/asr_results.json")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    rows = load_rows(root, args.configs, args.limit_per_config)
    report = {
        "dataset": "intronhealth/AfriSwitch",
        "evaluation_type": "real_audio_inference",
        "configs": args.configs,
        "utterances_per_config": args.limit_per_config,
        "models": {},
        "limitations": [
            "Whisper checkpoints are multilingual model checkpoints, not clinical validation models.",
            "Results are not evidence of diagnostic or medication safety.",
        ],
    }
    for checkpoint in args.models:
        print(f"Loading {checkpoint} ({MODEL_CHECKPOINTS[checkpoint]})")
        predictions, elapsed = transcribe_rows(root, rows, checkpoint)
        report["models"][checkpoint] = {
            "checkpoint": MODEL_CHECKPOINTS[checkpoint],
            "utterances": len(predictions),
            "elapsed_seconds": round(elapsed, 2),
            "mean_wer": round(sum(item["wer"] for item in predictions) / len(predictions), 4),
            "mean_entity_accuracy": round(
                sum(item["entity_accuracy"] for item in predictions) / len(predictions), 4
            ),
            "predictions": predictions,
        }

    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"ASR report exported to {output_path}")


if __name__ == "__main__":
    main()
