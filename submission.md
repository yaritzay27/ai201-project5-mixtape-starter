# Mixtape Bug Hunt Submission

## AI Usage

**Instance 1: Codebase orientation**

- *What I gave the AI:* I gave Codex the project brief, README, models, routes,
  services, seed script, and tests. I asked it to summarize what the main files
  were responsible for and trace a real feature from its route through the
  service and database models.
- *What it produced:* Codex helped organize the codebase map and traced the
  song-listen flow from `POST /songs/<song_id>/listen` through
  `record_listening_event()` and `update_listening_streak()`, then into the
  feed queries that later read the saved event.
- *What I changed or verified:* I read the files in the README's recommended
  order and checked every part of the trace against the actual function calls
  before accepting it. I also did not assume every reported bug would reproduce:
  the Issue #3 duplicate-search test passed in my environment, so I selected
  the reproducible feed issue for my required three fixes. When I returned to
  Issue #3 as a stretch fix, I inspected the raw joined rows and documented
  that my SQLAlchemy version masked the duplicates at the service boundary.

**Instance 2: Checking the streak and feed corrections**

- *What I gave the AI:* I shared the failing Sunday test, the streak condition,
  the feed threshold, and the terminal output from my reproduction steps. I
  asked Codex to explain the relevant date logic, check whether the proposed
  one-line corrections matched the reported behavior, and suggest side-effect
  checks.
- *What it produced:* Codex explained that `weekday()` returns `6` on Sunday
  and that the existing condition excluded Sunday even when the last listen was
  exactly one day earlier. It also explained how the 24-hour
  `RECENT_THRESHOLD` allowed previous-day activity into "Listening Now" and
  suggested controlled events on both sides of a one-hour cutoff.
- *What I changed or verified:* I accepted the minimal streak correction only
  after the focused tests passed and a live API check changed Darius's Sunday
  streak from 3 to 4 instead of resetting it. For the feed fix, I changed the
  threshold myself and used Flask shell to confirm that a 30-minute-old event
  appeared while a 23-hour-old event did not. I then ran the full suite to make
  sure neither correction introduced new failures.

**Instance 3: Explaining and checking the playlist fix**

- *What I gave the AI:* I showed Codex the failing five-song playlist test and
  asked whether `songs[:-1]` on the return line explained why only four songs
  were returned.
- *What it produced:* Codex explained Python's negative slice syntax: `[:-1]`
  starts at the beginning but stops before the final list element. It confirmed
  that the query itself returned the complete ordered list and that the slice
  removed the last song during serialization.
- *What I changed or verified:* I changed the return expression to iterate over
  `songs` directly. I verified the correction with all three playlist tests,
  including order preservation and the empty-playlist case, and then ran the
  full suite successfully. Codex also helped organize the RCA wording, which I
  checked against the code, reproduction output, and test results before using
  it.

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
- Environment: project-local WSL `.venv`, Python 3.12.3
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

## Milestones 2 and 3: Bug Reproduction and Root Cause Analysis

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

### Issue #3: The same song keeps showing up twice in search

**How I reproduced it:** I reseeded the database and searched for `Crown
Heights` in Flask shell. The matching song has three tags. In my installed
SQLAlchemy version, `search_songs()` returned one serialized song because an
entity-only `Query` de-duplicated rows with the same primary key. I then ran
the same outer join while projecting the song ID, title, and tag ID. That raw
query returned three rows with the same song ID and three different tag IDs.
This reproduced the underlying duplicate-row condition while also showing
that SQLAlchemy 2.0 masked the reported duplicate API output in my environment.

**How I found the root cause:** I traced `GET /songs/search` from
`routes/songs.py` to `search_songs()` in `services/search_service.py`, then
followed its query into the `song_tags` association table in `models.py` and
the multi-tag fixture in `seed_data.py`. Searching title and artist with `OR`
does not duplicate a row; the important step was the outer join. Seeing the
same song ID three times in the raw result, with only `tag_id` changing, made
me confident that join multiplicity was the cause. AI helped distinguish SQL
rows from ORM entity results, and I verified the explanation using both query
forms and the focused regression test.

**The root cause:** `search_songs()` outer-joined `Song` to `song_tags` without
requesting distinct songs. A song contributes one joined row for each matching
association-table row, so a song with three tags produces three SQL rows.
Single-tag and untagged songs do not expose the same multiplicity. The legacy
entity-query behavior in my SQLAlchemy version collapsed identical `Song`
primary keys before serialization, but the SQL query itself did not guarantee
unique songs and other result-handling paths can expose those duplicates.

**My fix and side-effect check:** I added `.distinct()` before `.all()` so the
database query explicitly returns unique `Song` rows instead of relying on ORM
identity de-duplication. I ran all five search tests, covering ordinary title
or artist matches, untagged songs, single-tag songs, multi-tag songs, and empty
results; all five passed, and the multi-tag result still contained all three
tag names. I then ran the complete suite and all 13 tests passed.

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
