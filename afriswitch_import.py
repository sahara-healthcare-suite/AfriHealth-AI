"""Import the gated AfriSwitch benchmark into a local manifest and audio folder."""

import argparse
import csv
import json
import os
from pathlib import Path

from datasets import Audio, get_dataset_config_names, load_dataset

DATASET_ID = "intronhealth/AfriSwitch"
DATASET_REVISION = "c24748242a2b435392f9b4c38ac7d3a96fc82ef9"


def safe_name(value: str) -> str:
    return "".join(character if character.isalnum() or character in "-_." else "_" for character in value)


def import_config(config_name: str, output_root: Path, token: str) -> int:
    dataset = load_dataset(
        DATASET_ID,
        config_name,
        split="test",
        token=token,
    )
    # Export the source bytes directly so Windows does not require FFmpeg/
    # torchcodec just to copy benchmark audio into the local evaluation set.
    dataset = dataset.cast_column("audio", Audio(decode=False))
    audio_root = output_root / "audio" / config_name
    audio_root.mkdir(parents=True, exist_ok=True)
    manifest_path = output_root / "manifests" / f"{config_name}.csv"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    count = 0
    with manifest_path.open("w", newline="", encoding="utf-8") as manifest_file:
        writer = csv.DictWriter(
            manifest_file,
            fieldnames=[
                "dataset_id",
                "dataset_revision",
                "config",
                "split",
                "filename",
                "local_audio",
                "language",
                "duration",
                "transcription",
                "transcription_tagged",
                "cmi",
                "num_switch_points",
            ],
        )
        writer.writeheader()
        for index, row in enumerate(dataset):
            audio = row["audio"]
            source_name = row.get("filename") or f"{config_name}_{index:06d}.wav"
            local_name = safe_name(f"{index:06d}_{Path(source_name).name}")
            local_path = audio_root / local_name
            audio_bytes = audio.get("bytes")
            if not audio_bytes:
                raise RuntimeError(f"Audio bytes missing for {config_name} row {index}")
            local_path.write_bytes(audio_bytes)
            writer.writerow(
                {
                    "dataset_id": DATASET_ID,
                    "dataset_revision": DATASET_REVISION,
                    "config": config_name,
                    "split": "test",
                    "filename": source_name,
                    "local_audio": str(local_path.relative_to(output_root)),
                    "language": row.get("language", config_name),
                    "duration": row.get("duration", ""),
                    "transcription": row.get("transcription", ""),
                    "transcription_tagged": row.get("transcription_tagged", ""),
                    "cmi": row.get("cmi", ""),
                    "num_switch_points": row.get("num_switch_points", ""),
                }
            )
            count += 1
            if count % 100 == 0:
                print(f"{config_name}: imported {count} utterances")
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="Import a bounded AfriSwitch test benchmark pilot.")
    parser.add_argument("--output", default="./clinical_validation/afriswitch", help="Local output directory")
    parser.add_argument(
        "--configs",
        nargs="*",
        help="Optional configs; defaults to the Amharic and Oromo pilot",
    )
    parser.add_argument(
        "--all-configs",
        action="store_true",
        help="Import every dataset config; this may require approximately 23.5 GB",
    )
    args = parser.parse_args()

    token = os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_HUB_TOKEN")
    if not token:
        raise SystemExit("Set HF_TOKEN locally before importing the gated dataset; never commit the token.")

    output_root = Path(args.output).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    if args.configs and args.all_configs:
        raise SystemExit("Use either --configs or --all-configs, not both.")
    configs = args.configs
    if args.all_configs:
        configs = get_dataset_config_names(DATASET_ID, token=token)
    if not configs:
        configs = ["amharic", "oromo"]
    totals = {config: import_config(config, output_root, token) for config in configs}
    (output_root / "import_metadata.json").write_text(
        json.dumps(
            {
                "dataset_id": DATASET_ID,
                "dataset_revision": DATASET_REVISION,
                "split": "test",
                "configs": configs,
                "utterances_by_config": totals,
                "total_utterances": sum(totals.values()),
                "license": "CC BY-NC-SA 4.0",
                "import_note": "Bounded evaluation-only pilot; not a clinical validation dataset.",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Imported {sum(totals.values())} utterances into {output_root}")


if __name__ == "__main__":
    main()
