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

### Using Docker Compose (HTTP, for Claude custom connectors)

The compose file runs the server over Streamable HTTP on `127.0.0.1:8000`.

```bash
cp .env.example .env          # fill in your Seafile credentials
echo "MCP_PATH=/mcp/$(openssl rand -hex 24)" >> .env
docker compose up -d --build
```

Claude connects from Anthropic's cloud, so the endpoint must be reachable from
the internet over **HTTPS**. Put a reverse proxy (Caddy, Traefik, nginx) or a
tunnel (Cloudflare Tunnel, Tailscale Funnel) in front of port 8000, then in
Claude go to **Settings → Connectors → Add custom connector** and enter:

```
https://your-domain.example/mcp/<your-random-MCP_PATH>
```

> **Security:** custom connectors only support OAuth or no auth. This server
> doesn't implement OAuth, so the random `MCP_PATH` is the only thing between
> the internet and your Seafile account. Keep it secret, and prefer a
> `SEAFILE_REPO_TOKEN` scoped to one library over your account password.

To run it over stdio instead (Claude Desktop, OpenCode…), set
`MCP_TRANSPORT=stdio` or run the image directly: `docker run -i --rm --env-file .env seafile-mcp`.

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
