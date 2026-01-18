"""Peewee ORM models - canonical data model for Viki-Trakt Sync."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from peewee import (
    Model,
    SqliteDatabase,
    CharField,
    IntegerField,
    TextField,
    BooleanField,
    FloatField,
    AutoField,
    DateTimeField,
    ForeignKeyField,
)


def _db_path() -> Path:
    """Get database path, creating parent directories if needed."""
    p = Path.home() / ".config" / "viki-trakt-sync" / "sync.db"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


database = SqliteDatabase(str(_db_path()), pragmas={
    'journal_mode': 'wal',
    'cache_size': -64 * 1000,  # 64MB
    'foreign_keys': 1,
})


class BaseModel(Model):
    """Base model with database binding."""
    
    class Meta:
        database = database


class Show(BaseModel):
    """A Viki show (series/movie) with optional Trakt match."""
    
    viki_id = CharField(primary_key=True)
    title = CharField(null=True)
    type = CharField(null=True)  # series, movie
    origin_country = CharField(null=True)
    origin_language = CharField(null=True)
    
    # Trakt matching
    trakt_id = IntegerField(null=True, index=True)
    trakt_slug = CharField(null=True)
    trakt_title = CharField(null=True)
    match_source = CharField(null=True)  # AUTO, MANUAL, NONE
    match_confidence = FloatField(null=True)
    match_method = CharField(null=True)  # title_search, tvdb_lookup, etc.
    
    # Smart sync - billboard hash for change detection
    billboard_hash = CharField(null=True)
    
    # Timestamps
    first_seen_at = DateTimeField(null=True)
    last_fetched_at = DateTimeField(null=True)
    last_synced_at = DateTimeField(null=True)
    
    class Meta:
        table_name = 'shows'


class Episode(BaseModel):
    """An episode with watch progress and sync status."""
    
    viki_video_id = CharField(primary_key=True)
    show = ForeignKeyField(Show, backref='episodes', on_delete='CASCADE')
    episode_number = IntegerField(null=True, index=True)
    
    # Duration/progress
    duration = IntegerField(null=True)  # seconds
    watched_seconds = IntegerField(null=True)
    credits_marker = IntegerField(null=True)  # when credits start
    progress_percent = FloatField(null=True)
    is_watched = BooleanField(default=False)
    
    # Timestamps
    last_watched_at = DateTimeField(null=True)
    
    # Trakt sync tracking
    synced_to_trakt = BooleanField(default=False)
    synced_at = DateTimeField(null=True)
    
    class Meta:
        table_name = 'episodes'
        indexes = (
            (('show', 'episode_number'), False),
        )


class Match(BaseModel):
    """Cached match results for auditing and manual overrides.
    
    Separate from Show to keep match history and support NONE matches.
    """
    
    id = AutoField()
    viki_id = CharField(index=True)
    trakt_id = IntegerField(null=True)
    trakt_slug = CharField(null=True)
    trakt_title = CharField(null=True)
    
    source = CharField()  # AUTO, MANUAL, NONE
    confidence = FloatField(null=True)
    method = CharField(null=True)
    notes = TextField(null=True)
    
    created_at = DateTimeField(default=lambda: datetime.now(timezone.utc))
    
    class Meta:
        table_name = 'matches'


class SyncLog(BaseModel):
    """Log of sync operations for debugging and auditing."""
    
    id = AutoField()
    timestamp = DateTimeField(default=lambda: datetime.now(timezone.utc))
    operation = CharField()  # sync, match, refresh
    shows_processed = IntegerField(default=0)
    episodes_synced = IntegerField(default=0)
    status = CharField()  # success, partial, failed
    notes = TextField(null=True)
    
    class Meta:
        table_name = 'sync_log'


class SyncMetadata(BaseModel):
    """Metadata for sync operations (last fetch timestamps, etc.)."""
    
    key = CharField(primary_key=True)
    value = TextField()
    updated_at = DateTimeField(default=lambda: datetime.now(timezone.utc))
    
    class Meta:
        table_name = 'sync_metadata'


# All models for table creation
ALL_MODELS = [Show, Episode, Match, SyncLog, SyncMetadata]


def init_db() -> None:
    """Initialize database and create tables."""
    database.connect(reuse_if_open=True)
    database.create_tables(ALL_MODELS, safe=True)


def close_db() -> None:
    """Close database connection."""
    if not database.is_closed():
        database.close()

