"""The owner's endpoints: reports, and the share links for a report."""
import json

from fastapi import APIRouter, Depends, HTTPException

from . import engine, repo, service
from .deps import current_user, get_conn
from .schemas import ReportCreate, ReportUpdate, ShareCreate
from .security import hash_token, new_token
from .suggest import suggest

router = APIRouter(prefix="/api/reports", tags=["reports"])

NOT_FOUND = "Report not found."


def _own_report(conn, user, report_id):
    row = repo.get_report(conn, user["id"], report_id)
    if row is None:
        raise HTTPException(404, NOT_FOUND)  # same answer for "not yours" and "doesn't exist"
    return row


@router.post("", status_code=201)
def create_report(body: ReportCreate, user=Depends(current_user), conn=Depends(get_conn)):
    report_id = repo.insert_report(conn, user["id"], body.dataset_id, body.title)
    if report_id is None:
        raise HTTPException(404, "Dataset not found.")
    if body.use_suggestions:
        profile = json.loads(repo.get_dataset(conn, user["id"], body.dataset_id)["profile_json"])
        blocks = [s["block"] for s in suggest(profile["columns"], profile["row_count"])]
        table = repo.load_table(conn, user["id"], body.dataset_id)
        try:   # suggestions go through the same strict check as hand-made blocks
            engine.compute_report(table, blocks, {}, strict=True)
            repo.update_report(conn, user["id"], report_id, body.title, blocks, {})
        except ValueError:
            pass   # never fail the request: the user just gets an empty report
    return service.owner_view(conn, repo.get_report(conn, user["id"], report_id))


@router.get("")
def list_reports(user=Depends(current_user), conn=Depends(get_conn)):
    return [dict(r) for r in repo.list_reports(conn, user["id"])]


@router.get("/{report_id}")
def get_report(report_id: int, user=Depends(current_user), conn=Depends(get_conn)):
    return service.owner_view(conn, _own_report(conn, user, report_id))


@router.put("/{report_id}")
def update_report(report_id: int, body: ReportUpdate, user=Depends(current_user), conn=Depends(get_conn)):
    row = _own_report(conn, user, report_id)
    table = repo.load_table(conn, user["id"], row["dataset_id"])
    blocks = [b.model_dump(mode="json") for b in body.blocks]
    filters = body.filters.model_dump(mode="json", exclude_none=True)
    try:   # strict: refuse to save a report that refers to missing columns or wrong column types
        engine.compute_report(table, blocks, filters, strict=True)
    except ValueError as e:
        raise HTTPException(422, str(e))
    repo.update_report(conn, user["id"], report_id, body.title.strip(), blocks, filters)
    return service.owner_view(conn, repo.get_report(conn, user["id"], report_id))


@router.delete("/{report_id}", status_code=204)
def delete_report(report_id: int, user=Depends(current_user), conn=Depends(get_conn)):
    if not repo.delete_report(conn, user["id"], report_id):
        raise HTTPException(404, NOT_FOUND)


# ---------------------------------------------------------------- share links

def _share_json(s, at):
    status = "revoked" if s["revoked_at"] else "expired" if s["expires_at"] <= at else "active"
    return {"id": s["id"], "token_hint": s["token_hint"], "created_at": s["created_at"],
            "expires_at": s["expires_at"], "revoked_at": s["revoked_at"], "status": status}


@router.post("/{report_id}/shares", status_code=201)
def create_share(report_id: int, body: ShareCreate, user=Depends(current_user), conn=Depends(get_conn)):
    _own_report(conn, user, report_id)
    token = new_token()
    expires_at = repo.now() + body.expires_in_hours * 3600
    share_id = repo.create_share(conn, user["id"], report_id, hash_token(token), token[-4:], expires_at)
    # The token is returned ONCE, here. Only its hash is stored, so it cannot be shown again.
    return {"id": share_id, "path": f"/s/{token}", "expires_at": expires_at}


@router.get("/{report_id}/shares")
def list_shares(report_id: int, user=Depends(current_user), conn=Depends(get_conn)):
    _own_report(conn, user, report_id)
    at = repo.now()
    return [_share_json(s, at) for s in repo.list_shares(conn, user["id"], report_id)]


@router.delete("/{report_id}/shares/{share_id}", status_code=204)
def revoke_share(report_id: int, share_id: int, user=Depends(current_user), conn=Depends(get_conn)):
    _own_report(conn, user, report_id)
    if not repo.revoke_share(conn, user["id"], report_id, share_id):
        raise HTTPException(404, "Link not found or already revoked.")