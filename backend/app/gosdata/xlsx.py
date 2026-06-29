"""Чтение .xlsx без внешних зависимостей: stdlib zipfile + ElementTree.

Понимает оба представления текста: inlineStr (наш шаблон) и sharedStrings (как
сохраняет Excel). Разрежённые ячейки выравниваются по колонке из атрибута r."""
from __future__ import annotations

import io
import zipfile
import xml.etree.ElementTree as ET

_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def _col_index(ref: str) -> int:
    """'C2' → 2 (0-based индекс колонки)."""
    letters = "".join(ch for ch in ref if ch.isalpha()).upper()
    idx = 0
    for ch in letters:
        idx = idx * 26 + (ord(ch) - 64)
    return idx - 1 if idx else 0


def _cell_text(c: ET.Element, shared: list[str]) -> str:
    t = c.get("t")
    if t == "s":  # shared string — индекс в общей таблице
        v = c.find(f"{_NS}v")
        if v is not None and v.text is not None:
            i = int(v.text)
            return shared[i] if 0 <= i < len(shared) else ""
        return ""
    if t == "inlineStr":
        is_ = c.find(f"{_NS}is")
        return "".join(tt.text or "" for tt in is_.iter(f"{_NS}t")) if is_ is not None else ""
    v = c.find(f"{_NS}v")  # число/прочее
    return v.text if (v is not None and v.text is not None) else ""


def read_xlsx_rows(data: bytes) -> list[list[str]]:
    z = zipfile.ZipFile(io.BytesIO(data))
    names = z.namelist()
    shared: list[str] = []
    if "xl/sharedStrings.xml" in names:
        sroot = ET.fromstring(z.read("xl/sharedStrings.xml"))
        for si in sroot.findall(f"{_NS}si"):
            shared.append("".join(t.text or "" for t in si.iter(f"{_NS}t")))
    sheet = next((n for n in sorted(names)
                  if n.startswith("xl/worksheets/") and n.endswith(".xml")), None)
    if not sheet:
        return []
    root = ET.fromstring(z.read(sheet))
    rows: list[list[str]] = []
    for r in root.iter(f"{_NS}row"):
        cells: dict[int, str] = {}
        maxc = -1
        for c in r.findall(f"{_NS}c"):
            ci = _col_index(c.get("r", "A"))
            cells[ci] = (_cell_text(c, shared) or "").strip()
            maxc = max(maxc, ci)
        rows.append([cells.get(i, "") for i in range(maxc + 1)])
    return rows


def read_xlsx_dicts(data: bytes) -> list[dict]:
    """Строки .xlsx → список dict (первая непустая строка — заголовки колонок)."""
    rows = [r for r in read_xlsx_rows(data) if any(c.strip() for c in r)]
    if not rows:
        return []
    headers = [h.strip() for h in rows[0]]
    return [
        {headers[i]: (r[i] if i < len(r) else "") for i in range(len(headers)) if headers[i]}
        for r in rows[1:]
    ]
