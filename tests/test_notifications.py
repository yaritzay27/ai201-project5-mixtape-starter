"""Tests for Mixtape notification behavior."""

import pytest

from app import create_app, db
from models import Notification, Song, User
from services.notification_service import rate_song


@pytest.fixture
def app():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


@pytest.fixture
def rating_data(app):
    with app.app_context():
        sharer = User(username="sharer", email="sharer@example.com")
        rater = User(username="friend", email="friend@example.com")
        db.session.add_all([sharer, rater])
        db.session.flush()

        song = Song(
            title="Shared Track",
            artist="Test Artist",
            shared_by=sharer.id,
        )
        db.session.add(song)
        db.session.commit()

        yield {
            "sharer_id": sharer.id,
            "rater_id": rater.id,
            "song_id": song.id,
        }


def test_rating_notifies_song_sharer(app, rating_data):
    """Rating another user's song should notify the original sharer."""
    with app.app_context():
        rating = rate_song(rating_data["rater_id"], rating_data["song_id"], 4)

        notifications = db.session.query(Notification).filter_by(
            user_id=rating_data["sharer_id"]
        ).all()

        assert rating.score == 4
        assert len(notifications) == 1
        notification = notifications[0]
        assert notification.notification_type == "song_rated"
        assert notification.body == "friend rated your song 'Shared Track' 4/5."


def test_self_rating_does_not_notify_song_sharer(app, rating_data):
    """A user should not be notified when rating their own shared song."""
    with app.app_context():
        rate_song(rating_data["sharer_id"], rating_data["song_id"], 5)

        notifications = db.session.query(Notification).filter_by(
            user_id=rating_data["sharer_id"]
        ).all()

        assert notifications == []
