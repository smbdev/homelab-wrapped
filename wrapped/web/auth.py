"""Single-admin authentication with zero new dependencies.

The admin record lives in ``auth.json`` next to config.yaml: username, a
stdlib-``scrypt`` password hash, and an HMAC secret. Sessions are stateless
signed cookies (``user|expiry|signature``) — changing the password rotates
the secret, which invalidates every outstanding session at once.

``auth: proxy`` in config.yaml skips all of this and trusts the
``X-Auth-User`` header from a reverse proxy (Authelia, Authentik, …).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import time
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

COOKIE = "wrapped_session"
SESSION_SECONDS = 30 * 24 * 3600
_USERNAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_OPEN_PATHS = ("/login", "/setup")
_OPEN_PREFIXES = ("/static/", "/favicon")
# ponytail: scrypt n=2^14 r=8 (~16MB, <100ms) — bump n if hardware allows
_SCRYPT = {"n": 2**14, "r": 8, "p": 1}


def _hash(password: str, salt: bytes) -> str:
    return hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT).hex()


class AuthStore:
    """The ``auth.json`` admin record and session-token signing."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def _load(self) -> dict | None:
        try:
            return json.loads(self.path.read_text())
        except (OSError, json.JSONDecodeError):
            return None

    def exists(self) -> bool:
        return self._load() is not None

    def username(self) -> str | None:
        rec = self._load()
        return rec["username"] if rec else None

    def create(self, username: str, password: str) -> None:
        salt = secrets.token_bytes(16)
        rec = {
            "username": username,
            "salt": salt.hex(),
            "hash": _hash(password, salt),
            "secret": secrets.token_hex(32),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(rec))
        self.path.chmod(0o600)

    def verify(self, username: str, password: str) -> bool:
        rec = self._load()
        if rec is None or not hmac.compare_digest(rec["username"], username):
            return False
        return hmac.compare_digest(rec["hash"], _hash(password, bytes.fromhex(rec["salt"])))

    def change(self, username: str | None, password: str | None) -> None:
        """Update username and/or password; a new password rotates the secret."""
        rec = self._load()
        if rec is None:
            raise ValueError("no admin account exists")
        if username:
            rec["username"] = username
        if password:
            salt = secrets.token_bytes(16)
            rec["salt"] = salt.hex()
            rec["hash"] = _hash(password, salt)
            rec["secret"] = secrets.token_hex(32)  # sign out every other session
        self.path.write_text(json.dumps(rec))
        self.path.chmod(0o600)

    # ---- session tokens ----

    def _sig(self, payload: str, secret: str) -> str:
        return hmac.new(bytes.fromhex(secret), payload.encode(), hashlib.sha256).hexdigest()

    def issue(self) -> str:
        rec = self._load()
        payload = f"{rec['username']}|{int(time.time()) + SESSION_SECONDS}"
        return f"{payload}|{self._sig(payload, rec['secret'])}"

    def user_from(self, token: str | None) -> str | None:
        rec = self._load()
        if not token or rec is None:
            return None
        user, sep, rest = token.partition("|")
        exp, sep2, sig = rest.partition("|")
        if not (sep and sep2):
            return None
        if not hmac.compare_digest(sig, self._sig(f"{user}|{exp}", rec["secret"])):
            return None
        if user != rec["username"] or not exp.isdigit() or int(exp) < time.time():
            return None
        return user


async def _form(request: Request) -> dict[str, str]:
    body = (await request.body()).decode()
    return {k: v[0].strip() for k, v in parse_qs(body, keep_blank_values=True).items()}


def _signed_in(response: Response, store: AuthStore) -> Response:
    response.set_cookie(
        COOKIE, store.issue(), max_age=SESSION_SECONDS, httponly=True, samesite="lax"
    )
    return response


