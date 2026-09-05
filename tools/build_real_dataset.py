"""Build the real-data Parquet file from the UCI Online Retail II archive.

The source is invoice *lines*. A line is not a transaction, so lines are
aggregated up to one row per invoice, which is the unit a risk engine should
actually score. Uses only the standard library plus pandas, so no Excel reader
needs to be installed.

Source: https://archive.ics.uci.edu/dataset/502/online+retail+ii
Run:    python tools/build_real_dataset.py path/to/online+retail+ii.zip
"""

from __future__ import annotations

import sys
import zipfile
from datetime import datetime, timedelta
from xml.etree.ElementTree import iterparse

import pandas as pd

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
EXCEL_EPOCH = datetime(1899, 12, 30)
HEADERS = ["Invoice", "StockCode", "Description", "Quantity", "InvoiceDate", "Price", "CustomerID", "Country"]


def _col_index(ref: str) -> int:
    """'A2' -> 0, 'H2' -> 7."""
    letters = "".join(ch for ch in ref if ch.isalpha())
    idx = 0
    for ch in letters:
        idx = idx * 26 + (ord(ch.upper()) - 64)
    return idx - 1


def _shared_strings(xlsx: zipfile.ZipFile) -> list[str]:
    strings: list[str] = []
    with xlsx.open("xl/sharedStrings.xml") as fh:
        buf: list[str] = []
        for event, el in iterparse(fh, events=("end",)):
            if el.tag == f"{NS}t":
                buf.append(el.text or "")
            elif el.tag == f"{NS}si":
                strings.append("".join(buf))
                buf.clear()
                el.clear()
    return strings


def _rows(xlsx: zipfile.ZipFile, sheet: str, shared: list[str]):
    """Yield each sheet row as a list of 8 raw cell values."""
    with xlsx.open(sheet) as fh:
        for event, el in iterparse(fh, events=("end",)):
            if el.tag != f"{NS}row":
                continue
            cells: list[object] = [None] * len(HEADERS)
            for c in el.findall(f"{NS}c"):
                ref = c.get("r") or ""
                i = _col_index(ref)
                if i < 0 or i >= len(HEADERS):
                    continue
                t = c.get("t")
                if t == "inlineStr":
                    node = c.find(f"{NS}is/{NS}t")
                    cells[i] = node.text if node is not None else None
                    continue
                v = c.find(f"{NS}v")
                if v is None or v.text is None:
                    continue
                if t == "s":
                    cells[i] = shared[int(v.text)]
                else:
                    cells[i] = v.text
            yield cells
            el.clear()


def _to_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def extract(zip_path: str) -> pd.DataFrame:
    outer = zipfile.ZipFile(zip_path)
    inner_name = next(n for n in outer.namelist() if n.endswith(".xlsx"))
    xlsx = zipfile.ZipFile(outer.open(inner_name))

    shared = _shared_strings(xlsx)
    print(f"shared strings: {len(shared):,}")

    invoices: dict[str, dict] = {}
    seen = 0

    for sheet in ("xl/worksheets/sheet1.xml", "xl/worksheets/sheet2.xml"):
        for cells in _rows(xlsx, sheet, shared):
            if not cells[0] or cells[0] == "Invoice":
                continue
            qty = _to_float(cells[3])
            price = _to_float(cells[5])
            serial = _to_float(cells[4])
            if qty is None or price is None or serial is None:
                continue

            seen += 1
            inv = str(cells[0])
            rec = invoices.get(inv)
            if rec is None:
                rec = invoices[inv] = {
                    "invoice": inv,
                    "timestamp": EXCEL_EPOCH + timedelta(days=serial),
                    "customer_id": str(cells[6]) if cells[6] else "GUEST",
                    "country": str(cells[7]) if cells[7] else "Unspecified",
                    "amount": 0.0,
                    "n_items": 0,
                    "n_units": 0.0,
                    "max_unit_price": 0.0,
                    "is_cancellation": inv.upper().startswith("C"),
                }
            rec["amount"] += qty * price
            rec["n_items"] += 1
            rec["n_units"] += qty
            rec["max_unit_price"] = max(rec["max_unit_price"], price)

        print(f"{sheet}: cumulative lines={seen:,} invoices={len(invoices):,}")

    df = pd.DataFrame(list(invoices.values()))
    df["amount"] = df["amount"].round(2)
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df


def main() -> None:
    zip_path = sys.argv[1] if len(sys.argv) > 1 else "online+retail+ii.zip"
    df = extract(zip_path)
    print(f"\ninvoices: {len(df):,}")
    print(f"date range: {df['timestamp'].min()} .. {df['timestamp'].max()}")
    print(f"countries: {df['country'].nunique()}")
    print(f"cancellations: {int(df['is_cancellation'].sum()):,}")
    df.to_parquet("data/transactions.parquet", index=False, compression="zstd")
    print("wrote data/transactions.parquet")


if __name__ == "__main__":
    main()
