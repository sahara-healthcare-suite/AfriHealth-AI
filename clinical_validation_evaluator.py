"""Score private clinical ASR results and emit a privacy-safe aggregate report."""

import argparse
import json
import re
from pathlib import Path


CRITICAL_TERMS = {
    "CS-02": ["Amoxicillin", "500mg", "TID"],
    "CS-05": ["125mg/5mL", "PO TID"],
    "CS-06": ["Metformin", "BID"],
    "CS-09": ["38 weeks", "ruptured membranes"],
    "CS-11": ["GeneXpert", "TB"],
    "CS-14": ["Ceftriaxone"],
    "CS-15": ["meningitis"],
}


def tokens(value: str) -> list[str]:
    return re.findall(r"[\w\u1200-\u137f]+", value.lower(), re.UNICODE)


def wer(reference: str, hypothesis: str) -> float:
    expected = tokens(reference)
    actual = tokens(hypothesis)
    previous = list(range(len(actual) + 1))
    for row, expected_token in enumerate(expected, start=1):
        current = [row]
        for column, actual_token in enumerate(actual, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[column] + 1,
                    previous[column - 1] + (expected_token != actual_token),
                )
            )
        previous = current
    return previous[-1] / max(1, len(expected))


def contains_term(hypothesis: str, term: str) -> bool:
    hypothesis_tokens = tokens(hypothesis)
    term_tokens = tokens(term)
    return bool(term_tokens) and all(token in hypothesis_tokens for token in term_tokens)


def evaluate(results_path: Path, model_name: str) -> dict:
    private_results = json.loads(results_path.read_text(encoding="utf-8"))
    cases = []
    for item in private_results:
        response_data = item.get("response", {}).get("data", {})
        hypothesis = item.get("transcript") or response_data.get("audio_transcript", "")
        reference = item.get("reference_transcript", "")
        target_terms = [
            term.strip().strip('"')
            for term in item.get("target_terms", "").split(";")
            if term.strip()
        ]
        matched_terms = [term for term in target_terms if contains_term(hypothesis, term)]
        critical_terms = CRITICAL_TERMS.get(item["case_id"], [])
        critical_misses = [
            term for term in critical_terms if not contains_term(hypothesis, term)
        ]
        cases.append(
            {
                "case_id": item["case_id"],
                "wer": round(wer(reference, hypothesis), 4),
                "target_term_recall": round(
                    len(matched_terms) / max(1, len(target_terms)), 4
                ),
                "critical_term_miss_count": len(critical_misses),
            }
        )

    if not cases:
        raise ValueError("The private result file contains no cases.")
    return {
        "report_type": "clinical_asr_validation_aggregate",
        "report_version": "1.1",
        "evaluation_method": "token-level WER and exact normalized target-term matching",
        "source": "reviewed simulated clinical recording results",
        "cases_evaluated": len(cases),
        "models": {
            model_name: {
                "cases": len(cases),
                "mean_word_error_rate": round(
                    sum(case["wer"] for case in cases) / len(cases), 4
                ),
                "mean_target_term_recall": round(
                    sum(case["target_term_recall"] for case in cases) / len(cases), 4
                ),
                "cases_with_critical_term_misses": sum(
                    case["critical_term_miss_count"] > 0 for case in cases
                ),
            }
        },
        "privacy": {
            "raw_audio": "excluded",
            "full_transcripts": "excluded",
            "provider_file_ids": "excluded",
            "per_case_error_details": "excluded",
        },
        "interpretation": {
            "status": "baseline_for_clinician_review",
            "autonomous_clinical_use": False,
            "note": "Critical-term misses require clinician review and must not be silently corrected by the application.",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--results",
        default=r"C:\Users\kingr\Desktop\clinical-validation-inputs\upload_results.json",
        help="Private upload result JSON; do not commit this file.",
    )
    parser.add_argument(
        "--output",
        default="clinical_validation_model_report.json",
        help="Aggregate output path.",
    )
    parser.add_argument(
        "--model-name",
        default="intron_sahara_v2.5",
        help="Stable model identifier for the aggregate report.",
    )
    args = parser.parse_args()
    report = evaluate(Path(args.results).resolve(), args.model_name)
    output_path = Path(args.output).resolve()
    output_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps(report["models"], indent=2))
    print(f"Aggregate report written to {output_path}")


if __name__ == "__main__":
    main()
