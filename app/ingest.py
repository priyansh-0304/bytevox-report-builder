"""CSV ingestion: decode -> parse -> infer column types -> convert -> profile.

Rule: nothing is silently dropped.
  * A row that cannot be read is REJECTED with a line number and reason (listed in the profile).
  * A single unreadable value inside a good row becomes missing (None) and is counted + sampled
    in the profile as "invalid", so you can tell it apart from a blank.
"""
import csv
import io
import math
import re
from datetime import date, datetime

MISSING_TOKENS = {"", "na", "n/a", "null", "none", "nan", "-", "--", "?"}
TYPE_THRESHOLD = 0.9          # a column gets a type if >= 90% of its non-missing values fit it
CATEGORY_MAX_DISTINCT = 50
MAX_COLUMNS = 100
MAX_REJECTED_SHOWN = 100
MAX_INVALID_SAMPLES = 5
MAX_MALFORMED_LINES = 1000


class IngestError(Exception):
    """A problem with the whole file. `status` is the HTTP status the route should use."""

    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.message = message
        self.status = status


# ---------------------------------------------------------------- decoding

def decode_bytes(raw: bytes) -> str:
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        raise IngestError("This file is UTF-16 encoded. Re-save it as 'CSV UTF-8' and upload again.")
    if raw.startswith(b"PK") or raw.startswith(b"%PDF") or b"\x00" in raw[:8192]:
        raise IngestError(
            "This looks like a binary file (Excel, PDF or similar), not a CSV. "
            "In your spreadsheet app choose File > Save As > CSV UTF-8.",
            415,
        )
    try:
        return raw.decode("utf-8-sig")  # utf-8-sig also strips the BOM that Excel adds
    except UnicodeDecodeError as e:
        raise IngestError(
            f"The file is not valid UTF-8 text (first bad byte at position {e.start}). "
            "Re-save it as 'CSV UTF-8' and upload again."
        )


def detect_delimiter(text: str) -> str:
    """Pick whichever of , ; tab | appears most in the header line. Ties and no-match -> comma."""
    header_line = text.split("\n", 1)[0]
    best, best_count = ",", 0
    for d in (",", ";", "\t", "|"):
        count = header_line.count(d)
        if count > best_count:
            best, best_count = d, count
    return best


# ---------------------------------------------------------------- value parsing

_NUM = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$")
# 1,234,567.89 (western) or 12,34,567.89 (Indian) grouping
_GROUPED = re.compile(r"^[+-]?(\d{1,3}(,\d{3})+|\d{1,2}(,\d{2})+,\d{3})(\.\d+)?$")
_CURRENCY = re.compile(r"^([+-]?)\s*[$₹€£]\s*")


def parse_number(text: str):
    t = _CURRENCY.sub(r"\1", text.strip())
    if _GROUPED.match(t):
        t = t.replace(",", "")
    if not _NUM.match(t):
        return None
    value = float(t)
    return value if math.isfinite(value) else None


_ISO = re.compile(
    r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})"
    r"(?:[ T]\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:\s?(?:Z|[+-]\d{2}:?\d{2}))?)?$"
)
_DMY_OR_MDY = re.compile(r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})$")
_NAMED_FORMATS = ("%d-%b-%Y", "%d %b %Y", "%b %d, %Y", "%d %B %Y", "%B %d, %Y", "%d-%B-%Y")


def _valid(d: date):
    return d if 1900 <= d.year <= 2100 else None


def parse_date(text: str, dayfirst: bool = True):
    """Return a date or None. `dayfirst` only matters for 05/03/2024-style values."""
    t = text.strip()
    try:
        m = _ISO.match(t)
        if m:
            return _valid(date(int(m[1]), int(m[2]), int(m[3])))
        m = _DMY_OR_MDY.match(t)
        if m:
            a, b, y = int(m[1]), int(m[2]), int(m[3])
            day, month = (a, b) if dayfirst else (b, a)
            return _valid(date(y, month, day))
    except ValueError:  # e.g. 31/02/2024
        return None
    for fmt in _NAMED_FORMATS:
        try:
            return _valid(datetime.strptime(t, fmt).date())
        except ValueError:
            continue
    return None


def decide_dayfirst(values):
    """Look at slashed dates in a column and decide DD/MM vs MM/DD. Returns (dayfirst, warning|None)."""
    day_first = month_first = ambiguous = 0
    for v in values:
        m = _DMY_OR_MDY.match(v.strip())
        if not m:
            continue
        a, b = int(m[1]), int(m[2])
        if a > 12 and b <= 12:
            day_first += 1       # 25/03/2024 can only be day-first
        elif b > 12 and a <= 12:
            month_first += 1     # 03/25/2024 can only be month-first
        elif a <= 12 and b <= 12 and a != b:
            ambiguous += 1       # 03/04/2024 could be either
    if day_first and month_first:
        return True, "mixes DD/MM/YYYY and MM/DD/YYYY dates; read as DD/MM/YYYY, so some dates may be wrong or invalid"
    if month_first:
        return False, None
    if day_first:
        return True, None
    if ambiguous:
        return True, "has dates like 03/04/2024 that could be DD/MM or MM/DD; read as DD/MM/YYYY"
    return True, None


def clean(value: str):
    v = value.strip()
    return None if v.lower() in MISSING_TOKENS else v