def add_auth(app: FastAPI, templates, auth_path: Path, mode: str) -> None:
    """Register the auth middleware and routes on ``app``.

    Args:
        app: The application to guard.
        templates: The shared Jinja environment.
        auth_path: Where the admin record lives (``auth.json``).
        mode: ``"local"`` (built-in accounts) or ``"proxy"`` (trust
            ``X-Auth-User`` from the reverse proxy).
    """
    store = AuthStore(auth_path)
    app.state.auth_mode = mode

    def current_user(request: Request) -> str | None:
        if mode == "proxy":
            return request.headers.get("X-Auth-User")
        return store.user_from(request.cookies.get(COOKIE))

    @app.middleware("http")
    async def guard(request: Request, call_next):
        path = request.url.path
        if path in _OPEN_PATHS or path.startswith(_OPEN_PREFIXES):
            return await call_next(request)
        user = current_user(request)
        if user is None:
            if mode == "proxy":
                return Response("X-Auth-User header missing — check proxy config", 401)
            if path.startswith("/api/"):
                return JSONResponse({"error": "not signed in"}, status_code=401)
            return RedirectResponse("/login" if store.exists() else "/setup", status_code=303)
        request.state.user = user
        return await call_next(request)

    @app.get("/setup", response_class=HTMLResponse)
    def setup_page(request: Request):
        if mode == "proxy" or store.exists():
            return RedirectResponse("/", status_code=303)
        return templates.TemplateResponse(request, "setup.html", {})

    @app.post("/setup")
    async def setup(request: Request):
        if mode == "proxy" or store.exists():
            return RedirectResponse("/", status_code=303)
        form = await _form(request)
        username, password = form.get("username", ""), form.get("password", "")
        error = None
        if not _USERNAME.match(username):
            error = "Username: letters, digits, - or _ only."
        elif len(password) < 8:
            error = "Password needs at least 8 characters."
        elif password != form.get("confirm", ""):
            error = "Passwords don't match."
        if error:
            return templates.TemplateResponse(
                request, "setup.html", {"error": error, "username": username}, status_code=400
            )
        store.create(username, password)
        return _signed_in(RedirectResponse("/", status_code=303), store)

    @app.get("/login", response_class=HTMLResponse)
    def login_page(request: Request):
        if mode == "proxy":
            return RedirectResponse("/", status_code=303)
        if not store.exists():
            return RedirectResponse("/setup", status_code=303)
        return templates.TemplateResponse(request, "login.html", {})

    @app.post("/login")
    async def login(request: Request):
        if mode == "proxy":
            return RedirectResponse("/", status_code=303)
        form = await _form(request)
        if not store.verify(form.get("username", ""), form.get("password", "")):
            return templates.TemplateResponse(
                request,
                "login.html",
                {"error": "Wrong username or password.", "username": form.get("username", "")},
                status_code=401,
            )
        return _signed_in(RedirectResponse("/", status_code=303), store)

    @app.post("/logout")
    def logout():
        response = RedirectResponse("/login", status_code=303)
        response.delete_cookie(COOKIE)
        return response

    @app.post("/account")
    async def account(request: Request):
        if mode == "proxy":
            return RedirectResponse("/settings?err=Account+is+managed+by+your+reverse+proxy.", 303)
        form = await _form(request)
        if not store.verify(store.username() or "", form.get("current_password", "")):
            return RedirectResponse("/settings?err=Current+password+is+wrong.", status_code=303)
        username = form.get("new_username", "")
        password = form.get("new_password", "")
        if username and not _USERNAME.match(username):
            return RedirectResponse("/settings?err=Invalid+new+username.", status_code=303)
        if password:
            if len(password) < 8:
                return RedirectResponse(
                    "/settings?err=New+password+needs+8%2B+characters.", status_code=303
                )
            if password != form.get("confirm", ""):
                return RedirectResponse("/settings?err=Passwords+don%27t+match.", status_code=303)
        if not (username or password):
            return RedirectResponse("/settings?err=Nothing+to+change.", status_code=303)
        store.change(username or None, password or None)
        return _signed_in(
            RedirectResponse("/settings?msg=Account+updated.", status_code=303), store
        )
