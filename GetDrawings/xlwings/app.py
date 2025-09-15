from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

import xlwings as xw

# Import your Teamcenter client (pythonnet-based)
import tc_client_net as tcnet


@dataclass(frozen=True)
class JobResult:
    item_id: str
    ok: bool
    message: str
    output_path: Optional[Path]


def _read_item_ids(sheet: xw.Sheet, start_cell: str = "A2") -> List[str]:
    """Read a single column of item IDs until the first empty cell."""
    rng = sheet.range(start_cell).expand("down")
    values = rng.options(ndim=1).value
    if values is None:
        return []
    return [str(v).strip() for v in values if v]

def _write_status(
    sheet: xw.Sheet, results: Iterable[JobResult], start_cell: str = "B1"
) -> None:
    """Write a 3-column status table: Item ID | Status | Path/Message."""
    header = ["Item ID", "Status", "Details"]
    rows: List[List[str]] = []
    for r in results:
        rows.append([
            r.item_id,
            "OK" if r.ok else "ERROR",
            str(r.output_path) if (r.ok and r.output_path) else r.message
        ])

    top_left = sheet.range(start_cell)
    top_left.value = header
    if rows:
        top_left.offset(1, 0).value = rows
    # Optional: set as table, autofit
    sheet.autofit()

def _default_output_dir() -> Path:
    base = Path.home() / "Downloads" / "TC_Drawings"
    base.mkdir(parents=True, exist_ok=True)
    run_dir = base / xw.utils.rand()  # quick unique folder
    run_dir.mkdir(exist_ok=True)
    return run_dir

@xw.sub
def download_drawings_from_sheet() -> None:
    """Excel button entry point: reads Items from column A, downloads PDFs."""
    wb = xw.Book.caller()
    sheet = wb.sheets["Items"]  # Column A: header in A1, data from A2
    out_sheet = wb.sheets.get("Log") or wb.sheets.add("Log")

    item_ids = _read_item_ids(sheet)
    if not item_ids:
        out_sheet.range("B1").value = ["Nothing to do – no Item IDs found"]
        return

    # Where to save PDFs
    output_dir = _default_output_dir()

    # Read credentials/config from a "Config" sheet (cells B2..B4), or env
    cfg_sheet = wb.sheets.get("Config")
    if cfg_sheet:
        server_url = cfg_sheet.range("B2").value or ""
        username = cfg_sheet.range("B3").value or ""
        password = cfg_sheet.range("B4").value or ""
    else:
        server_url = ""
        username = ""
        password = ""

    client = tcnet.TeamcenterClient(
        server_url=server_url or None,
        username=username or None,
        password=password or None,
    )

    results: List[JobResult] = []
    with client.session() as sess:
        for item_id in item_ids:
            try:
                local_pdf: Path = sess.download_latest_pdf_for_item(
                    item_id=item_id,
                    dest_dir=output_dir,
                )
                results.append(JobResult(item_id, True, "Downloaded", local_pdf))
            except Exception as ex:  # noqa: BLE001
                results.append(JobResult(item_id, False, str(ex), None))

    _write_status(out_sheet, results)
    xw.apps.active.api.ActiveWorkbook.Application.StatusBar = (
        f"Done. Files in: {output_dir}"
    )
