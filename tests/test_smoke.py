"""Smoke tests for the new architecture.

Tests the core components with mocked adapters to verify
the integration works without hitting external APIs.
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import Mock, MagicMock
import tempfile
import os


# ============================================================
# Repository Tests
# ============================================================

class TestRepository:
    """Test the Repository class."""
    
    @pytest.fixture
    def repo(self, tmp_path):
        """Create a repository with a temp database."""
        # Set config dir to temp path
        os.environ['XDG_CONFIG_HOME'] = str(tmp_path)
        
        from viki_trakt_sync.repository import Repository
        from viki_trakt_sync.models import database
        
        # Use temp database
        db_path = tmp_path / "viki-trakt-sync" / "sync.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        database.init(str(db_path))
        
        return Repository()
    
    def test_upsert_show(self, repo):
        """Test creating and updating a show."""
        # Create
        show = repo.upsert_show(
            viki_id="12345v",
            title="Test Show",
            type_="series",
            origin_country="KR",
        )
        
        assert show.viki_id == "12345v"
        assert show.title == "Test Show"
        
        # Update
        show2 = repo.upsert_show(
            viki_id="12345v",
            title="Updated Title",
        )
        
        assert show2.title == "Updated Title"
    
    def test_upsert_episode(self, repo):
        """Test creating and updating episodes."""
        # First create the show
        repo.upsert_show(viki_id="12345v", title="Test")
        
        # Create episode
        ep = repo.upsert_episode(
            viki_video_id="ep001",
            viki_id="12345v",
            episode_number=1,
            duration=3600,
            watched_seconds=1800,
        )
        
        assert ep.viki_video_id == "ep001"
        assert ep.progress_percent == 50.0
        assert ep.is_watched == False
        
        # Update to watched
        ep2 = repo.upsert_episode(
            viki_video_id="ep001",
            viki_id="12345v",
            watched_seconds=3600,
        )
        
        assert ep2.is_watched == True
    
    def test_save_and_get_match(self, repo):
        """Test saving and retrieving matches."""
        repo.upsert_show(viki_id="12345v", title="Test")
        
        match = repo.save_match(
            viki_id="12345v",
            trakt_id=99999,
            trakt_slug="test-show",
            trakt_title="Test Show on Trakt",
            source="AUTO",
            confidence=0.95,
            method="exact_trakt",
        )
        
        assert match.trakt_id == 99999
        
        # Verify show was updated
        show = repo.get_show("12345v")
        assert show.trakt_id == 99999
        assert show.match_source == "AUTO"
    
    def test_get_unmatched_shows(self, repo):
        """Test filtering unmatched shows."""
        repo.upsert_show(viki_id="matched1", title="Matched")
        repo.save_match(
            viki_id="matched1",
            trakt_id=111,
            trakt_slug="matched",
            trakt_title="Matched",
            source="AUTO",
        )
        
        repo.upsert_show(viki_id="unmatched1", title="Unmatched")
        
        unmatched = repo.get_unmatched_shows()
        assert len(unmatched) == 1
        assert unmatched[0].viki_id == "unmatched1"
    
    def test_get_stats(self, repo):
        """Test statistics generation."""
        repo.upsert_show(viki_id="show1", title="Show 1")
        repo.upsert_show(viki_id="show2", title="Show 2")
        repo.save_match(viki_id="show1", trakt_id=1, trakt_slug="s1", trakt_title="S1", source="AUTO")
        
        stats = repo.get_stats()
        
        assert stats['total_shows'] == 2
        assert stats['matched_shows'] == 1
        assert stats['unmatched_shows'] == 1


# ============================================================
# Adapter Tests
# ============================================================

class TestVikiAdapter:
    """Test the VikiAdapter with mocked client."""
    
    @pytest.fixture
    def mock_client(self):
        """Create a mock Viki client."""
        client = Mock()
        client.get_watchlist.return_value = {
            "response": [
                {
                    "id": "12345v",
                    "type": "series",
                    "titles": {"en": "Test Drama"},
                    "origin": {"country": "KR", "language": "ko"},
                    "last_watched": {"id": "ep001", "updated_at": "2025-01-01T00:00:00Z"},
                }
            ],
            "more": False,
        }
        client.get_episodes.return_value = {
            "response": [
                {"id": "ep001", "number": 1, "duration": 3600},
                {"id": "ep002", "number": 2, "duration": 3600},
            ],
            "more": False,
        }
        return client
    
    def test_get_billboard(self, mock_client):
        """Test fetching billboard."""
        from viki_trakt_sync.adapters import VikiAdapter
        
        adapter = VikiAdapter(mock_client)
        billboard = adapter.get_billboard()
        
        assert len(billboard) == 1
        assert billboard[0].viki_id == "12345v"
        assert billboard[0].title == "Test Drama"
        assert billboard[0].last_video_id == "ep001"
    
    def test_get_episodes(self, mock_client):
        """Test fetching episodes."""
        from viki_trakt_sync.adapters import VikiAdapter
        
        adapter = VikiAdapter(mock_client)
        episodes = adapter.get_episodes("12345v")
        
        assert len(episodes) == 2
        assert episodes[0].episode_number == 1
        assert episodes[1].episode_number == 2


class TestTraktAdapter:
    """Test the TraktAdapter with mocked client."""
    
    @pytest.fixture
    def mock_client(self):
        """Create a mock Trakt client."""
        client = Mock()
        client.search_shows.return_value = [
            {
                "show": {
                    "title": "Test Drama",
                    "year": 2025,
                    "ids": {"trakt": 12345, "slug": "test-drama", "tvdb": 999},
                },
                "score": 100.0,
            }
        ]
        client.client_id = "test_client_id"
        client.access_token = "test_token"
        return client
    
    def test_search(self, mock_client):
        """Test searching for shows."""
        from viki_trakt_sync.adapters import TraktAdapter
        
        adapter = TraktAdapter(mock_client)
        results = adapter.search("Test Drama")
        
        assert len(results) == 1
        assert results[0].show.trakt_id == 12345
        assert results[0].show.title == "Test Drama"
        assert results[0].score == 100.0


# ============================================================
# Workflow Tests
# ============================================================

class TestSyncWorkflow:
    """Test the SyncWorkflow with mocked dependencies."""
    
    @pytest.fixture
    def mock_viki(self):
        """Create a mock VikiAdapter."""
        from viki_trakt_sync.adapters.viki import VikiBillboardItem, VikiEpisode
        
        adapter = Mock()
        adapter.get_billboard.return_value = [
            VikiBillboardItem(
                viki_id="show1",
                title="Test Show",
                type="series",
                last_video_id="ep1",
                last_watched_at="2025-01-01T00:00:00Z",
            )
        ]
        adapter.get_episodes.return_value = [
            VikiEpisode(
                viki_video_id="ep1",
                viki_id="show1",
                episode_number=1,
                duration=3600,
            )
        ]
        adapter.get_watch_progress.return_value = {
            "show1": {"ep1": 3600}
        }
        # New primary method for watch-status-first architecture
        # Returns (watch_status_dict, current_timestamp)
        adapter.get_watch_status_with_metadata.return_value = (
            {
                "show1": {
                    "ep1": {
                        "watched_seconds": 3600,
                        "duration": 3600,
                        "episode_number": 1,
                        "credits_marker": None,
                    }
                }
            },
            1768474054  # current timestamp
        )
        return adapter
    
    @pytest.fixture
    def mock_trakt(self):
        """Create a mock TraktAdapter."""
        adapter = Mock()
        adapter.search.return_value = []
        adapter.sync_watched.return_value = {"added": 0, "existing": 0, "failed": 0}
        return adapter
    
    @pytest.fixture
    def repo(self, tmp_path):
        """Create a repository with temp database."""
        os.environ['XDG_CONFIG_HOME'] = str(tmp_path)
        
        from viki_trakt_sync.repository import Repository
        from viki_trakt_sync.models import database
        
        db_path = tmp_path / "viki-trakt-sync" / "sync.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        database.init(str(db_path))
        
        return Repository()
    
    def test_run_fetches_billboard(self, mock_viki, mock_trakt, repo):
        """Test that workflow fetches billboard."""
        from viki_trakt_sync.workflows import SyncWorkflow
        
        workflow = SyncWorkflow(
            viki=mock_viki,
            trakt=mock_trakt,
            repository=repo,
        )
        
        result = workflow.run(dry_run=True)
        
        assert result.shows_fetched == 1
        assert result.episodes_fetched == 1
        # New architecture uses get_watch_status_with_metadata as primary
        mock_viki.get_watch_status_with_metadata.assert_called_once()
    
    def test_run_refreshes_changed_shows(self, mock_viki, mock_trakt, repo):
        """Test that workflow refreshes shows that changed."""
        from viki_trakt_sync.workflows import SyncWorkflow
        
        workflow = SyncWorkflow(
            viki=mock_viki,
            trakt=mock_trakt,
            repository=repo,
        )
        
        result = workflow.run(dry_run=True)
        
        # First run should fetch and process shows
        assert result.shows_fetched == 1
        assert result.episodes_fetched == 1
        # New architecture uses get_watch_status_with_metadata as primary
        mock_viki.get_watch_status_with_metadata.assert_called_once()


# ============================================================
# Query Tests
# ============================================================

class TestWatchQuery:
    """Test WatchQuery."""
    
    @pytest.fixture
    def repo(self, tmp_path):
        """Create populated repository."""
        os.environ['XDG_CONFIG_HOME'] = str(tmp_path)
        
        from viki_trakt_sync.repository import Repository
        from viki_trakt_sync.models import database
        
        db_path = tmp_path / "viki-trakt-sync" / "sync.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        database.init(str(db_path))
        
        repo = Repository()
        
        # Add test data
        repo.upsert_show(viki_id="show1", title="Test Show 1")
        repo.upsert_episode(viki_video_id="ep1", viki_id="show1", episode_number=1, duration=3600, watched_seconds=3600)
        repo.upsert_episode(viki_video_id="ep2", viki_id="show1", episode_number=2, duration=3600, watched_seconds=0)
        
        return repo
    
    def test_all_shows(self, repo):
        """Test getting all shows."""
        from viki_trakt_sync.queries import WatchQuery
        
        query = WatchQuery(repo)
        shows = query.all_shows()
        
        assert len(shows) == 1
        assert shows[0].viki_id == "show1"
        assert shows[0].total_episodes == 2
        assert shows[0].watched_episodes == 1
    
    def test_show_detail(self, repo):
        """Test getting show detail."""
        from viki_trakt_sync.queries import WatchQuery
        
        query = WatchQuery(repo)
        detail = query.show_detail("show1")
        
        assert detail is not None
        assert detail['title'] == "Test Show 1"
        assert len(detail['episodes']) == 2


class TestStatusQuery:
    """Test StatusQuery."""
    
    @pytest.fixture
    def repo(self, tmp_path):
        """Create repository with test data."""
        os.environ['XDG_CONFIG_HOME'] = str(tmp_path)
        
        from viki_trakt_sync.repository import Repository
        from viki_trakt_sync.models import database
        
        db_path = tmp_path / "viki-trakt-sync" / "sync.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        database.init(str(db_path))
        
        repo = Repository()
        repo.upsert_show(viki_id="show1", title="Show 1")
        repo.upsert_show(viki_id="show2", title="Show 2")
        repo.save_match(viki_id="show1", trakt_id=1, trakt_slug="s1", trakt_title="S1", source="AUTO")
        
        return repo
    
    def test_get_stats(self, repo):
        """Test getting stats."""
        from viki_trakt_sync.queries import StatusQuery
        
        query = StatusQuery(repo)
        stats = query.get_stats()
        
        assert stats.total_shows == 2
        assert stats.matched_shows == 1
    
    def test_get_issues(self, repo):
        """Test getting issues."""
        from viki_trakt_sync.queries import StatusQuery
        
        query = StatusQuery(repo)
        issues = query.get_issues()
        
        # Should have issue about unmatched shows (or "not matched")
        assert any("match" in i.message.lower() for i in issues)


# ============================================================
# Run with: pytest tests/test_smoke.py -v
# ============================================================
