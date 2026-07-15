import socket
import threading
import os
import psycopg2
import bcrypt
import time
import uuid
import datetime
import subprocess
import re

HOST = "0.0.0.0"
PORT = 9000
MUSIC_DIR = "./music"
CHUNK_SIZE = 4096
BACKUP_DIR = "./backups"
BACKUP_INTERVAL = 300
BAN_THRESHOLD = 5
BAN_DURATION = 300
TRANSCODE_DIR = "./transcoded_cache"
TRANSCODE_BITRATE = "64k"
SLOW_THRESHOLD_KBPS = 100
MAX_CONCURRENT_TRANSCODES = 2
TRANSCODE_TTL = 300
DOWNLOAD_COOLDOWN = 60
MAX_LINKS_PER_REQUEST = 5
LIBRARY_SCAN_INTERVAL = 60

DB = {
    "dbname": os.environ.get("POSTGRES_DB", "musicdb"),
    "user": os.environ.get("POSTGRES_USER", "musicuser"),
    "password": os.environ.get("POSTGRES_PASSWORD", "musicpass"),
    "host": os.environ.get("DB_HOST", "localhost"),
    "port": os.environ.get("DB_PORT", "5432"),
}

transcode_semaphore = threading.Semaphore(MAX_CONCURRENT_TRANSCODES)
transcode_cache_lock = threading.Lock()
cache_last_used = {}  # {transcoded_filename: timestamp of last access}

sessions = {}
sessions_lock = threading.Lock()

fail_counts = {}
fail_counts_lock = threading.Lock()

download_cooldowns = {}
download_cooldowns_lock = threading.Lock()

library_version = 0
library_version_lock = threading.Lock()


def get_library_version():
    with library_version_lock:
        return library_version


class UserState:
    def __init__(self, user_id, username, songs):
        self.session_id  = str(uuid.uuid4())
        self.user_id     = user_id
        self.username    = username
        self.songs       = songs
        self.queue       = list(songs)
        self.current_idx = 0
        self.bytes_sent  = 0
        self.send_rate_kbps = 1000.0  # optimistic starting guess — assume fast until proven slow
        self.known_library_version = get_library_version()

    def update_send_rate(self, nbytes, elapsed):
        if elapsed <= 0:
            return
        instant_kbps = (nbytes / 1024) / elapsed
        # exponential moving average — smooths out one-off network blips
        self.send_rate_kbps = 0.7 * self.send_rate_kbps + 0.3 * instant_kbps


def get_db():
    return psycopg2.connect(**DB)


def scan_music_library():
    db = get_db()
    cur = db.cursor()
    files = [f for f in os.listdir(MUSIC_DIR) if f.endswith(".mp3")]
    if not files:
        print("[scan] no .mp3 files found in ./music/")
        db.close()
        return
    for filename in files:
        filepath = os.path.join(MUSIC_DIR, filename)
        file_size = os.path.getsize(filepath)
        title = filename[:-4].replace("_", " ").replace("-", " ").title()
        cur.execute("""
            INSERT INTO songs (filename, title, file_size_bytes)
            VALUES (%s, %s, %s)
            ON CONFLICT (filename) DO UPDATE
                SET file_size_bytes = EXCLUDED.file_size_bytes,
                    title = EXCLUDED.title
        """, (filename, title, file_size))
        print(f"[scan] synced: {filename} > '{title}' ({file_size} bytes)")
    db.commit()
    db.close()
    print(f"[scan] library sync complete - {len(files)} tracks")


