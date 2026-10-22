"""Upload a CSV, list your datasets, read one dataset's profile."""
import json
import os

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from . import repo
from .deps import current_user, get_conn
from .ingest import IngestError, ingest_csv
from .suggest import suggest

router = APIRouter(prefix="/api/datasets", tags=["datasets"])


def _too_large(limit: int) -> HTTPException:
    size = f"{limit // (1024 * 1024)} MB" if limit >= 1024 * 1024 else f"{limit // 1024} KB"
    return HTTPException(413, f"The file is too large. The limit is {size}. "
                              "Remove columns or rows you do not need and try again.")


def _read_limited(upload: UploadFile, limit: int) -> bytes:
    """Read the upload in chunks and stop as soon as it passes the size limit."""
    data = bytearray()
    while chunk := upload.file.read(64 * 1024):
        data += chunk
        if len(data) > limit:
            raise _too_large(limit)
    return bytes(data)


# A plain `def` (not async): FastAPI runs it in a worker thread, so parsing a big file
# does not freeze the server for other users.
@router.post("", status_code=201)
def upload_dataset(request: Request, file: UploadFile = File(...), name: str = Form(""),
                   user=Depends(current_user), conn=Depends(get_conn)):
    settings = request.app.state.settings
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > settings.max_upload_bytes + 64 * 1024:
        raise _too_large(settings.max_upload_bytes)  # reject before reading the body when we can

    filename = os.path.basename(file.filename or "")[:200]
    if not filename.lower().endswith(".csv"):
        raise HTTPException(415, "Only .csv files are supported. Export your spreadsheet as CSV and try again.")

    raw = _read_limited(file, settings.max_upload_bytes)
    if not raw.strip():
        raise HTTPException(422, "The file is empty.")
    try:
        profile, rows = ingest_csv(raw, settings.max_rows)
    except IngestError as e:
        raise HTTPException(e.status, e.message)

    display_name = name.strip()[:100] or os.path.splitext(filename)[0][:100] or "Untitled dataset"
    dataset_id = repo.insert_dataset(conn, user["id"], display_name, filename, profile, rows)
    return {"id": dataset_id, "name": display_name, "row_count": profile["row_count"],
            "rejected_count": profile["rejected_count"]}


@router.get("")
def list_datasets(user=Depends(current_user), conn=Depends(get_conn)):
    out = []
    for d in repo.list_datasets(conn, user["id"]):
        profile = json.loads(d["profile_json"])
        out.append({"id": d["id"], "name": d["name"], "original_filename": d["original_filename"],
                    "row_count": d["row_count"], "rejected_count": profile["rejected_count"],
                    "created_at": d["created_at"]})
    return out


@router.get("/{dataset_id}")
def get_dataset(dataset_id: int, user=Depends(current_user), conn=Depends(get_conn)):
    d = repo.get_dataset(conn, user["id"], dataset_id)
    if d is None:
        raise HTTPException(404, "Dataset not found.")
    profile = json.loads(d["profile_json"])
    return {"id": d["id"], "name": d["name"], "original_filename": d["original_filename"],
            "created_at": d["created_at"], "profile": profile,
            "report_count": repo.count_reports(conn, user["id"], dataset_id),
            "suggestions": suggest(profile["columns"], profile["row_count"]),
            "preview": {"columns": [c["name"] for c in profile["columns"]],
                        "rows": repo.preview_rows(conn, user["id"], dataset_id)}}


@router.delete("/{dataset_id}", status_code=204)
def delete_dataset(dataset_id: int, user=Depends(current_user), conn=Depends(get_conn)):
    if not repo.delete_dataset(conn, user["id"], dataset_id):
        raise HTTPException(404, "Dataset not found.")