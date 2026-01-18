# Architecture Refactor (January 2026)

## Overview

Refactored from organic growth to clean, pattern-based architecture with clear separation of concerns.

**Motto:** "Just enough, consistent, empowers not prohibits"

## Design Patterns Used

| Pattern | Where | Purpose |
|---------|-------|---------|
| **Adapter** | `adapters/` | Wrap external APIs (Viki, Trakt, Metadata) with clean interfaces |
| **Repository** | `repository.py` | Single data access layer - all DB operations go through here |
| **Command/Orchestrator** | `workflows/` | Coordinate multi-step operations (fetch → match → sync) |
| **Query Objects** | `queries/` | Read-only operations for viewing state |

## Components

### Models (`models.py`)
Peewee ORM models stored in `sync.db`:
- **Show**: Viki show with match fields (trakt_id, slug, title, source, confidence)
- **Episode**: Episode with watch progress tracking
- **Match**: Audit table for match history
- **SyncLog**: Operational audit log

### Repository (`repository.py`)
Single source of truth for all data operations:
- `upsert_show()` - Create/update shows
- `upsert_episode()` - Create/update episodes with progress calculation
- `save_match()` - Save match and update show
- `get_unmatched_shows()` - Query helper
- `mark_episodes_synced()` - Bulk update
- Smart hashing: `compute_billboard_hash()`, `needs_refresh()`

### Adapters (`adapters/`)

**VikiAdapter** - Wraps VikiClient
- `get_billboard()` - Fetch watchlist
- `get_episodes()` - Fetch full episode list
- `get_watch_progress()` - Fetch progress data
- Returns clean dataclasses: `VikiBillboardItem`, `VikiEpisode`

**TraktAdapter** - Wraps TraktClient
- `search()` - Search by title
- `get_show()` - Get by slug
- `sync_watched()` - Sync episodes to Trakt
- Returns clean dataclasses: `TraktShow`, `TraktSearchResult`

**MetadataAdapter** - TVDB/MDL lookups
- `search_tvdb()` - Search TVDB
- `get_tvdb_show()` - Get show details
- Useful for matching when Trakt search fails

### Workflows (`workflows/`)

**SyncWorkflow** - Main orchestrator
```
1. Fetch billboard from Viki
2. Check billboard hash (change detection)
3. For changed shows: fetch episodes
4. Update watch progress
5. Match unmatched shows
6. Sync to Trakt
```

Options:
- `force_refresh=True` - Refresh all shows
- `dry_run=True` - Preview, don't sync
- Progress callbacks for UI updates

### Queries (`queries/`)

**WatchQuery** - View watch status
- `all_shows()` - List with progress
- `show_detail()` - Full episode breakdown
- `in_progress()` - Only partial watches
- `pending_sync()` - Unsynced episodes

**StatusQuery** - System health
- `get_stats()` - Match rate, sync rate, etc.
- `get_issues()` - Warnings/errors
- `health_check()` - Overall status

**MatchQuery** - Match management
- `get_match()` - Show match info
- `list_unmatched()` - All unmatched
- `set_manual_match()` - User override
- `clear_match()` - Undo match

## CLI Commands

### New/Refactored

```bash
# Refresh local cache (for testing)
python -m viki_trakt_sync refresh [--force]

# View watch status
python -m viki_trakt_sync watch [SHOW_ID] [--in-progress] [--pending]

# Check system health
python -m viki_trakt_sync status [--json]

# Main workflow: fetch → match → sync
python -m viki_trakt_sync sync [--force-refresh] [--dry-run]

# Manage matches
python -m viki_trakt_sync match show <id>
python -m viki_trakt_sync match list [--matched]
python -m viki_trakt_sync match set <viki_id> <trakt_id>
python -m viki_trakt_sync match clear <id>
```

### Legacy
- Old `match` commands moved to `_match_legacy` (hidden)
- `cache`, `dataset`, `watchdb`, `trakt`, `viki` groups still available

## Data Flow

```
┌──────────────────────────────────────────┐
│            CLI Commands                  │
│  sync | refresh | watch | status | match │
└──────────────┬───────────────────────────┘
               │
┌──────────────▼───────────────────────────┐
│  Workflows (SyncWorkflow)                 │
│  Queries (WatchQuery, etc)                │
└──────────────┬───────────────────────────┘
               │
┌──────────────▼───────────────────────────┐
│         Adapters                          │
│  VikiAdapter | TraktAdapter | MetadataA   │
└──────────────┬───────────────────────────┘
               │
┌──────────────▼───────────────────────────┐
│         Repository                        │
│  Single data access layer                 │
└──────────────┬───────────────────────────┘
               │
┌──────────────▼───────────────────────────┐
│          Models (Peewee)                  │
│  sync.db: Show | Episode | Match | SyncLog
└──────────────────────────────────────────┘
```

## Testing

**Smoke Tests** (`tests/test_smoke.py`) - 14 tests, all passing
- Repository tests: CRUD, filtering, hashing
- Adapter tests: with mocked clients
- Workflow tests: fetch, refresh operations
- Query tests: viewing and filtering data

Run: `pytest tests/test_smoke.py -v`

## Configuration

Via `config.py` + TOML:
- Viki credentials: session cookie, API token
- Trakt credentials: client ID, secret, access token
- File: `~/.config/viki-trakt-sync/settings.toml`

## Smart Sync Features

1. **Billboard Hash Change Detection**
   - Hash = MD5(last_video_id + last_watched_at)
   - Only fetches episodes if hash changed
   - Saves API calls during repeated syncs

2. **Match Source Tracking**
   - AUTO: Matched by algorithm
   - MANUAL: User override
   - NONE: No match found
   - Stored for audit trail

3. **Progress Calculation**
   - Watched if: progress ≥ credits marker OR progress ≥ 90% duration
   - Stored as both raw seconds and percentage
   - Enables smart syncing

## Future Improvements

- [ ] Parallel episode fetching
- [ ] Incremental sync (only changed episodes)
- [ ] Conflict resolution for manual matches
- [ ] CLI option to force-match specific shows
- [ ] Bookmark (Watch Later) sync support
- [ ] Season/episode mapping for multi-season shows