def infer_column(name: str, raw: list):
    """raw: list of str|None. Returns (type, dayfirst, warnings)."""
    present = [v for v in raw if v is not None]
    n = len(present)
    if n == 0:
        return "text", True, [f'Column "{name}" has no values at all.']
    dayfirst, day_warning = decide_dayfirst(present)
    date_ok = sum(parse_date(v, dayfirst) is not None for v in present)
    num_ok = sum(parse_number(v) is not None for v in present)
    if date_ok / n >= TYPE_THRESHOLD and date_ok >= num_ok:
        warnings = [f'Column "{name}" {day_warning}.'] if day_warning else []
        return "date", dayfirst, warnings
    if num_ok / n >= TYPE_THRESHOLD:
        return "number", True, []
    distinct = len(set(present))
    if distinct <= CATEGORY_MAX_DISTINCT and distinct <= max(5, n // 2):
        return "category", True, []
    return "text", True, []


def convert(value, ctype: str, dayfirst: bool):
    """Returns (typed_value, invalid_reason). Missing stays missing with no reason."""
    if value is None:
        return None, None
    if ctype == "number":
        x = parse_number(value)
        return (x, None) if x is not None else (None, "not a valid number")
    if ctype == "date":
        d = parse_date(value, dayfirst)
        return (d.isoformat(), None) if d else (None, "not a valid date")
    return value, None


# ---------------------------------------------------------------- parsing

def _header_names(fields, warnings):
    names, seen = [], set()
    for i, f in enumerate(fields):
        name = f.strip()[:100] or f"column_{i + 1}"
        if not f.strip():
            warnings.append(f"Column {i + 1} had no header and was named {name}.")
        base, k = name, 2
        while name.lower() in seen:
            name = f"{base}_{k}"
            k += 1
        if name != base:
            warnings.append(f'Duplicate header "{base}" was renamed to "{name}".')
        seen.add(name.lower())
        names.append(name)
    return names


def _rejection(line, reason, fields):
    preview = ",".join(fields)
    return {"line": line, "reason": reason, "preview": preview[:200]}


def ingest_csv(raw: bytes, max_rows: int = 100_000):
    """Returns (profile, rows). rows = [(line_number, [typed values...])]."""
    text = decode_bytes(raw)
    delimiter = detect_delimiter(text)
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)

    try:
        header_fields = next(reader)
    except StopIteration:
        raise IngestError("The file is empty.")
    except csv.Error as e:
        raise IngestError(f"Could not read the header row: {e}")
    if not any(f.strip() for f in header_fields):
        raise IngestError("The first row (the header) is blank. The first row must contain column names.")
    if len(header_fields) > MAX_COLUMNS:
        raise IngestError(f"The file has {len(header_fields)} columns; the limit is {MAX_COLUMNS}.")

    warnings: list = []
    names = _header_names(header_fields, warnings)
    ncols = len(names)

    text_lines = text.split("\n")   # only used to show a preview of a bad line
    records, rejected, rows_read, errors = [], [], 0, 0
    prev_end = reader.line_num       # last line used by the header
    while True:
        start = prev_end + 1         # first line of the record we are about to read
        try:
            fields = next(reader)
        except StopIteration:
            break
        except csv.Error as e:
            # An unclosed quote makes the reader swallow the lines after it. We report the whole
            # span so those lines are accounted for instead of vanishing.
            errors += 1
            rows_read += 1
            end = prev_end = reader.line_num
            span = f" Lines {start}-{end} could not be separated into rows." if end > start else ""
            preview = text_lines[start - 1][:200] if start - 1 < len(text_lines) else ""
            rejected.append({"line": start, "reason": f"Malformed CSV: {e}.{span}", "preview": preview})
            if errors > MAX_MALFORMED_LINES:
                raise IngestError("The file has too many malformed lines to be a usable CSV.")
            continue
        rows_read += 1
        prev_end = reader.line_num
        line = start                 # report the FIRST line of the record (quoted fields can span lines)
        if not fields or not any(f.strip() for f in fields):
            rejected.append(_rejection(line, "Blank row (no values)", fields))
        elif len(fields) != ncols:
            rejected.append(_rejection(line, f"Expected {ncols} fields but found {len(fields)}", fields))
        else:
            records.append((line, fields))
            if len(records) > max_rows:
                raise IngestError(f"The file has more than {max_rows:,} data rows, which is the limit.", 413)

    if not records:
        raise IngestError("No readable data rows were found in the file.")

    columns, typed_cols = [], []
    for i, name in enumerate(names):
        raw_vals = [clean(fields[i]) for _, fields in records]
        ctype, dayfirst, col_warnings = infer_column(name, raw_vals)
        warnings.extend(col_warnings)

        typed, invalid_count, samples = [], 0, []
        for (line, _), rv in zip(records, raw_vals):
            value, reason = convert(rv, ctype, dayfirst)
            typed.append(value)
            if reason:
                invalid_count += 1
                if len(samples) < MAX_INVALID_SAMPLES:
                    samples.append({"line": line, "value": rv[:100], "reason": reason})

        present = [v for v in typed if v is not None]
        col = {
            "name": name,
            "type": ctype,
            "missing": sum(v is None for v in raw_vals),   # blank / NA / null etc.
            "invalid": invalid_count,                      # present but unreadable as the column's type
            "invalid_samples": samples,
            "distinct": len(set(present)),
        }
        if ctype in ("number", "date") and present:
            col["min"], col["max"] = min(present), max(present)
        if ctype == "category":
            col["categories"] = sorted(set(present))
        columns.append(col)
        typed_cols.append(typed)

    rows = [(line, [col[r] for col in typed_cols]) for r, (line, _) in enumerate(records)]
    profile = {
        "delimiter": delimiter,
        "rows_read": rows_read,
        "row_count": len(records),
        "rejected_count": len(rejected),
        "rejected": rejected[:MAX_REJECTED_SHOWN],
        "columns": columns,
        "warnings": warnings,
    }
    return profile, rows
