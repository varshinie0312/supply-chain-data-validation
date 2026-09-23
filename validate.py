"""Master-data validation for supply chain planning loads.

Runs a configurable set of data-quality checks over item, location and
sales-history extracts before they are loaded into a planning platform,
and writes a pass/fail report. Modelled on the kind of pre-load gate used
on ERP-to-APS integrations, where a single bad key silently breaks a
downstream forecast.

Usage:
    python validate.py --config checks.yaml
    python validate.py --config checks.yaml --report report.csv --fail-fast
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import yaml


@dataclass
class CheckResult:
    dataset: str
    check: str
    column: str
    failed_rows: int
    total_rows: int
    status: str
    detail: str

    @property
    def as_row(self) -> dict:
        return {
            "dataset": self.dataset,
            "check": self.check,
            "column": self.column,
            "failed_rows": self.failed_rows,
            "total_rows": self.total_rows,
            "status": self.status,
            "detail": self.detail,
        }


def _result(dataset, check, column, failed, total, detail="") -> CheckResult:
    return CheckResult(
        dataset=dataset,
        check=check,
        column=column,
        failed_rows=int(failed),
        total_rows=int(total),
        status="PASS" if failed == 0 else "FAIL",
        detail=detail,
    )


def check_not_null(df: pd.DataFrame, dataset: str, columns: list[str]) -> list[CheckResult]:
    results = []
    for col in columns:
        if col not in df.columns:
            results.append(_result(dataset, "not_null", col, len(df), len(df), "column missing"))
            continue
        failed = df[col].isna().sum()
        results.append(_result(dataset, "not_null", col, failed, len(df)))
    return results


def check_unique(df: pd.DataFrame, dataset: str, keys: list[str]) -> list[CheckResult]:
    missing = [k for k in keys if k not in df.columns]
    if missing:
        return [_result(dataset, "unique_key", "+".join(keys), len(df), len(df), f"missing {missing}")]
    duplicated = df.duplicated(subset=keys, keep=False).sum()
    sample = ""
    if duplicated:
        dupes = df[df.duplicated(subset=keys, keep=False)][keys].head(3)
        sample = "e.g. " + "; ".join(dupes.astype(str).agg(" | ".join, axis=1))
    return [_result(dataset, "unique_key", "+".join(keys), duplicated, len(df), sample)]


def check_allowed_values(df: pd.DataFrame, dataset: str, spec: dict) -> list[CheckResult]:
    results = []
    for col, allowed in spec.items():
        if col not in df.columns:
            results.append(_result(dataset, "allowed_values", col, len(df), len(df), "column missing"))
            continue
        bad = ~df[col].isin(allowed) & df[col].notna()
        detail = ""
        if bad.any():
            detail = "unexpected: " + ", ".join(sorted(map(str, df.loc[bad, col].unique()))[:5])
        results.append(_result(dataset, "allowed_values", col, bad.sum(), len(df), detail))
    return results


def check_non_negative(df: pd.DataFrame, dataset: str, columns: list[str]) -> list[CheckResult]:
    results = []
    for col in columns:
        if col not in df.columns:
            results.append(_result(dataset, "non_negative", col, len(df), len(df), "column missing"))
            continue
        numeric = pd.to_numeric(df[col], errors="coerce")
        failed = ((numeric < 0) | numeric.isna()).sum()
        results.append(_result(dataset, "non_negative", col, failed, len(df)))
    return results


def check_referential_integrity(
    df: pd.DataFrame, dataset: str, spec: list[dict], loaded: dict[str, pd.DataFrame]
) -> list[CheckResult]:
    """Every foreign key in this dataset must exist in the parent dataset."""
    results = []
    for rule in spec:
        col, parent, parent_col = rule["column"], rule["references"], rule["referenced_column"]
        if parent not in loaded:
            results.append(_result(dataset, "referential_integrity", col, len(df), len(df), f"{parent} not loaded"))
            continue
        valid = set(loaded[parent][parent_col].dropna())
        orphans = df[~df[col].isin(valid) & df[col].notna()]
        detail = ""
        if len(orphans):
            detail = f"orphan keys not in {parent}: " + ", ".join(map(str, orphans[col].unique()[:5]))
        results.append(_result(dataset, "referential_integrity", col, len(orphans), len(df), detail))
    return results


CHECKS = {
    "not_null": check_not_null,
    "unique_key": check_unique,
    "allowed_values": check_allowed_values,
    "non_negative": check_non_negative,
}


def run(config_path: Path) -> pd.DataFrame:
    config = yaml.safe_load(config_path.read_text())
    base = config_path.parent
    loaded: dict[str, pd.DataFrame] = {}
    results: list[CheckResult] = []

    for name, spec in config["datasets"].items():
        df = pd.read_csv(base / spec["path"])
        loaded[name] = df
        print(f"loaded {name}: {len(df):,} rows, {len(df.columns)} columns")

    for name, spec in config["datasets"].items():
        df = loaded[name]
        for check_name, argument in spec.get("checks", {}).items():
            if check_name == "referential_integrity":
                results += check_referential_integrity(df, name, argument, loaded)
            elif check_name in CHECKS:
                results += CHECKS[check_name](df, name, argument)
            else:
                raise ValueError(f"unknown check '{check_name}' on dataset '{name}'")

    return pd.DataFrame([r.as_row for r in results])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("checks.yaml"))
    parser.add_argument("--report", type=Path, default=Path("validation_report.csv"))
    parser.add_argument("--fail-fast", action="store_true", help="exit 1 if any check fails")
    args = parser.parse_args()

    report = run(args.config)
    report.to_csv(args.report, index=False)

    failures = report[report["status"] == "FAIL"]
    print(f"\n{len(report)} checks run, {len(failures)} failed -> {args.report}\n")
    if len(failures):
        print(failures.to_string(index=False))
    else:
        print("all checks passed")

    return 1 if (len(failures) and args.fail_fast) else 0


if __name__ == "__main__":
    sys.exit(main())
