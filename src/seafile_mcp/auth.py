"""Built-in OAuth 2.1 authorization server for HTTP mode.

The MCP SDK provides the OAuth endpoints (metadata discovery, dynamic client
registration, /authorize, /token, /revoke). This module supplies the provider
behind them: a single-owner login page protected by ``MCP_AUTH_PASSWORD`` and
token storage, optionally persisted to a JSON file so clients stay connected
across restarts.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import html
import json
import logging
import os
import secrets
import time
from pathlib import Path
from typing import Any

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    RefreshToken,
    TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import BaseModel
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response

logger = logging.getLogger(__name__)

SCOPE = "seafile"
LOGIN_PATH = "/oauth/login"

AUTH_CODE_TTL = 5 * 60
LOGIN_REQUEST_TTL = 10 * 60
MAX_LOGIN_ATTEMPTS = 5
MIN_PASSWORD_LENGTH = 12


def _hash(token: str) -> str:
    """Tokens are stored hashed so a leaked state file can't be replayed."""
    return hashlib.sha256(token.encode()).hexdigest()


class _LoginRequest(BaseModel):
    client_id: str
    client_name: str
    params: AuthorizationParams
    expires_at: float
    attempts: int = 0


class SeafileOAuthProvider:
    """Single-owner OAuth provider: whoever knows the password can authorize clients."""

    def __init__(
        self,
        issuer_url: str,
        password: str,
        state_file: str | None = None,
        access_token_ttl: int = 3600,
        refresh_token_ttl: int = 30 * 24 * 3600,
    ) -> None:
        if len(password) < MIN_PASSWORD_LENGTH:
            raise ValueError(f"MCP_AUTH_PASSWORD must be at least {MIN_PASSWORD_LENGTH} characters")
        self.issuer_url = issuer_url.rstrip("/")
        self._password = password
        self._state_file = Path(state_file) if state_file else None
        self.access_token_ttl = access_token_ttl
        self.refresh_token_ttl = refresh_token_ttl

        self._clients: dict[str, OAuthClientInformationFull] = {}
        # Keyed by token hash; the model's ``token`` field also holds the hash.
        self._access_tokens: dict[str, AccessToken] = {}
        self._refresh_tokens: dict[str, RefreshToken] = {}
        # Short-lived, kept in memory only.
        self._auth_codes: dict[str, AuthorizationCode] = {}
        self._login_requests: dict[str, _LoginRequest] = {}

        self._load()

    # ------------------------------------------------------------------ storage

    def _load(self) -> None:
        if not self._state_file or not self._state_file.exists():
            return
        try:
            data = json.loads(self._state_file.read_text())
            self._clients = {
                k: OAuthClientInformationFull.model_validate(v)
                for k, v in data.get("clients", {}).items()
            }
            self._access_tokens = {
                k: AccessToken.model_validate(v) for k, v in data.get("access_tokens", {}).items()
            }
            self._refresh_tokens = {
                k: RefreshToken.model_validate(v) for k, v in data.get("refresh_tokens", {}).items()
            }
        except Exception as e:  # corrupt file: start fresh rather than refuse to boot
            logger.warning("Could not load OAuth state from %s: %s", self._state_file, e)
        self._purge_expired()

    def _save(self) -> None:
        if not self._state_file:
            return
        self._purge_expired()
        data: dict[str, Any] = {
            "clients": {k: v.model_dump(mode="json") for k, v in self._clients.items()},
            "access_tokens": {k: v.model_dump(mode="json") for k, v in self._access_tokens.items()},
            "refresh_tokens": {
                k: v.model_dump(mode="json") for k, v in self._refresh_tokens.items()
            },
        }
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._state_file.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
        os.replace(tmp, self._state_file)

    def _purge_expired(self) -> None:
        now = time.time()
        for store in (self._access_tokens, self._refresh_tokens):
            for k in [k for k, t in store.items() if t.expires_at and t.expires_at < now]:
                del store[k]
        for k in [k for k, c in self._auth_codes.items() if c.expires_at < now]:
            del self._auth_codes[k]
        for k in [k for k, r in self._login_requests.items() if r.expires_at < now]:
            del self._login_requests[k]

    # ------------------------------------------------------------------ clients

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        return self._clients.get(client_id)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        self._clients[client_info.client_id] = client_info
        self._save()
        logger.info(
            "Registered OAuth client %s (%s)", client_info.client_id, client_info.client_name
        )

    # ------------------------------------------------------------ authorization

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        self._purge_expired()
        request_id = secrets.token_urlsafe(32)
        self._login_requests[request_id] = _LoginRequest(
            client_id=client.client_id,
            client_name=client.client_name or client.client_id,
            params=params,
            expires_at=time.time() + LOGIN_REQUEST_TTL,
        )
        return f"{self.issuer_url}{LOGIN_PATH}?req={request_id}"

    async def login_page(self, request: Request) -> Response:
        """GET shows the password form, POST checks it and redirects back to the client."""
        if request.method == "GET":
            request_id = request.query_params.get("req", "")
        else:
            form = await request.form()
            request_id = str(form.get("req", ""))

        self._purge_expired()
        login = self._login_requests.get(request_id)
        if login is None:
            return _page("This sign-in link has expired. Start the connection again.", status=400)

        if request.method == "GET":
            return _login_form(request_id, login.client_name)

        password = str(form.get("password", ""))
        if not hmac.compare_digest(password.encode(), self._password.encode()):
            login.attempts += 1
            await asyncio.sleep(1)  # slow down guessing
            if login.attempts >= MAX_LOGIN_ATTEMPTS:
                del self._login_requests[request_id]
                logger.warning("Too many failed sign-in attempts for client %s", login.client_id)
                return _page("Too many failed attempts. Start the connection again.", status=403)
            return _login_form(request_id, login.client_name, error="Wrong password.")

        del self._login_requests[request_id]
        params = login.params
        code = secrets.token_urlsafe(32)
        self._auth_codes[code] = AuthorizationCode(
            code=code,
            scopes=params.scopes or [SCOPE],
            expires_at=time.time() + AUTH_CODE_TTL,
            client_id=login.client_id,
            code_challenge=params.code_challenge,
            redirect_uri=params.redirect_uri,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            resource=params.resource,
        )
        logger.info("Authorized OAuth client %s", login.client_id)
        return RedirectResponse(
            construct_redirect_uri(str(params.redirect_uri), code=code, state=params.state),
            status_code=302,
        )

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        code = self._auth_codes.get(authorization_code)
        if code and code.client_id == client.client_id:
            return code
        return None

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        if self._auth_codes.pop(authorization_code.code, None) is None:
            raise TokenError("invalid_grant", "authorization code already used")
        return self._issue_tokens(
            client.client_id, authorization_code.scopes, authorization_code.resource
        )

    # ------------------------------------------------------------------- tokens

    def _issue_tokens(self, client_id: str, scopes: list[str], resource: str | None) -> OAuthToken:
        now = int(time.time())
        access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        self._access_tokens[_hash(access)] = AccessToken(
            token=_hash(access),
            client_id=client_id,
            scopes=scopes,
            expires_at=now + self.access_token_ttl,
            resource=resource,
        )
        self._refresh_tokens[_hash(refresh)] = RefreshToken(
            token=_hash(refresh),
            client_id=client_id,
            scopes=scopes,
            expires_at=now + self.refresh_token_ttl,
            resource=resource,
        )
        self._save()
        return OAuthToken(
            access_token=access,
            token_type="Bearer",
            expires_in=self.access_token_ttl,
            refresh_token=refresh,
            scope=" ".join(scopes),
        )

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        token = self._refresh_tokens.get(_hash(refresh_token))
        if token is None or token.client_id != client.client_id:
            return None
        if token.expires_at and token.expires_at < time.time():
            return None
        return token

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        # Rotate: the old refresh token can't be used again.
        if self._refresh_tokens.pop(refresh_token.token, None) is None:
            raise TokenError("invalid_grant", "refresh token already used")
        return self._issue_tokens(
            client.client_id, scopes or refresh_token.scopes, refresh_token.resource
        )

    async def load_access_token(self, token: str) -> AccessToken | None:
        access = self._access_tokens.get(_hash(token))
        if access is None:
            return None
        if access.expires_at and access.expires_at < time.time():
            del self._access_tokens[access.token]
            return None
        return access

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        self._access_tokens.pop(token.token, None)
        self._refresh_tokens.pop(token.token, None)
        self._save()


