-- =============================================================
--  Music Streaming App — Full Database Schema
--  Run with: psql -U musicuser -d musicdb -f schema.sql
-- =============================================================
GRANT ALL ON SCHEMA public TO musicuser;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO musicuser;

-- -------------------------------------------------------------
--  1. users
--     Already exists from Phase 4.
--     Added created_at — safe to run, ALTER is skipped if column
--     exists (just re-run the CREATE TABLE, psql will error-skip).
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id            SERIAL      PRIMARY KEY,
    username      TEXT        UNIQUE NOT NULL,
    password_hash TEXT        NOT NULL,
    created_at    TIMESTAMP   DEFAULT NOW()
);


-- -------------------------------------------------------------
--  2. artists
--     Pure name registry. Songs and albums point here.
--     ON DELETE SET NULL on those foreign keys means deleting
--     an artist does NOT delete their songs — just orphans them.
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS artists (
    id   SERIAL PRIMARY KEY,
    name TEXT   UNIQUE NOT NULL
);


-- -------------------------------------------------------------
--  3. albums
--     Belongs to one artist (nullable — some songs have no album).
--     release_year is optional metadata.
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS albums (
    id           SERIAL  PRIMARY KEY,
    title        TEXT    NOT NULL,
    artist_id    INTEGER REFERENCES artists(id) ON DELETE SET NULL,
    release_year INTEGER
);


-- -------------------------------------------------------------
--  4. genres
--     Tag list: "rock", "jazz", "hiphop" etc.
--     Songs link to genres via song_genres join table.
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS genres (
    id   SERIAL PRIMARY KEY,
    name TEXT   UNIQUE NOT NULL
);


-- -------------------------------------------------------------
--  5. songs
--     One row per .mp3 file the server knows about.
--     filename is UNIQUE — used as the upsert key on startup scan.
--     artist_id / album_id are nullable (SET NULL on delete).
--     duration_seconds and file_size_bytes filled by server scan.
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS songs (
    id                SERIAL  PRIMARY KEY,
    filename          TEXT    UNIQUE NOT NULL,
    title             TEXT    NOT NULL,
    artist_id         INTEGER REFERENCES artists(id) ON DELETE SET NULL,
    album_id          INTEGER REFERENCES albums(id)  ON DELETE SET NULL,
    duration_seconds  INTEGER,
    file_size_bytes   INTEGER
);


-- -------------------------------------------------------------
--  6. song_genres  (many-to-many: songs <-> genres)
--     A song can have multiple genres.
--     A genre can tag multiple songs.
--     CASCADE: deleting a song or genre cleans up its rows here.
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS song_genres (
    song_id  INTEGER REFERENCES songs(id)  ON DELETE CASCADE,
    genre_id INTEGER REFERENCES genres(id) ON DELETE CASCADE,
    PRIMARY KEY (song_id, genre_id)
);


-- -------------------------------------------------------------
--  7. playlists
--     Belongs to one user (CASCADE: delete user → delete playlists).
--     UNIQUE (user_id, name) — same user can't have two playlists
--     with the same name, but two users can both have "favorites".
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS playlists (
    id         SERIAL    PRIMARY KEY,
    user_id    INTEGER   REFERENCES users(id) ON DELETE CASCADE,
    name       TEXT      NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (user_id, name)
);


-- -------------------------------------------------------------
--  8. playlist_songs  (many-to-many: playlists <-> songs)
--     position controls playback order within a playlist.
--     CASCADE: deleting a playlist or song cleans up rows here.
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS playlist_songs (
    playlist_id INTEGER REFERENCES playlists(id) ON DELETE CASCADE,
    song_id     INTEGER REFERENCES songs(id)     ON DELETE CASCADE,
    position    INTEGER NOT NULL,
    PRIMARY KEY (playlist_id, song_id)
);


-- =============================================================
--  Seed some genres so they're ready to use
-- =============================================================
INSERT INTO genres (name) VALUES
    ('pop'), ('rock'), ('hiphop'), ('jazz'),
    ('classical'), ('electronic'), ('metal'), ('rnb')
ON CONFLICT (name) DO NOTHING;

-- =============================================================
--  Active bans
-- =============================================================
CREATE TABLE IF NOT EXISTS active_bans (
    id         SERIAL    PRIMARY KEY,
    ip         TEXT      NOT NULL,
    reason     TEXT,
    banned_at  TIMESTAMP DEFAULT NOW(),
    expires_at TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_active_bans_ip ON active_bans(ip);
