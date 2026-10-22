"""FastAPI dependencies: a DB connection per request, and the signed-in user."""
from fastapi import Depends, HTTPException, Request

from . import repo
from .db import connect
from .security import hash_token


def get_conn(request: Request):
    conn = connect(request.app.state.settings.db_path)
    try:
        yield conn
    finally:
        conn.close()


def current_user(request: Request, conn=Depends(get_conn)):
    token = request.cookies.get("sid")
    if token:
        user = repo.get_session_user(conn, hash_token(token), repo.now())
        if user:
            return {"id": user["id"], "email": user["email"]}
    raise HTTPException(401, "Please sign in.")
