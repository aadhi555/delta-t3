-- Music streaming app db schema

GRANT ALL ON SCHEMA public TO musicuser;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO musicuser;

-- -------------------------------------------------------------
--  1. users

CREATE TABLE IF NOT EXISTS users (
    id            SERIAL      PRIMARY KEY,
    username      TEXT        UNIQUE NOT NULL,
    password_hash TEXT        NOT NULL,
    created_at    TIMESTAMP   DEFAULT NOW()
);


-- -------------------------------------------------------------
--  2. artists

CREATE TABLE IF NOT EXISTS artists (
    id   SERIAL PRIMARY KEY,
    name TEXT   UNIQUE NOT NULL
);


-- -------------------------------------------------------------
--  3. albums

CREATE TABLE IF NOT EXISTS albums (
    id           SERIAL  PRIMARY KEY,
    title        TEXT    NOT NULL,
    artist_id    INTEGER REFERENCES artists(id) ON DELETE SET NULL,
    release_year INTEGER
);


-- -------------------------------------------------------------
--  4. genres

CREATE TABLE IF NOT EXISTS genres (
    id   SERIAL PRIMARY KEY,
    name TEXT   UNIQUE NOT NULL
);


-- -------------------------------------------------------------
--  5. songs

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

CREATE TABLE IF NOT EXISTS song_genres (
    song_id  INTEGER REFERENCES songs(id)  ON DELETE CASCADE,
    genre_id INTEGER REFERENCES genres(id) ON DELETE CASCADE,
    PRIMARY KEY (song_id, genre_id)
);


-- -------------------------------------------------------------
--  7. playlists

CREATE TABLE IF NOT EXISTS playlists (
    id         SERIAL    PRIMARY KEY,
    user_id    INTEGER   REFERENCES users(id) ON DELETE CASCADE,
    name       TEXT      NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (user_id, name)
);


-- -------------------------------------------------------------
--  8. playlist_songs  (many-to-many: playlists <-> songs)

CREATE TABLE IF NOT EXISTS playlist_songs (
    playlist_id INTEGER REFERENCES playlists(id) ON DELETE CASCADE,
    song_id     INTEGER REFERENCES songs(id)     ON DELETE CASCADE,
    position    INTEGER NOT NULL,
    PRIMARY KEY (playlist_id, song_id)
);


-- seeding some genres

INSERT INTO genres (name) VALUES
    ('pop'), ('rock'), ('hiphop'), ('jazz'),
    ('classical'), ('electronic'), ('metal'), ('rnb')
ON CONFLICT (name) DO NOTHING;

-- active bans table

CREATE TABLE IF NOT EXISTS active_bans (
    id         SERIAL    PRIMARY KEY,
    ip         TEXT      NOT NULL,
    reason     TEXT,
    banned_at  TIMESTAMP DEFAULT NOW(),
    expires_at TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_active_bans_ip ON active_bans(ip);
