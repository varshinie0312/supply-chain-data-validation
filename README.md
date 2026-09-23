# Supply Chain Master-Data Validation

A configurable pre-load data-quality gate for supply chain planning systems.

When master data is loaded from an ERP into a planning platform, a single bad key
can silently distort a forecast weeks later — an orphan item that drops out of a
grain, a duplicate location that double-counts demand, a negative quantity that
skews a baseline. This runs the checks *before* the load and produces a pass/fail
report, so problems are caught at the source instead of during a planning cycle.

## What it checks

| Check | What it catches |
|---|---|
| `not_null` | Missing mandatory attributes (item description, UOM, region) |
| `unique_key` | Duplicate keys — the usual cause of double-counted demand |
| `allowed_values` | Values outside the agreed domain (e.g. `uom` must be EA/CS/KG/LT) |
| `non_negative` | Negative or non-numeric quantities and durations |
| `referential_integrity` | Transaction rows pointing at items or locations that don't exist |

Checks are declared in YAML, not hard-coded, so a new interface is onboarded by
adding a block rather than editing Python.

## Usage

```bash
pip install -r requirements.txt
python validate.py --config checks.yaml
python validate.py --config checks.yaml --fail-fast   # exit 1 on any failure (CI gate)
```

## Example output

The bundled sample data contains deliberate defects so the report is not empty:

```
loaded item_master: 42 rows, 5 columns
loaded location_master: 18 rows, 4 columns
loaded sales_history: 2,883 rows, 4 columns

21 checks run, 8 failed -> validation_report.csv

      dataset                 check          column  failed_rows  total_rows status                                     detail
  item_master              not_null     description            1          42   FAIL
  item_master            unique_key         item_id            2          42   FAIL                      e.g. ITM0007; ITM0007
  item_master        allowed_values             uom            1          42   FAIL                            unexpected: BOX
  item_master        allowed_values      item_class            1          42   FAIL                              unexpected: D
  item_master          non_negative shelf_life_days            1          42   FAIL
sales_history          non_negative        quantity            1        2883   FAIL
sales_history referential_integrity         item_id            1        2883   FAIL    orphan keys not in item_master: ITM9999
sales_history referential_integrity     location_id            1        2883   FAIL orphan keys not in location_master: LOC999
```

`--fail-fast` makes this usable as a gate in a scheduled load or CI pipeline.

## Configuration

```yaml
datasets:
  sales_history:
    path: sample_data/sales_history.csv
    checks:
      not_null: [item_id, location_id, period, quantity]
      unique_key: [item_id, location_id, period]
      non_negative: [quantity]
      referential_integrity:
        - column: item_id
          references: item_master
          referenced_column: item_id
```

## Layout

```
validate.py            check implementations and CLI
checks.yaml            declarative check configuration
sample_data/           synthetic item, location and sales-history extracts
requirements.txt       pandas, PyYAML
```

## Notes

All data in this repository is synthetic and generated for demonstration.
The approach reflects pre-load validation patterns used on ERP-to-planning
integrations; no client data or configuration is included.

## Possible extensions

- Row-level rejection files alongside the summary report
- Threshold-based checks (warn at 1% failures, fail at 5%)
- Profiling output: cardinality, null rate and value distribution per column
