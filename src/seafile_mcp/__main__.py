"""Entry point for running the Seafile MCP server."""

from __future__ import annotations

import os
import sys

from dotenv import load_dotenv

TRANSPORTS = ("stdio", "streamable-http", "sse")


def _enable_oauth(mcp, path: str) -> None:
    """Turn on the built-in OAuth authorization server (used by Claude custom connectors)."""
    from mcp.server.auth.provider import ProviderTokenVerifier
    from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions

    from seafile_mcp.auth import LOGIN_PATH, SCOPE, SeafileOAuthProvider

    public_url = os.getenv("MCP_PUBLIC_URL", "").strip().rstrip("/")
    if not public_url:
        raise ValueError(
            "MCP_PUBLIC_URL is required with MCP_AUTH_PASSWORD: the public HTTPS URL of "
            "this server (e.g. https://mcp.example.com), without the /mcp path"
        )
    password = os.getenv("MCP_AUTH_PASSWORD", "")

    provider = SeafileOAuthProvider(
        issuer_url=public_url,
        password=password,
        state_file=os.getenv("MCP_OAUTH_STATE_FILE") or None,
        access_token_ttl=int(os.getenv("MCP_ACCESS_TOKEN_TTL", "3600")),
        refresh_token_ttl=int(os.getenv("MCP_REFRESH_TOKEN_TTL", str(30 * 24 * 3600))),
    )
    mcp.settings.auth = AuthSettings(
        issuer_url=public_url,
        resource_server_url=public_url + path,
        validate_token_resource=False,
        required_scopes=[SCOPE],
        client_registration_options=ClientRegistrationOptions(
            enabled=True, valid_scopes=[SCOPE], default_scopes=[SCOPE]
        ),
        revocation_options=RevocationOptions(enabled=True),
    )
    # The server object is created at import time, so attach the provider afterwards.
    mcp._auth_server_provider = provider
    mcp._token_verifier = ProviderTokenVerifier(provider)
    mcp.custom_route(LOGIN_PATH, methods=["GET", "POST"])(provider.login_page)
    print(f"OAuth enabled, issuer {public_url}", file=sys.stderr)


def main() -> None:
    """Run the Seafile MCP server."""
    # Load environment variables from .env file
    load_dotenv()

    try:
        # Import here to ensure .env is loaded first
        from seafile_mcp.server import mcp

        transport = os.getenv("MCP_TRANSPORT", "streamable-http").strip().lower()
        if transport not in TRANSPORTS:
            raise ValueError(
                f"MCP_TRANSPORT must be one of {', '.join(TRANSPORTS)} (got {transport!r})"
            )

        if transport != "stdio":
            from mcp.server.transport_security import TransportSecuritySettings

            mcp.settings.host = os.getenv("MCP_HOST", "0.0.0.0")
            mcp.settings.port = int(os.getenv("MCP_PORT", "8000"))
            path = "/" + os.getenv("MCP_PATH", "/mcp").strip("/")
            mcp.settings.streamable_http_path = path
            mcp.settings.sse_path = path
            # The server is meant to sit behind a reverse proxy / tunnel with a
            # public hostname, so the localhost-only Host check is disabled.
            mcp.settings.transport_security = TransportSecuritySettings(
                enable_dns_rebinding_protection=False
            )
            # OAuth is on as soon as a sign-in password is set. A public URL without
            # a password is refused, so an exposed server is never left open.
            if os.getenv("MCP_AUTH_PASSWORD"):
                _enable_oauth(mcp, path)
            elif os.getenv("MCP_PUBLIC_URL", "").strip():
                raise ValueError(
                    "MCP_AUTH_PASSWORD is required when MCP_PUBLIC_URL is set "
                    "(the server is reachable from the internet)"
                )
            else:
                print(
                    "WARNING: no MCP_AUTH_PASSWORD, authentication is off. Anyone who can "
                    "reach this port can use your Seafile account.",
                    file=sys.stderr,
                )

            print(
                f"Seafile MCP listening on http://{mcp.settings.host}:{mcp.settings.port}"
                f"{path} ({transport})",
                file=sys.stderr,
            )

        mcp.run(transport=transport)
    except ValueError as e:
        # Configuration errors (missing credentials, invalid values)
        print(f"Configuration error: {e}", file=sys.stderr)
        sys.exit(1)
    except ImportError as e:
        # Missing dependencies
        print(f"Import error: {e}", file=sys.stderr)
        print("Please ensure all dependencies are installed: pip install -e .", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        # Graceful shutdown on Ctrl+C
        pass
    except Exception as e:
        # Unexpected errors
        print(f"Failed to start Seafile MCP server: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
