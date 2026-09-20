#!/usr/bin/env python3
"""Inspect CSV/TSV experiment data and emit a reproducible quality summary."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
from collections import Counter
from pathlib import Path
from portable_io import configure_utf8


MISSING = {"", "na", "n/a", "nan", "null", "none", "-", "--"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data", type=Path)
    parser.add_argument("--delimiter", help="Override delimiter, e.g. ',' or '\\t'")
    parser.add_argument("--encoding", default="utf-8-sig")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--max-rows", type=int, default=200_000)
    parser.add_argument("--decimal-separator", choices=(".", ","), default=".")
    parser.add_argument("--thousands-separator", default=",", help="Use an empty string to disable grouping")
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def detect_delimiter(sample: str, override: str | None) -> str:
    if override:
        return "\t" if override == r"\t" else override
    try:
        return csv.Sniffer().sniff(sample, delimiters=",\t;|").delimiter
    except csv.Error:
        return ","


def to_number(value: str, decimal_separator: str = ".", thousands_separator: str = ",") -> float | None:
    cleaned = value.strip()
    if thousands_separator:
        cleaned = cleaned.replace(thousands_separator, "")
    cleaned = cleaned.replace(decimal_separator, ".")
    if cleaned.lower() in MISSING:
        return None
    try:
        number = float(cleaned)
        return number if math.isfinite(number) else None
    except ValueError:
        return None


def inspect(path: Path, encoding: str, delimiter_override: str | None, max_rows: int, decimal_separator: str = ".", thousands_separator: str = ",") -> dict:
    if max_rows < 1:
        raise ValueError("max_rows must be positive")
    if decimal_separator not in {".", ","} or len(thousands_separator) > 1 or thousands_separator == decimal_separator:
        raise ValueError("Decimal and thousands separators must be distinct single characters")
    with path.open("r", encoding=encoding, newline="") as stream:
        sample = stream.read(8192)
        stream.seek(0)
        delimiter = detect_delimiter(sample, delimiter_override)
        reader = csv.DictReader(stream, delimiter=delimiter)
        if not reader.fieldnames:
            raise ValueError("No header row found")
        fieldnames = [name.strip() if name else "" for name in reader.fieldnames]
        if any(not name for name in fieldnames) or len(set(fieldnames)) != len(fieldnames):
            raise ValueError("Column headers must be nonempty and unique after trimming")
        values = {name: [] for name in fieldnames}
        row_count = 0
        truncated = False
        width_issues = 0
        for row in reader:
            if row_count >= max_rows:
                truncated = True
                break
            row_count += 1
            if None in row or any(value is None for value in row.values()):
                width_issues += 1
            for original, name in zip(reader.fieldnames, fieldnames):
                values[name].append((row.get(original) or "").strip())

    columns = []
    for name in fieldnames:
        data = values[name]
        missing_count = sum(value.lower() in MISSING for value in data)
        nonmissing = [value for value in data if value.lower() not in MISSING]
        numeric = [number for value in nonmissing if (number := to_number(value, decimal_separator, thousands_separator)) is not None]
        numeric_ratio = len(numeric) / len(nonmissing) if nonmissing else 0.0
        item = {
            "name": name,
            "row_count": row_count,
            "missing_count": missing_count,
            "missing_rate": round(missing_count / row_count, 6) if row_count else 0.0,
            "unique_count": len(set(nonmissing)),
            "numeric_ratio": round(numeric_ratio, 6),
        }
        if numeric and numeric_ratio >= 0.8:
            item["numeric"] = {
                "count": len(numeric),
                "min": min(numeric),
                "max": max(numeric),
                "mean": statistics.fmean(numeric),
                "median": statistics.median(numeric),
            }
        elif nonmissing:
            item["top_values"] = Counter(nonmissing).most_common(10)
        columns.append(item)

    return {
        "path": str(path.resolve()),
        "sha256": sha256_file(path),
        "encoding": encoding,
        "decimal_separator": decimal_separator,
        "thousands_separator": thousands_separator,
        "delimiter": "\\t" if delimiter == "\t" else delimiter,
        "row_count": row_count,
        "column_count": len(fieldnames),
        "truncated": truncated,
        "row_width_issues": width_issues,
        "columns": columns,
    }


def main() -> int:
    configure_utf8()
    args = parse_args()
    path = args.data.expanduser().resolve()
    if not path.is_file():
        raise SystemExit(f"Data file not found: {path}")
    data = inspect(path, args.encoding, args.delimiter, args.max_rows, args.decimal_separator, args.thousands_separator)
    content = json.dumps(data, ensure_ascii=False, indent=2)
    if args.output:
        output = args.output.expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(content, encoding="utf-8")
        print(output)
    else:
        print(content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
