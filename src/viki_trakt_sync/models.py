"""Peewee ORM models for watch state."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from peewee import (
    Model,
    SqliteDatabase,
    CharField,
    IntegerField,
    TextField,
    BooleanField,
    FloatField,
    AutoField,
    fn,
)


def _db_path() -> Path:
    p = Path.home() / ".config" / "viki-trakt-sync" / "watch_state.db"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


database = SqliteDatabase(str(_db_path()))


class BaseModel(Model):
    class Meta:
        database = database


class Show(BaseModel):
    viki_container_id = CharField(primary_key=True)
    title = CharField(null=True)
    type = CharField(null=True)
    origin_country = CharField(null=True)
    origin_language = CharField(null=True)
    trakt_id = IntegerField(null=True)
    trakt_slug = CharField(null=True)
    trakt_title = CharField(null=True)
    is_completed = BooleanField(default=False)
    first_seen = CharField(null=True)
    last_seen = CharField(null=True)
    last_updated = CharField(null=True)


class Episode(BaseModel):
    viki_video_id = CharField(primary_key=True)
    viki_container_id = CharField(index=True)
    episode_number = IntegerField(null=True)
    duration = IntegerField(null=True)
    watched_seconds = IntegerField(null=True)
    credits_marker = IntegerField(null=True)
    progress_percent = FloatField(null=True)
    is_watched = IntegerField(null=True)  # use 0/1/NULL
    last_watched_at = CharField(null=True)
    source = CharField(null=True)
    updated_at = CharField(null=True)


class Scan(BaseModel):
    id = AutoField()
    scanned_at = CharField()
    source = CharField()
    items = IntegerField()


class Snapshot(BaseModel):
    id = AutoField()
    created_at = CharField()
    source = CharField()
    payload = TextField()  # JSON text


def init_models() -> None:
    database.connect(reuse_if_open=True)
    database.execute_sql("PRAGMA journal_mode=WAL;")
    database.create_tables([Show, Episode, Scan, Snapshot], safe=True)

