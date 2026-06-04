import json
from pathlib import Path


def test_template_files_have_expected_shape() -> None:
    template_dir = Path(".template/beishida_math_json_v3_with_template")
    files = sorted(template_dir.glob("G*.json"))
    assert files

    for file in files:
        data = json.loads(file.read_text(encoding="utf-8"))
        assert "meta" in data
        assert "shared_skill_catalog" in data
        assert "semester" in data
        assert data["semester"]["chapters"]
