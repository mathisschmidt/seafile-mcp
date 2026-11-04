# Seafile MCP Server

MCP (Model Context Protocol) server for [Seafile](https://www.seafile.com/) cloud storage. Access your self-hosted files from AI assistants like Claude, OpenCode, and other MCP clients.

## Features

- List, read, and write files in your Seafile libraries
- Create and manage directories
- Move, copy, and rename files
- Search across libraries
- Supports both account-based and library-specific authentication

## Installation

### Using pip

```bash
pip install seafile-mcp
```

### From source

```bash
git clone https://github.com/5p00kyy/seafile-mcp.git
cd seafile-mcp
pip install -e .
```

### Using Docker Compose (HTTP + OAuth, for Claude custom connectors)

The compose file runs the server over Streamable HTTP on `127.0.0.1:8000` (set
`MCP_PORT` in `.env` to use another port), with
a built-in OAuth 2.1 server (dynamic client registration + PKCE), which is what
Claude's custom connectors expect.

```bash
cp .env.example .env   # fill in Seafile credentials, MCP_PUBLIC_URL and MCP_AUTH_PASSWORD
docker compose up -d --build
```

Claude connects from Anthropic's cloud, so the server must be reachable from the
internet over **HTTPS**. Put a reverse proxy (Caddy, Traefik, nginx) or a tunnel
(Cloudflare Tunnel, Tailscale Funnel) in front of that port, and set
`MCP_PUBLIC_URL` to that public URL (for example `https://mcp.example.com`).
The whole host must be proxied, not just `/mcp`: the OAuth endpoints live at
`/.well-known/*`, `/register`, `/authorize`, `/token` and `/oauth/login`.

Then in Claude go to **Settings → Connectors → Add custom connector**, enter
`https://mcp.example.com/mcp` and click **Connect**. A sign-in page opens; enter
`MCP_AUTH_PASSWORD` to allow access. Tokens are refreshed automatically and are
kept in the `oauth-data` volume, so restarts don't disconnect Claude.

> **Security:** the server holds your Seafile credentials, so anyone who knows
> `MCP_AUTH_PASSWORD` can use them. Pick a long random password, and prefer a
> `SEAFILE_REPO_TOKEN` scoped to one library over your account password.
> To revoke every connection, stop the container, delete the `oauth-data`
> volume and start it again.

To run it over stdio instead (Claude Desktop, OpenCode…), run the image
directly: `docker run -i --rm --env-file .env seafile-mcp`.

## Configuration

Create a `.env` file or set environment variables:

### Required

- `SEAFILE_SERVER_URL`: Your Seafile server URL

### Authentication (choose one)

**Option 1: Account Authentication** (access all libraries)

- `SEAFILE_USERNAME`: Your email
- `SEAFILE_PASSWORD`: Your password

**Option 2: Library Token** (single library, more secure)

- `SEAFILE_REPO_TOKEN`: API token from library settings
- `SEAFILE_REPO_ID`: Library UUID

### Optional

- `SEAFILE_MAX_READ_SIZE`: Max file size to read (default: 1MB)
- `SEAFILE_MAX_WRITE_SIZE`: Max upload size (default: 10MB)
- `SEAFILE_TIMEOUT`: Request timeout in seconds (default: 30)
- `MCP_TRANSPORT`: `stdio` (default), `streamable-http` or `sse`
- `MCP_HOST` / `MCP_PORT`: HTTP bind address (default: `0.0.0.0:8000`)
- `MCP_PATH`: HTTP endpoint path (default: `/mcp`)
- `MCP_AUTH`: `oauth` (default in HTTP mode) or `none`
- `MCP_PUBLIC_URL`: public HTTPS URL of the server, required with OAuth
- `MCP_AUTH_PASSWORD`: sign-in password for OAuth (min 12 characters)
- `MCP_OAUTH_STATE_FILE`: file that keeps OAuth clients/tokens across restarts
- `MCP_ACCESS_TOKEN_TTL` / `MCP_REFRESH_TOKEN_TTL`: token lifetimes in seconds (default: 1 h / 30 days)

## Usage with OpenCode

Add to your OpenCode MCP configuration:

```json
{
  "mcpServers": {
    "seafile": {
      "command": "python",
      "args": ["-m", "seafile_mcp"],
      "env": {
        "SEAFILE_SERVER_URL": "https://your-seafile.com",
        "SEAFILE_USERNAME": "user@example.com",
        "SEAFILE_PASSWORD": "your-password"
      }
    }
  }
}
```

Or with library token:

```json
{
  "mcpServers": {
    "seafile": {
      "command": "seafile-mcp",
      "env": {
        "SEAFILE_SERVER_URL": "https://your-seafile.com",
        "SEAFILE_REPO_TOKEN": "your-api-token",
        "SEAFILE_REPO_ID": "library-uuid"
      }
    }
  }
}
```

## Available Tools

| Tool | Description |
|------|-------------|
| `seafile_list_libraries` | List all accessible libraries |
| `seafile_get_library_info` | Get library details |
| `seafile_list_directory` | List directory contents |
| `seafile_read_file` | Read file content |
| `seafile_write_file` | Write text to a file |
| `seafile_upload_file` | Upload binary file (base64) |
| `seafile_create_directory` | Create a folder |
| `seafile_delete` | Delete file or folder |
| `seafile_move` | Move file or folder |
| `seafile_copy` | Copy file or folder |
| `seafile_rename` | Rename file or folder |
| `seafile_get_file_info` | Get file metadata |
| `seafile_get_download_link` | Get download URL |
| `seafile_search` | Search files by name |

## File Handling

- **Text files**: Content returned directly (up to MAX_READ_SIZE)
- **Binary files**: Returns metadata and download URL
- **Large files**: Returns download URL instead of content

## Security Notes

- Use library tokens for production (limits access to single library)
- Never commit `.env` files with credentials
- API tokens can be revoked from Seafile web interface

## License

MIT
