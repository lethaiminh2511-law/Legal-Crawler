from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_json(data: Any, output_path: str | Path, indent: int = 2) -> None:
    path = Path(output_path)
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=indent)
