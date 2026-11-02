"""Entry point for running the Seafile MCP server."""

from __future__ import annotations

import os
import sys

from dotenv import load_dotenv

TRANSPORTS = ("stdio", "streamable-http", "sse")


def main() -> None:
    """Run the Seafile MCP server."""
    # Load environment variables from .env file
    load_dotenv()

    try:
        # Import here to ensure .env is loaded first
        from seafile_mcp.server import mcp

        transport = os.getenv("MCP_TRANSPORT", "stdio").strip().lower()
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
