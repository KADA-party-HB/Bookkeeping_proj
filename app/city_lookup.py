from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path


_NON_ALNUM_RE = re.compile(r"[^0-9a-zA-Z\u00c0-\u024f]+")


def _normalize_text(value: str | None) -> str:
    text = unicodedata.normalize("NFKC", value or "")
    text = text.casefold()
    text = "".join(
        char for char in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(char)
    )
    text = _NON_ALNUM_RE.sub(" ", text)
    return " ".join(text.split())


@lru_cache(maxsize=1)
def _city_candidates():
    data_path = Path(__file__).with_name("citys.json")
    rows = json.loads(data_path.read_text(encoding="utf-8"))

    by_normalized_name: dict[str, dict] = {}
    for row in rows:
        population = row.get("population") or 0
        for raw_name in (row.get("locality"), row.get("municipality")):
            normalized_name = _normalize_text(raw_name)
            if not normalized_name:
                continue

            current = by_normalized_name.get(normalized_name)
            candidate = {
                "normalized_name": normalized_name,
                "display_name": (raw_name or "").strip(),
                "population": population,
                "word_count": len(normalized_name.split()),
                "length": len(normalized_name),
            }

            if current is None or (
                candidate["population"],
                candidate["word_count"],
                candidate["length"],
            ) > (
                current["population"],
                current["word_count"],
                current["length"],
            ):
                by_normalized_name[normalized_name] = candidate

    return sorted(
        by_normalized_name.values(),
        key=lambda item: (
            item["word_count"],
            item["length"],
            item["population"],
        ),
        reverse=True,
    )


def extract_city_name(*parts: str | None) -> str | None:
    normalized_parts = [_normalize_text(part) for part in parts if part]
    normalized_parts = [part for part in normalized_parts if part]
    if not normalized_parts:
        return None

    # Respect field priority. A delivery address match should beat an older
    # customer postal city value if both happen to be present on the booking.
    for normalized_part in normalized_parts:
        search_text = f" {normalized_part} "
        for candidate in _city_candidates():
            name = candidate["normalized_name"]
            if f" {name} " in search_text:
                return candidate["display_name"]

    return None
