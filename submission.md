# Mixtape Bug Hunt Submission

## Milestone 1: Codebase Map

### Application structure

- `app.py` creates and configures the Flask application, initializes the shared
  SQLAlchemy object, registers the four route blueprints, and creates the
  database tables inside the application context.
- `models.py` defines eight SQLAlchemy models:
  - `User` stores account data, the current listening streak, the last-listened
    timestamp, and relationships to songs, ratings, listening events,
    notifications, playlists, and friends.
  - `Song` stores music metadata and who shared it. It relates to ratings,
    listening events, and tags.
  - `Tag` supplies reusable labels for songs.
  - `ListeningEvent` records which user listened to which song and when.
  - `Rating` stores a user's 1–5 score for a song. A database constraint allows
    only one rating per user/song pair.
  - `Playlist` stores playlist metadata and relates to its ordered songs.
  - `Notification` stores a recipient, notification type, message, timestamp,
    and read state.
  - The module also defines the `friendships`, `song_tags`, and
    `playlist_entries` association tables. `playlist_entries` carries extra
    information—position, adding user, and timestamp—so playlist membership is
    ordered and records who added each song.
- `routes/songs.py` exposes song search/detail endpoints plus the rate and
  listen actions. It validates HTTP input, delegates work to search,
  notification, or streak services, and converts results/errors to JSON.
- `routes/playlists.py` exposes playlist creation, metadata, ordered-song
  retrieval, and add-song endpoints. It delegates retrieval/creation to the
  playlist service and the add-song workflow to the notification service.
- `routes/users.py` exposes user profiles, streaks, notification lists, and the
  mark-as-read action. Profile lookup is done directly through the database;
  the other operations delegate to services.
- `routes/feed.py` exposes "Friends Listening Now" and the broader activity
  feed, delegating both queries to the feed service.
- `services/streak_service.py` creates listening events and updates or reads a
  user's consecutive-day listening streak.
- `services/feed_service.py` queries friends' listening events. The
  listening-now function applies a recency cutoff and returns each friend's
  newest event, while the activity feed returns the newest events up to a
  limit.
- `services/search_service.py` searches song titles and artists
  case-insensitively and retrieves individual song details.
- `services/notification_service.py` creates/retrieves notifications, marks
  them read, saves song ratings, and coordinates the add-to-playlist workflow.
- `services/playlist_service.py` creates playlists and retrieves playlist
  metadata, a user's playlists, or the songs ordered by their
  `playlist_entries.position`.
- `seed_data.py` rebuilds the local database with five connected users,
  thirteen tagged/untagged songs, recent and older listening events, three
  ordered playlists, streak state, and a sample playlist notification.
- `tests/` contains focused service tests for streak boundaries, search result
  uniqueness, and complete/ordered playlist retrieval. Each test module uses a
  fresh in-memory SQLite database.

### Data flow: recording a song listen

1. A client sends `POST /songs/<song_id>/listen` with a JSON `user_id`.
2. `routes/songs.py` checks that `user_id` is present and calls
   `streak_service.record_listening_event(user_id, song_id)`.
3. The service loads the `User`, creates a `ListeningEvent` using the current
   UTC time, and adds the event to the database session.
4. The service passes the same user and timestamp to
   `update_listening_streak()`. That function compares the current calendar
   date with `User.last_listened_at`, then starts, preserves, increments, or
   resets `User.listening_streak` according to the elapsed days.
5. `record_listening_event()` commits the event and user changes together and
   returns the event.
6. The route serializes the event through `ListeningEvent.to_dict()` and
   returns JSON with HTTP 201. A `ValueError` from the service becomes an HTTP
   400 response.
7. The stored event can later be read through `routes/feed.py`, whose feed
   service queries friends' `ListeningEvent` rows and joins them back to
   `User` and `Song` objects for the response.

### Organization patterns noticed

- Blueprints divide endpoints by feature, while service modules hold most
  business rules and database workflows.
- Routes mainly parse input and format JSON; model `to_dict()` methods provide
  the shared serialization format.
- Services signal expected failures with `ValueError`, and routes translate
  those failures into feature-appropriate HTTP status codes.
- UUID strings are primary keys throughout the model layer.
- Many-to-many relationships use explicit association tables. Playlist
  membership is richer than a basic relationship because its association row
  also defines ordering and attribution.
- Timestamps are created in UTC. Service code includes a compatibility step
  for older or SQLite-loaded timestamps that do not contain timezone
  information.
- Multi-step writes generally use one SQLAlchemy session, although some helper
  functions commit their own changes.

### Setup and orientation checkpoint

- Working branch: `bugfix/mixtape`
- Environment: project-local Windows `.venv`, Python 3.12.13
- Seed command: completed successfully
- Flask app-factory launch: confirmed HTTP 200 at `http://127.0.0.1:5000`
- Baseline tests: 10 passed and 3 failed before any fixes
- Five reported issues reviewed:
  1. Listening streak resets unexpectedly (`streak_service.py`)
  2. Listening Now includes stale activity (`feed_service.py`)
  3. Search may show duplicate songs (`search_service.py`)
  4. Ratings do not notify the song sharer (`notification_service.py`)
  5. The final playlist song is omitted (`playlist_service.py`)

### Initial bug plan

The first three issues I plan to reproduce and investigate are #1, #2, and #5.
Issues #1 and #5 already have focused boundary tests that fail in the baseline
suite. Issue #2 can be reproduced with the seeded listening events because the
data includes both recent activity and events from earlier in the day that
should not appear in "Friends Listening Now." I am not selecting Issue #3
initially because its supplied duplicate-search regression test passes in this
environment, so its reported behavior is not yet reproducible.