def sync_library():
    """Diff ./music/ against the songs table. Inserts new files, removes
    rows for deleted files, updates rows for changed files. Returns True
    if anything changed."""
    db = get_db()
    cur = db.cursor()

    disk_files = set(f for f in os.listdir(MUSIC_DIR) if f.endswith(".mp3"))
    cur.execute("SELECT filename, file_size_bytes FROM songs")
    db_rows = {row[0]: row[1] for row in cur.fetchall()}
    db_files = set(db_rows.keys())

    changed = False

    for filename in disk_files - db_files:
        filepath = os.path.join(MUSIC_DIR, filename)
        file_size = os.path.getsize(filepath)
        title = filename[:-4].replace("_", " ").replace("-", " ").title()
        cur.execute("""
            INSERT INTO songs (filename, title, file_size_bytes)
            VALUES (%s, %s, %s)
            ON CONFLICT (filename) DO UPDATE
                SET file_size_bytes = EXCLUDED.file_size_bytes,
                    title = EXCLUDED.title
        """, (filename, title, file_size))
        print(f"[scan] new track: {filename}")
        changed = True

    for filename in db_files - disk_files:
        cur.execute("DELETE FROM songs WHERE filename = %s", (filename,))
        print(f"[scan] removed track: {filename}")
        changed = True

    for filename in disk_files & db_files:
        filepath = os.path.join(MUSIC_DIR, filename)
        current_size = os.path.getsize(filepath)
        if db_rows.get(filename) != current_size:
            title = filename[:-4].replace("_", " ").replace("-", " ").title()
            cur.execute(
                "UPDATE songs SET file_size_bytes = %s, title = %s WHERE filename = %s",
                (current_size, title, filename)
            )
            print(f"[scan] updated track: {filename}")
            changed = True

    if changed:
        db.commit()
    db.close()
    return changed


def library_scan_loop():
    global library_version
    while True:
        time.sleep(LIBRARY_SCAN_INTERVAL)
        if sync_library():
            with library_version_lock:
                library_version += 1
            print(f"[scan] library_version -> {library_version}")


def get_song_list():
    db = get_db()
    cur = db.cursor()
    cur.execute("""
        SELECT s.filename
        FROM songs s
        LEFT JOIN artists a ON s.artist_id = a.id
        ORDER BY s.title
    """)
    rows = cur.fetchall()
    db.close()
    return [row[0] for row in rows]


def sanitize_filename(name):
    base, ext = os.path.splitext(name)
    base = re.sub(r"[^\w\s.-]", "", base)
    base = re.sub(r"\s+", "_", base).strip("_-")
    if not base:
        base = "track"
    return base[:80] + ext


