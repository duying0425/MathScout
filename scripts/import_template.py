from __future__ import annotations

import argparse
import json
from pathlib import Path


def inspect_template(template_dir: Path) -> None:
    files = sorted(template_dir.glob("G*.json"))
    for file in files:
        data = json.loads(file.read_text(encoding="utf-8"))
        semester = data["semester"]
        chapters = semester.get("chapters", [])
        section_count = sum(len(chapter.get("sections", [])) for chapter in chapters)
        print(f"{file.name}: {len(chapters)} chapters, {section_count} sections")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=["inspect-template"],
        help="Template utility command to run.",
    )
    parser.add_argument(
        "--template-dir",
        type=Path,
        default=Path(".template/beishida_math_json_v3_with_template"),
        help="Directory containing semester JSON files.",
    )
    args = parser.parse_args()

    if args.command == "inspect-template":
        inspect_template(args.template_dir)
