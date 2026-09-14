"""Upload approved clinical validation recordings through the local Intron bridge."""

import argparse
import csv
import json
from pathlib import Path

import requests


def load_references(path: Path) -> dict[str, dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return {row["case_id"]: row for row in csv.DictReader(handle)}


def canonical_audio(root: Path, case_id: str) -> Path:
    candidates = [
        root / f"{case_id}_.m4a",
        root / f"{case_id}.m4a",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"No canonical recording found for {case_id}")


def main() -> None:
    project_root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(
        description="Upload the approved canonical clinical validation recordings."
    )
    parser.add_argument(
        "--input",
        default=str(project_root / "clinical_validation" / "inputs"),
        help="Directory containing the recordings and reference CSV",
    )
    parser.add_argument("--endpoint", default="http://127.0.0.1:8000/api/intron/stt/upload-sync")
    parser.add_argument("--output", default="clinical_validation_upload_results.json")
    parser.add_argument("--upload", action="store_true", help="Perform uploads; otherwise validate only")
    args = parser.parse_args()

    root = Path(args.input).resolve()
    references = load_references(root / "CLINICAL_REFERENCE_TRANSCRIPTS.csv")
    cases = sorted(references)
    results = []
    for case_id in cases:
        audio_path = canonical_audio(root, case_id)
        result = {
            "case_id": case_id,
            "audio_file": audio_path.name,
            "language_pair": references[case_id]["language_pair"],
            "reference_transcript": references[case_id]["reference_transcript"],
            "target_terms": references[case_id]["target_terms"],
            "upload_status": "validated_only",
        }
        if args.upload:
            with audio_path.open("rb") as audio_file:
                response = requests.post(
                    args.endpoint,
                    files={
                        "audio_file_blob": (
                            audio_path.name,
                            audio_file,
                            "audio/mp4",
                        )
                    },
                    data={
                        "audio_file_name": audio_path.name,
                        "use_language_asr_input": "am",
                        "use_category": "file_category_telehealth",
                        "use_disable_llm_corrections": "FALSE",
                    },
                    timeout=130,
                )
            try:
                body = response.json()
            except ValueError:
                body = {"raw_response": response.text[:1000]}
            result["http_status"] = response.status_code
            result["response"] = body
            result["upload_status"] = "uploaded" if response.ok else "failed"
        results.append(result)
        print(f"{case_id}: {result['upload_status']} ({audio_path.name})")

    output_path = Path(args.output).resolve()
    output_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Results written to {output_path}")
    if args.upload and any(item["upload_status"] != "uploaded" for item in results):
        raise SystemExit("One or more clinical uploads failed.")


if __name__ == "__main__":
    main()