def download_song(url):
    """Run yt-dlp to fetch audio for a single URL into MUSIC_DIR.
    Returns (ok, filename_or_url)."""
    cmd = [
        "yt-dlp", "-x", "--audio-format", "mp3",
        "--restrict-filenames", "--no-playlist",
        "--print", "after_move:filepath",
        "-o", os.path.join(MUSIC_DIR, "%(title)s.%(ext)s"),
        url,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return False, url

    lines = [l.strip() for l in result.stdout.splitlines() if l.strip()]
    if not lines:
        return False, url

    filepath = lines[-1]
    filename = os.path.basename(filepath)
    clean_name = sanitize_filename(filename)

    if clean_name != filename:
        clean_path = os.path.join(MUSIC_DIR, clean_name)
        os.rename(filepath, clean_path)
        filename = clean_name

    return True, filename


def check_download_cooldown(user_id):
    now = time.time()
    with download_cooldowns_lock:
        last = download_cooldowns.get(user_id, 0)
        if now - last < DOWNLOAD_COOLDOWN:
            return False
        download_cooldowns[user_id] = now
        return True


def db_create_playlists(user_id, name):
    db = get_db()
    cur = db.cursor()
    try:
        cur.execute("BEGIN")
        cur.execute(
            "INSERT INTO playlists (user_id, name) VALUES (%s, %s) RETURNING id",
            (user_id, name)
        )
        playlist_id = cur.fetchone()[0]
        cur.execute("COMMIT")
        db.close()
        return playlist_id
    except psycopg2.errors.UniqueViolation:
        cur.execute("ROLLBACK")
        db.close()
        return None


def db_list_playlists(user_id):
    db = get_db()
    cur = db.cursor()
    cur.execute(
        "SELECT id, name FROM playlists WHERE user_id = %s ORDER BY created_at",
        (user_id,)
    )
    rows = cur.fetchall()
    db.close()
    return rows


def db_add_to_playlists(playlist_id, song_idx, songs):
    if song_idx < 0 or song_idx >= len(songs):
        return False
    filename = songs[song_idx]
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT id FROM songs WHERE filename = %s", (filename,))
    row = cur.fetchone()
    if not row:
        db.close()
        return False
    song_id = row[0]
    try:
        cur.execute("BEGIN")
        cur.execute("""
            INSERT INTO playlist_songs (playlist_id, song_id, position)
            VALUES (%s, %s,
                (SELECT COALESCE(MAX(position), 0) + 1
                 FROM playlist_songs WHERE playlist_id = %s)
            )
        """, (playlist_id, song_id, playlist_id))
        cur.execute("COMMIT")
        db.close()
        return True
    except:
        cur.execute("ROLLBACK")
        db.close()
        return False


def db_get_playlist_songs(playlist_id):
    db = get_db()
    cur = db.cursor()
    cur.execute("""
        SELECT s.filename
        FROM playlist_songs ps
        JOIN songs s ON ps.song_id = s.id
        WHERE ps.playlist_id = %s
        ORDER BY ps.position
    """, (playlist_id,))
    rows = cur.fetchall()
    db.close()
    return [row[0] for row in rows]


def db_playlist_owner(playlist_id):
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT user_id FROM playlists WHERE id = %s", (playlist_id,))
    row = cur.fetchone()
    db.close()
    return row[0] if row else None


def db_is_banned(ip):
    db = get_db()
    cur = db.cursor()
    now = datetime.datetime.now()
    cur.execute(
        "SELECT id FROM active_bans WHERE ip = %s AND expires_at > %s",
        (ip, now)
    )
    row = cur.fetchone()
    db.close()
    return row is not None


def db_ban_ip(ip, reason="brute force"):
    db = get_db()
    cur = db.cursor()
    expires = datetime.datetime.now() + datetime.timedelta(seconds=BAN_DURATION)
    cur.execute(
        "INSERT INTO active_bans (ip, reason, expires_at) VALUES (%s, %s, %s)",
        (ip, reason, expires)
    )
    db.commit()
    db.close()
    print(f"[ban] {ip} banned until {expires} — {reason}")


def check_and_record_fail(ip):
    with fail_counts_lock:
        fail_counts[ip] = fail_counts.get(ip, 0) + 1
        count = fail_counts[ip]
    if count >= BAN_THRESHOLD:
        db_ban_ip(ip, reason=f"brute force ({count} failures)")
        with fail_counts_lock:
            fail_counts.pop(ip, None)
        return True
    return False


def reset_fail_count(ip):
    with fail_counts_lock:
        fail_counts.pop(ip, None)


def recv_line(conn):
    buf = b""
    while b"\n" not in buf:
        part = conn.recv(1024)
        if not part:
            return None
        buf += part
    line, _ = buf.split(b"\n", 1)
    return line.decode().strip()


def get_transcoded_path(filename):
    base = filename.rsplit(".", 1)[0]
    transcoded_name = f"{base}_lq.mp3"
    transcoded_path = os.path.join(TRANSCODE_DIR, transcoded_name)

    with transcode_cache_lock:
        if os.path.exists(transcoded_path):
            cache_last_used[transcoded_name] = time.time()
            return transcoded_path, transcoded_name

    os.makedirs(TRANSCODE_DIR, exist_ok=True)
    input_path = os.path.join(MUSIC_DIR, filename)

    transcode_semaphore.acquire()  # cpu overload protection
    try:
        if not os.path.exists(transcoded_path):
            print(f"[transcode] encoding {filename} -> {transcoded_name} at {TRANSCODE_BITRATE}")
            subprocess.run(
                ["ffmpeg", "-y", "-i", input_path, "-b:a", TRANSCODE_BITRATE, transcoded_path],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
    finally:
        transcode_semaphore.release()

    with transcode_cache_lock:
        cache_last_used[transcoded_name] = time.time()
    return transcoded_path, transcoded_name


def transcode_cleanup_loop():
    while True:
        time.sleep(60)
        now = time.time()
        with transcode_cache_lock:
            stale = [name for name, last in cache_last_used.items()
                     if now - last > TRANSCODE_TTL]
            for name in stale:
                path = os.path.join(TRANSCODE_DIR, name)
                if os.path.exists(path):
                    os.remove(path)
                cache_last_used.pop(name, None)
                print(f"[transcode] cache evicted (TTL): {name}")


def stream_song(conn, filename, user_state, skip_bytes=0, filepath=None):
    if filepath is None:
        filepath = os.path.join(MUSIC_DIR, filename)
    filesize = os.path.getsize(filepath)
    remaining = filesize - skip_bytes
    conn.sendall(f"{remaining}\n".encode())
    with open(filepath, "rb") as f:
        f.seek(skip_bytes)
        while True:
            chunk = f.read(CHUNK_SIZE)
            if not chunk:
                break
            start = time.time()
            conn.sendall(chunk)
            elapsed = time.time() - start
            user_state.update_send_rate(len(chunk), elapsed)
            user_state.bytes_sent += len(chunk)
    user_state.bytes_sent = 0


def stream_song_list(conn, song_files, user_state, resume_bytes=0):
    for i, filename in enumerate(song_files):
        user_state.current_idx = i

        transcoded_name = None
        filepath = os.path.join(MUSIC_DIR, filename)
        skip = 0

        if user_state.send_rate_kbps < SLOW_THRESHOLD_KBPS:
            filepath, transcoded_name = get_transcoded_path(filename)
            print(f"[transcode] {user_state.username}'s link is slow "
                  f"({user_state.send_rate_kbps:.1f} KB/s) -> serving {transcoded_name}")
        elif i == 0:
            skip = resume_bytes

        conn.sendall(f"PLAYING:{filename}:{'LQ' if transcoded_name else 'HQ'}\n".encode())
        stream_song(conn, filename, user_state, skip_bytes=skip, filepath=filepath)
        conn.sendall(b"DONE\n")

        cmd = recv_line(conn)
        if cmd is None or cmd == "QUIT":
            return

        # check if the library has changed since this user last knew about it
        current_version = get_library_version()
        if current_version != user_state.known_library_version:
            songs_now = get_song_list()
            user_state.songs = songs_now
            user_state.known_library_version = current_version
            conn.sendall(("LIBRARY_CHANGED:" + "|".join(songs_now) + "\n").encode())


def handle_client(conn, addr):
    ip = addr[0]
    print(f"[+] connection from {addr}")

    if db_is_banned(ip):
        print(f"[ban] rejected {ip} — active ban")
        conn.sendall(b"BANNED\n")
        conn.close()
        return

    conn.sendall(b"AUTH_REQUIRED\n")

    first_line = recv_line(conn)
    if first_line is None:
        conn.close()
        return

    user_state = None

    if first_line.startswith("RESUME:"):
        session_id = first_line.split(":", 1)[1].strip()
        with sessions_lock:
            user_state = sessions.get(session_id)
        if user_state is None:
            conn.sendall(b"RESUME_FAIL\n")
            print(f"[!] resume failed for session {session_id[:8]}... from {addr}")
            conn.sendall(b"AUTH_REQUIRED\n")
            line = recv_line(conn)
            if line is None:
                conn.close()
                return
            parts = line.split(":", 2)
            if len(parts) != 3:
                conn.sendall(b"AUTH_FAIL\n")
                conn.close()
                return
            action, username, password = parts
            ok, user_id, username = _do_auth(conn, ip, action, username, password)
            if not ok:
                conn.close()
                return
            songs = get_song_list()
            if not songs:
                conn.sendall(b"NO_SONGS\n")
                conn.close()
                return
            user_state = UserState(user_id, username, songs)
            with sessions_lock:
                sessions[user_state.session_id] = user_state
            print(f"[session] {username} -> {user_state.session_id}")
            conn.sendall(f"SESSION:{user_state.session_id}\n".encode())
            conn.sendall(("SONGS:" + "|".join(songs) + "\n").encode())
        else:
            conn.sendall(b"RESUME_OK\n")
            print(f"[~] resumed session for {user_state.username} from {addr}")
            conn.sendall(("SONGS:" + "|".join(user_state.songs) + "\n").encode())
            remaining_queue = user_state.queue[user_state.current_idx:]
            resume_bytes = user_state.bytes_sent
            stream_song_list(conn, remaining_queue, user_state, resume_bytes=resume_bytes)
    else:
        parts = first_line.split(":", 2)
        if len(parts) != 3:
            conn.sendall(b"AUTH_FAIL\n")
            conn.close()
            return
        action, username, password = parts
        ok, user_id, username = _do_auth(conn, ip, action, username, password)
        if not ok:
            conn.close()
            return
        songs = get_song_list()
        if not songs:
            conn.sendall(b"NO_SONGS\n")
            conn.close()
            return
        user_state = UserState(user_id, username, songs)
        with sessions_lock:
            sessions[user_state.session_id] = user_state
        print(f"[session] {username} -> {user_state.session_id}")
        conn.sendall(f"SESSION:{user_state.session_id}\n".encode())
        conn.sendall(("SONGS:" + "|".join(user_state.songs) + "\n").encode())

    # command loop
    user_id = user_state.user_id
    songs = user_state.songs
    while True:
        cmd = recv_line(conn)
        if cmd is None or cmd == "QUIT":
            break

        if cmd.startswith("PLAY:"):
            idx = int(cmd.split(":", 1)[1])
            if idx < 0 or idx >= len(songs):
                idx = 0
            queue = songs[idx:] + songs[:idx]
            user_state.queue = queue
            user_state.current_idx = 0
            user_state.bytes_sent = 0
            stream_song_list(conn, queue, user_state)

        elif cmd == "LIST_PLAYLISTS":
            playlists = db_list_playlists(user_state.user_id)
            if not playlists:
                conn.sendall(b"PLAYLISTS:\n")
            else:
                parts = "|".join(f"{p[0]}:{p[1]}" for p in playlists)
                conn.sendall(f"PLAYLISTS:{parts}\n".encode())

        elif cmd.startswith("CREATE_PLAYLIST:"):
            name = cmd.split(":", 1)[1].strip()
            playlist_id = db_create_playlists(user_id, name)
            if playlist_id is None:
                conn.sendall(b"PLAYLIST_EXISTS\n")
            else:
                conn.sendall(f"PLAYLIST_CREATED:{playlist_id}\n".encode())

        elif cmd.startswith("ADD_TO_PLAYLIST:"):
            parts = cmd.split(":")
            playlist_id = int(parts[1])
            song_idx = int(parts[2])
            owner = db_playlist_owner(playlist_id)
            if owner != user_id:
                conn.sendall(b"ADDED_FAIL\n")
            else:
                ok = db_add_to_playlists(playlist_id, song_idx, songs)
                conn.sendall(b"ADDED_OK\n" if ok else b"ADDED_FAIL\n")

        elif cmd.startswith("PLAY_PLAYLIST:"):
            playlist_id = int(cmd.split(":", 1)[1])
            owner = db_playlist_owner(playlist_id)
            if owner != user_id:
                conn.sendall(b"PLAYLIST_FAIL\n")
                continue
            playlist_songs = db_get_playlist_songs(playlist_id)
            if not playlist_songs:
                conn.sendall(b"PLAYLIST_EMPTY\n")
                continue
            user_state.queue = playlist_songs
            user_state.current_idx = 0
            user_state.bytes_sent = 0
            conn.sendall(("PLAYLIST_SONGS:" + "|".join(playlist_songs) + "\n").encode())
            stream_song_list(conn, playlist_songs, user_state)

        elif cmd == "GET_SONGS":
            songs = get_song_list()
            user_state.songs = songs
            user_state.known_library_version = get_library_version()
            conn.sendall(("SONGS:" + "|".join(songs) + "\n").encode())

        elif cmd.startswith("DOWNLOAD_REQUEST:"):
            urls = [u for u in cmd.split(":", 1)[1].split("|") if u.strip()]

            if not check_download_cooldown(user_id):
                conn.sendall(b"DOWNLOAD_RATE_LIMITED\n")
                continue

            if len(urls) > MAX_LINKS_PER_REQUEST:
                conn.sendall(b"DOWNLOAD_TOO_MANY\n")
                continue

            for url in urls:
                ok, result = download_song(url)
                if ok:
                    conn.sendall(f"DOWNLOAD_RESULT:OK:{result}\n".encode())
                else:
                    conn.sendall(f"DOWNLOAD_RESULT:FAIL:{url}\n".encode())

            conn.sendall(b"DOWNLOAD_DONE\n")

    conn.close()
    print(f"[-] disconnected: {user_state.username} ({addr})")


def _do_auth(conn, ip, action, username, password):
    """Perform LOGIN or REGISTER. Returns (ok, user_id, username)."""
    db = get_db()
    cur = db.cursor()
    if action == "REGISTER":
        hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        try:
            cur.execute(
                "INSERT INTO users (username, password_hash) VALUES (%s, %s) RETURNING id",
                (username, hashed)
            )
            user_id = cur.fetchone()[0]
            db.commit()
            conn.sendall(b"AUTH_OK\n")
            print(f"[+] registered: {username}")
            reset_fail_count(ip)
            return True, user_id, username
        except psycopg2.errors.UniqueViolation:
            db.rollback()
            conn.sendall(b"AUTH_FAIL\n")
            if check_and_record_fail(ip):
                conn.sendall(b"BANNED\n")
            return False, None, None
        finally:
            db.close()
    elif action == "LOGIN":
        cur.execute("SELECT id, password_hash FROM users WHERE username = %s", (username,))
        row = cur.fetchone()
        db.close()
        if row and bcrypt.checkpw(password.encode(), row[1].encode()):
            conn.sendall(b"AUTH_OK\n")
            print(f"[+] login: {username}")
            reset_fail_count(ip)
            return True, row[0], username
        else:
            conn.sendall(b"AUTH_FAIL\n")
            if check_and_record_fail(ip):
                conn.sendall(b"BANNED\n")
            return False, None, None
    db.close()
    conn.sendall(b"AUTH_FAIL\n")
    if check_and_record_fail(ip):
        conn.sendall(b"BANNED\n")
    return False, None, None


def backup_loop():
    os.makedirs(BACKUP_DIR, exist_ok=True)
    while True:
        time.sleep(BACKUP_INTERVAL)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filepath = os.path.join(BACKUP_DIR, f"backup_{timestamp}.sql")
        result = os.system(f"pg_dump -h localhost -U musicuser musicdb > {filepath}")
        if result == 0:
            print(f"[backup] saved: {filepath}")
        else:
            print(f"[backup] failed at {timestamp}")


def main():
    scan_music_library()
    os.makedirs(TRANSCODE_DIR, exist_ok=True)

    t = threading.Thread(target=backup_loop)
    t.daemon = True
    t.start()

    t2 = threading.Thread(target=transcode_cleanup_loop)
    t2.daemon = True
    t2.start()

    t3 = threading.Thread(target=library_scan_loop)
    t3.daemon = True
    t3.start()

    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind((HOST, PORT))
    server_socket.listen()
    print(f"[*] streaming server on {HOST}:{PORT}")
    while True:
        conn, addr = server_socket.accept()
        thread = threading.Thread(target=handle_client, args=(conn, addr))
        thread.daemon = True
        thread.start()


if __name__ == "__main__":
    main()