# Viki to Trakt Sync

Sync your Viki watch history to Trakt.tv

## Quick Start

### 1. Install

```bash
pip install -e .
```

### 2. Configure credentials in `.env`

Required credentials:

```env
# Viki
VIKI_SESSION=<your session cookie>
VIKI_TOKEN=<your API token>

# Trakt
TRAKT_CLIENT_ID=<your client ID>
TRAKT_CLIENT_SECRET=<your client secret>
TRAKT_ACCESS_TOKEN=<your access token>

# TVDB (for advanced matching)
TVDB_API_KEY=<your API key>
```

### Getting Credentials

**Viki credentials:**
- Log in to [viki.com](https://viki.com)
- Open DevTools (F12) → Application → Cookies → https://www.viki.com
- Copy the `session__id` value
- For API token, run: `viki-trakt viki extract-token`

**Trakt credentials:**
- Create app at [trakt.tv/oauth/applications](https://trakt.tv/oauth/applications/new)
- Copy Client ID and Client Secret
- Run: `viki-trakt viki link-trakt` (handles OAuth flow)

**TVDB credentials (optional):**
- Create account at [thetvdb.com](https://thetvdb.com)
- Generate API key from account settings

## Usage

Run with `--help` for available commands:

```bash
viki-trakt --help
viki-trakt match --help
viki-trakt cache --help
```

### Common Commands

```bash
# Initialize cache (first time)
viki-trakt cache init

# Match shows (Viki → Trakt)
viki-trakt match shows

# Sync watch history
viki-trakt sync

# Check status
viki-trakt status
```

## Configuration File

Settings can be overridden in `.env` or via environment variables. See `.env.example` for all options.

## Troubleshooting

Run with verbose output:
```bash
viki-trakt -v <command>
```

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run linter
ruff check src/

# Format code
black src/
```