## Milestone 2: Bug Reproduction

### Issue #1: My listening streak keeps resetting

**How I reproduced it:** I activated the project virtual environment in WSL
and ran the focused test
`python -m pytest tests/test_streaks.py::test_streak_increments_on_sunday -q`.
The test creates a user who listens on Saturday and again on Sunday. A
consecutive-day listen should increase the streak from 1 to 2, but the test
failed because the actual streak remained 1. This deliberately reproduced the
reported Sunday-only reset before I changed any service code.

**How I found the root cause:** I traced the request from
`POST /songs/<song_id>/listen` in `routes/songs.py` to
`record_listening_event()` and then `update_listening_streak()` in
`services/streak_service.py`. I compared the function's documented
consecutive-day rules with each branch that uses `days_since_last`. The focused
test established that the one-day difference was correct, which isolated the
additional weekday condition as the deciding factor. AI helped me trace this
call chain and check the meaning of Python's `weekday()` result; I verified the
conclusion against the service code and the controlled Saturday/Sunday test.

**The root cause:** `datetime.date.weekday()` returns `6` for Sunday. The
consecutive-day branch required both `days_since_last == 1` and
`today.weekday() != 6`, so it explicitly rejected every Sunday. When a user
listened on Saturday and again on Sunday, the elapsed-day value correctly
equaled one, but the weekday check was false. Execution therefore entered the
fallback branch and reset the streak to 1 even though the user had not skipped
a day.

**My fix and side-effect check:** I removed the unrelated weekday restriction
so every `days_since_last == 1` case increments the streak. I then ran all five
tests in `tests/test_streaks.py`; they passed for a new listener, an ordinary
weekday transition, repeated listens on one day, a skipped day, and the
Saturday-to-Sunday boundary. I also ran the full test suite. It produced 11
passes and only the two previously reproduced Issue #5 playlist failures, so
the streak fix introduced no additional test failures.

### Issue #2: Friends Listening Now shows people from yesterday

**How I reproduced it:** I reseeded the database, opened `flask shell`, and
created a controlled listening event for Aaliya dated 23 hours before the
current UTC time. Aaliya is one of Kenji's friends, so I then called
`get_friends_listening_now(kenji.id)` and printed each returned friend's
username and listening timestamp. The result included Aaliya with the
timestamp `2026-07-04T22:56:47.241286` even though the check was performed on
July 5. This confirmed that activity from the previous day was incorrectly
included in "Friends Listening Now" before I changed any service code.

**How I found the root cause:** I traced
`GET /feed/<user_id>/listening-now` from `routes/feed.py` to
`get_friends_listening_now()` in `services/feed_service.py`. Inside that
function, I followed the value of `RECENT_THRESHOLD` into the calculated
`cutoff`, then into the database filter on `ListeningEvent.listened_at`. The
controlled 23-hour-old event satisfied that filter, which confirmed that the
cutoff itself—not friendship lookup, ordering, or friend deduplication—was the
specific cause. AI helped me trace the request and design controlled events on
both sides of the cutoff; I verified the conclusion through Flask shell and
the returned timestamps.

**The root cause:** `RECENT_THRESHOLD` was defined as 24 hours, so the query
accepted every friend event whose timestamp was at least
`datetime.now(timezone.utc) - timedelta(hours=24)`. That range is an activity
history window rather than a "listening now" window and can include events from
the previous calendar day. The seed data identifies events within 30 minutes
as recent and events beginning at two hours old as stale, leaving a one-hour
boundary between the two groups.

**My fix and side-effect check:** I changed `RECENT_THRESHOLD` from 24 hours to
1 hour without changing the activity-feed query, ordering, or per-friend
deduplication. I then created two controlled events for Kenji's friends: Nova
at 30 minutes old and Aaliya at 23 hours old. The service returned Nova and
excluded Aaliya, confirming both sides of the new cutoff. The full test suite
produced 11 passes and only the two previously reproduced Issue #5 playlist
failures, so the feed change introduced no additional test failures.

### Issue #5: The last song in a playlist never shows up

**How I reproduced it:** After restoring the seed data, I ran the focused test
`python -m pytest tests/test_playlists.py::test_playlist_returns_all_songs -q
-p no:cacheprovider`. The test fixture creates a playlist containing five
songs and then retrieves its ordered song list. The assertion failed because
the service returned only four songs, with `Track 4` as the final returned
entry. This confirmed that the fifth and final song was omitted before I
changed any service code.

**How I found the root cause:** I traced
`GET /playlists/<playlist_id>/songs` from `routes/playlists.py` to
`get_playlist_songs()` in `services/playlist_service.py`. The database query
joined songs to `playlist_entries`, filtered by playlist ID, ordered the rows
by position, and returned the complete result with `.all()`. The data was
therefore complete until the return statement applied `songs[:-1]`. AI helped
me interpret the negative slice syntax, and I verified that this was the exact
cause by comparing the five-song fixture with the four serialized results.

**The root cause:** In Python, `songs[:-1]` creates a slice from the start of
the list up to—but not including—the element at index `-1`, which is the final
element. The query retrieved every playlist song in the correct order, but the
serialization loop deliberately iterated over that shortened slice. As a
result, every nonempty playlist response omitted exactly its last song.

**My fix and side-effect check:** I changed the return expression to iterate
over `songs` directly, preserving every row returned by the ordered query. All
three playlist tests then passed: a five-song playlist returned all five,
their position order remained correct, and an empty playlist still returned an
empty list. I also ran the complete test suite, which passed all 13 tests.
