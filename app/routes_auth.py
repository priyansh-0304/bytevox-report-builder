"""Accounts: register, login, logout, who-am-I. Sessions are random tokens in an HttpOnly cookie."""
import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from . import repo
from .deps import current_user, get_conn
from .schemas import Credentials
from .security import DUMMY_HASH, hash_password, hash_token, new_token, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])

MAX_FAILS, WINDOW_SECONDS = 5, 600


def _start_session(request: Request, response: Response, conn, user_id: int):
    settings = request.app.state.settings
    token = new_token()
    max_age = settings.session_days * 86400
    repo.create_session(conn, user_id, hash_token(token), repo.now() + max_age)
    response.set_cookie("sid", token, max_age=max_age, httponly=True, samesite="lax",
                        secure=settings.cookie_secure, path="/")


@router.post("/register", status_code=201)
def register(body: Credentials, request: Request, response: Response, conn=Depends(get_conn)):
    user_id = repo.create_user(conn, body.email, hash_password(body.password))
    if user_id is None:
        raise HTTPException(409, "An account with this email already exists. Try signing in.")
    _start_session(request, response, conn, user_id)
    return {"id": user_id, "email": body.email}


@router.post("/login")
def login(body: Credentials, request: Request, response: Response, conn=Depends(get_conn)):
    # Simple brute-force brake: 5 failures per email per 10 minutes (in memory, per process).
    fails = request.app.state.login_fails
    recent = [t for t in fails.get(body.email, []) if t > time.time() - WINDOW_SECONDS]
    fails[body.email] = recent
    if len(recent) >= MAX_FAILS:
        raise HTTPException(429, "Too many failed attempts. Try again in a few minutes.")

    user = repo.get_user_by_email(conn, body.email)
    # Always run one scrypt verification so unknown emails take as long as wrong passwords.
    ok = verify_password(body.password, user["password_hash"] if user else DUMMY_HASH)
    if not (user and ok):
        fails[body.email].append(time.time())
        raise HTTPException(401, "Invalid email or password.")
    fails.pop(body.email, None)
    _start_session(request, response, conn, user["id"])
    return {"id": user["id"], "email": user["email"]}


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, conn=Depends(get_conn)):
    token = request.cookies.get("sid")
    if token:
        repo.delete_session(conn, hash_token(token))
    response.delete_cookie("sid", path="/")


@router.get("/me")
def me(user=Depends(current_user)):
    return user
