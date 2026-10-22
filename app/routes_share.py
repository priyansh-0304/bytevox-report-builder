"""The public, no-sign-in endpoint behind a share link."""
from fastapi import APIRouter, Depends, HTTPException, Request

from . import repo, service
from .deps import get_conn
from .security import hash_token

router = APIRouter(prefix="/api/shared", tags=["shared"])

# Expired, revoked and never-existed links all get this exact same answer.
GONE = "This link is invalid, has expired, or was revoked by its owner."
TOO_MANY = "Too many requests. Please wait a few minutes and try again."


@router.get("/{token}")
def view_shared(token: str, request: Request, conn=Depends(get_conn)):
    # Two brakes per client address (see main.py): overall requests, and failed guesses.
    # The token is 256 random bits so guessing is hopeless anyway; this also stops scraping and load.
    ip = request.client.host if request.client else "unknown"
    state = request.app.state
    if state.share_fail_limiter.blocked(ip) or not state.share_limiter.allow(ip):
        raise HTTPException(429, TOO_MANY)
    report = None if len(token) > 100 else repo.get_shared_report(conn, hash_token(token), repo.now())
    if report is None:
        state.share_fail_limiter.record(ip)
        raise HTTPException(404, GONE)
    return service.shared_view(conn, report)