# ---------------------------------------------------------------------- pages

_STYLE = """
body{font-family:system-ui,sans-serif;background:#f4f5f7;color:#1f2328;display:flex;
min-height:100vh;align-items:center;justify-content:center;margin:0;padding:16px}
main{background:#fff;border-radius:12px;box-shadow:0 2px 12px rgba(0,0,0,.08);
padding:32px;width:100%;max-width:360px;box-sizing:border-box}
h1{font-size:20px;margin:0 0 8px}p{color:#57606a;font-size:14px;line-height:1.5}
input{width:100%;box-sizing:border-box;padding:10px 12px;font-size:15px;border:1px solid #d0d7de;
border-radius:8px;margin:8px 0 16px}button{width:100%;padding:10px;font-size:15px;border:0;
border-radius:8px;background:#e8730c;color:#fff;cursor:pointer}.err{color:#cf222e}
"""


def _page(body: str, status: int = 200) -> HTMLResponse:
    return HTMLResponse(
        f"<!doctype html><html><head><meta charset='utf-8'>"
        f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>Seafile MCP sign-in</title><style>{_STYLE}</style></head>"
        f"<body><main>{body}</main></body></html>",
        status_code=status,
        headers={"X-Frame-Options": "DENY", "Cache-Control": "no-store"},
    )


def _login_form(request_id: str, client_name: str, error: str | None = None) -> HTMLResponse:
    err = f"<p class='err'>{html.escape(error)}</p>" if error else ""
    return _page(
        "<h1>Connect to Seafile</h1>"
        f"<p><strong>{html.escape(client_name)}</strong> wants access to your Seafile files. "
        "Enter the server password to allow it.</p>"
        f"{err}<form method='post' action='{LOGIN_PATH}'>"
        f"<input type='hidden' name='req' value='{html.escape(request_id)}'>"
        "<input type='password' name='password' placeholder='Password' autofocus required>"
        "<button type='submit'>Allow access</button></form>",
        status=401 if error else 200,
    )
