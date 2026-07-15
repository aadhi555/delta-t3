import socket
import subprocess
import threading
import curses
import time
import json
import os

HOST = "127.0.0.1"
PORT = 9001          # connects through nginx (nginx proxies to server on 9000)
IPC_PATH = "/tmp/mpvsocket"
TMP_TRACK = "/tmp/current_track.mp3"
DOWNLOAD_LINKS_FILE = "./download_links.txt"
MAX_LINKS_PER_REQUEST = 5

_buf = b""
_session_id = None


def recv_line(sock):
    global _buf
    while b"\n" not in _buf:
        chunk = sock.recv(1024)
        if not chunk:
            return None
        _buf += chunk
    line, _buf = _buf.split(b"\n", 1)
    return line.decode().strip()


def receive_to_file(sock, filesize, dest):
    global _buf
    received = 0
    with open(dest, "wb") as f:
        if _buf:
            take = min(len(_buf), filesize)
            f.write(_buf[:take])
            _buf = _buf[take:]
            received += take
        while received < filesize:
            chunk = sock.recv(min(4096, filesize - received))
            if not chunk:
                break
            f.write(chunk)
            received += len(chunk)
    return received == filesize


def mpv_send(cmd):
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(IPC_PATH)
        s.sendall((json.dumps({"command": cmd}) + "\n").encode())
        response = s.recv(4096).decode().strip()
        s.close()
        return json.loads(response)
    except:
        return None


def mpv_get(prop):
    result = mpv_send(["get_property", prop])
    if result and result.get("error") == "success":
        return result.get("data")
    return None


def mpv_set(prop, value):
    mpv_send(["set_property", prop, value])


def wait_for_ipc(timeout=5):
    start = time.time()
    while time.time() - start < timeout:
        if os.path.exists(IPC_PATH):
            return True
        time.sleep(0.1)
    return False


def format_time(seconds):
    if seconds is None:
        return "--:--"
    s = int(seconds)
    return f"{s // 60}:{s % 60:02d}"


def draw_tui(stdscr, state):
    try:
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        bar_width = max(10, w - 24)
        stdscr.addstr(0, 0, "=" * (w - 1))
        title = " * music stream "
        stdscr.addstr(1, max(0, (w - len(title)) // 2), title)
        stdscr.addstr(2, 0, "=" * (w - 1))
        song = state.get("song_name", "-")
        status_tag = " [paused]" if state.get("paused") else " [playing]"
        quality_tag = " [LOW QUALITY]" if state.get("quality") == "LQ" else ""
        stdscr.addstr(3, 2, f"now playing: {song}{status_tag}{quality_tag}"[:w - 3])
        pos = state.get("position") or 0
        dur = state.get("duration") or 0
        frac = (pos / dur) if dur > 0 else 0
        filled = int(frac * bar_width)
        bar = "█" * filled + "░" * (bar_width - filled)
        stdscr.addstr(5, 2, f"[{bar}]  {format_time(pos)} / {format_time(dur)}"[:w - 3])
        if state.get("library_note"):
            stdscr.addstr(h - 4, 2, state["library_note"][:w - 3])
        stdscr.addstr(h - 3, 0, "=" * (w - 1))
        stdscr.addstr(h - 2, 0, "  [p] pause/resume   [n] next   [b] back to menu   [q] quit"[:w - 1])
        stdscr.addstr(h - 1, 2, state.get("status", "")[:w - 3])
        stdscr.refresh()
    except curses.error:
        pass


def show_banned_screen(stdscr):
    """Show a message when the server has banned this IP."""
    stdscr.nodelay(False)
    stdscr.erase()
    stdscr.addstr(0, 0, "your IP has been banned.")
    stdscr.addstr(1, 0, "too many failed login attempts.")
    stdscr.addstr(3, 0, "try again later. press any key to exit.")
    stdscr.refresh()
    stdscr.getch()


def connect_and_authenticate(stdscr):
    global _session_id, _buf
    _buf = b""

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((HOST, PORT))

    prompt = recv_line(sock)

    # IP is banned — server sent BANNED instead of AUTH_REQUIRED
    if prompt == "BANNED":
        sock.close()
        show_banned_screen(stdscr)
        return None, None

    if prompt != "AUTH_REQUIRED":
        sock.close()
        return None, None

    if _session_id:
        sock.sendall(f"RESUME:{_session_id}\n".encode())
        response = recv_line(sock)
        if response == "RESUME_OK":
            songs_line = recv_line(sock)
            songs = songs_line.replace("SONGS:", "").split("|")
            return sock, songs
        # RESUME_FAIL — server sends AUTH_REQUIRED next, fall through to auth_screen
        result = recv_line(sock)
        if result != "AUTH_REQUIRED":
            sock.close()
            return None, None

    # fresh connection or after RESUME_FAIL — run full auth
    if not auth_screen(stdscr, sock):
        # check if auth failure was because we got banned mid-attempt
        # (server sends BANNED after AUTH_FAIL when threshold is hit)
        # auth_screen already showed the AUTH_FAIL — we just clean up here
        stdscr.nodelay(False)
        stdscr.erase()
        stdscr.addstr(0, 0, "auth failed. press any key.")
        stdscr.refresh()
        stdscr.getch()
        sock.close()
        return None, None

    session_line = recv_line(sock)

    # server may send BANNED right after AUTH_FAIL on the threshold attempt
    # auth_screen returns False in that case, handled above — but guard here too
    if session_line == "BANNED":
        sock.close()
        show_banned_screen(stdscr)
        return None, None

    if session_line and session_line.startswith("SESSION:"):
        _session_id = session_line.split(":", 1)[1].strip()

    songs_line = recv_line(sock)
    if songs_line == "NO_SONGS":
        stdscr.erase()
        stdscr.addstr(0, 0, "server has no songs.")
        stdscr.refresh()
        time.sleep(2)
        sock.close()
        return None, None

    songs = songs_line.replace("SONGS:", "").split("|")
    return sock, songs


def auth_screen(stdscr, sock):
    curses.echo()
    curses.curs_set(1)
    stdscr.nodelay(False)
    stdscr.erase()
    stdscr.addstr(0, 0, "=== music stream ===")
    stdscr.addstr(2, 0, "  [1] login")
    stdscr.addstr(3, 0, "  [2] register")
    stdscr.addstr(5, 0, "choice: ")
    stdscr.refresh()
    choice = stdscr.getstr().decode().strip()
    action = "LOGIN" if choice == "1" else "REGISTER"
    stdscr.addstr(7, 0, "username: ")
    stdscr.refresh()
    username = stdscr.getstr().decode().strip()
    stdscr.addstr(8, 0, "password: ")
    curses.noecho()
    stdscr.refresh()
    password = stdscr.getstr().decode().strip()
    curses.echo()
    sock.sendall(f"{action}:{username}:{password}\n".encode())
    result = recv_line(sock)
    curses.noecho()
    curses.curs_set(0)
    return result == "AUTH_OK"


def main_menu(stdscr):
    curses.curs_set(0)
    stdscr.nodelay(False)
    stdscr.erase()
    stdscr.addstr(0, 0, "=" * 40)
    stdscr.addstr(1, 2, "* music stream - main menu")
    stdscr.addstr(2, 0, "=" * 40)
    stdscr.addstr(4, 2, "[1]  browse songs")
    stdscr.addstr(5, 2, "[2]  my playlists")
    stdscr.addstr(6, 2, "[3]  create playlist")
    stdscr.addstr(7, 2, "[d]  download from youtube")
    stdscr.addstr(8, 2, "[r]  refresh library")
    stdscr.addstr(9, 2, "[q]  quit")
    stdscr.addstr(11, 2, "choice: ")
    stdscr.refresh()
    while True:
        key = stdscr.getch()
        if key == ord("1"): return "browse"
        elif key == ord("2"): return "playlists"
        elif key == ord("3"): return "create"
        elif key == ord("d"): return "download"
        elif key == ord("r"): return "refresh"
        elif key == ord("q"): return "quit"


def browse_screen(stdscr, sock, songs):
    curses.echo()
    curses.curs_set(1)
    stdscr.nodelay(False)
    stdscr.erase()
    stdscr.addstr(0, 0, "=" * 40)
    stdscr.addstr(1, 2, "* browse songs")
    stdscr.addstr(2, 0, "=" * 40)
    for i, s in enumerate(songs):
        stdscr.addstr(4 + i, 2, f"[{i}]  {s}")
    stdscr.addstr(4 + len(songs) + 1, 2, f"enter number (0-{len(songs)-1}): ")
    stdscr.refresh()
    choice = stdscr.getstr().decode().strip()
    curses.noecho()
    curses.curs_set(0)
    try:
        idx = int(choice)
    except ValueError:
        idx = 0
    sock.sendall(f"PLAY:{idx}\n".encode())
    return playback_screen(stdscr, sock, songs)


def playlists_screen(stdscr, sock, songs):
    sock.sendall(b"LIST_PLAYLISTS\n")
    response = recv_line(sock)
    raw = response.replace("PLAYLISTS:", "")
    if not raw:
        stdscr.nodelay(False)
        stdscr.erase()
        stdscr.addstr(0, 0, "you have no playlists yet.")
        stdscr.addstr(2, 0, "press any key to go back.")
        stdscr.refresh()
        stdscr.getch()
        return "menu"
    playlists = []
    for entry in raw.split("|"):
        pid, pname = entry.split(":", 1)
        playlists.append((int(pid), pname))
    curses.curs_set(1)
    curses.echo()
    stdscr.nodelay(False)
    stdscr.erase()
    stdscr.addstr(0, 0, "=" * 40)
    stdscr.addstr(1, 2, "* my playlists")
    stdscr.addstr(2, 0, "=" * 40)
    for i, (pid, pname) in enumerate(playlists):
        stdscr.addstr(4 + i, 2, f"[{i}]  {pname}  (id:{pid})")
    stdscr.addstr(4 + len(playlists) + 1, 2, f"enter number to play (0-{len(playlists)-1}): ")
    stdscr.refresh()
    choice = stdscr.getstr().decode().strip()
    curses.noecho()
    curses.curs_set(0)
    try:
        idx = int(choice)
        if idx < 0 or idx >= len(playlists): idx = 0
    except ValueError:
        idx = 0
    playlist_id = playlists[idx][0]
    sock.sendall(f"PLAY_PLAYLIST:{playlist_id}\n".encode())
    response = recv_line(sock)
    if response in ("PLAYLIST_EMPTY", "PLAYLIST_FAIL"):
        stdscr.erase()
        stdscr.addstr(0, 0, "playlist is empty or unavailable.")
        stdscr.addstr(2, 0, "press any key.")
        stdscr.refresh()
        stdscr.getch()
        return "menu"
    return playback_screen(stdscr, sock, songs)


def create_playlist_screen(stdscr, sock, songs):
    curses.echo()
    curses.curs_set(1)
    stdscr.nodelay(False)
    stdscr.erase()
    stdscr.addstr(0, 0, "=" * 40)
    stdscr.addstr(1, 2, "* create playlist")
    stdscr.addstr(2, 0, "=" * 40)
    stdscr.addstr(4, 2, "playlist name: ")
    stdscr.refresh()
    name = stdscr.getstr().decode().strip()
    curses.noecho()
    if not name:
        return "menu"
    sock.sendall(f"CREATE_PLAYLIST:{name}\n".encode())
    response = recv_line(sock)
    stdscr.erase()
    if response == "PLAYLIST_EXISTS":
        stdscr.addstr(0, 0, f"a playlist named '{name}' already exists.")
        stdscr.addstr(2, 0, "press any key.")
        stdscr.refresh()
        stdscr.getch()
        return "menu"
    playlist_id = int(response.split(":")[1])
    stdscr.addstr(0, 0, f"playlist '{name}' created! (id:{playlist_id})")
    stdscr.addstr(2, 0, "add songs to it now? [y/n]: ")
    stdscr.refresh()
    key = stdscr.getch()
    if key != ord("y"):
        return "menu"
    while True:
        curses.echo()
        curses.curs_set(1)
        stdscr.erase()
        stdscr.addstr(0, 0, "=" * 40)
        stdscr.addstr(1, 2, f"adding to: {name}")
        stdscr.addstr(2, 0, "=" * 40)
        for i, s in enumerate(songs):
            stdscr.addstr(4 + i, 2, f"[{i}]  {s}")
        stdscr.addstr(4 + len(songs) + 1, 2, "song number (or 'done'): ")
        stdscr.refresh()
        inp = stdscr.getstr().decode().strip()
        curses.noecho()
        curses.curs_set(0)
        if inp == "done" or inp == "":
            break
        try:
            song_idx = int(inp)
        except ValueError:
            continue
        sock.sendall(f"ADD_TO_PLAYLIST:{playlist_id}:{song_idx}\n".encode())
        response = recv_line(sock)
        stdscr.erase()
        if response == "ADDED_OK":
            stdscr.addstr(0, 0, f"added {songs[song_idx]} to '{name}'")
        else:
            stdscr.addstr(0, 0, "failed to add song.")
        stdscr.addstr(2, 0, "add another? [y/n]: ")
        stdscr.refresh()
        key = stdscr.getch()
        if key != ord("y"):
            break
    return "menu"


def download_screen(stdscr, sock):
    stdscr.nodelay(False)
    stdscr.erase()
    stdscr.addstr(0, 0, "=" * 40)
    stdscr.addstr(1, 2, "* download from youtube")
    stdscr.addstr(2, 0, "=" * 40)

    if not os.path.exists(DOWNLOAD_LINKS_FILE):
        stdscr.addstr(4, 2, f"no {DOWNLOAD_LINKS_FILE} found.")
        stdscr.addstr(5, 2, "create it with one youtube url per line.")
        stdscr.addstr(7, 2, "press any key.")
        stdscr.refresh()
        stdscr.getch()
        return "menu"

    with open(DOWNLOAD_LINKS_FILE) as f:
        urls = [line.strip() for line in f if line.strip()]

    if not urls:
        stdscr.addstr(4, 2, f"{DOWNLOAD_LINKS_FILE} is empty.")
        stdscr.addstr(6, 2, "press any key.")
        stdscr.refresh()
        stdscr.getch()
        return "menu"

    stdscr.addstr(4, 2, f"found {len(urls)} link(s). requesting download...")
    stdscr.refresh()

    sock.sendall(("DOWNLOAD_REQUEST:" + "|".join(urls) + "\n").encode())
    line = recv_line(sock)

    if line == "DOWNLOAD_RATE_LIMITED":
        stdscr.addstr(6, 2, "rate limited - wait before downloading again.")
        stdscr.addstr(8, 2, "press any key.")
        stdscr.refresh()
        stdscr.getch()
        return "menu"

    if line == "DOWNLOAD_TOO_MANY":
        stdscr.addstr(6, 2, f"too many links (max {MAX_LINKS_PER_REQUEST} per request).")
        stdscr.addstr(8, 2, "press any key.")
        stdscr.refresh()
        stdscr.getch()
        return "menu"

    row = 6
    while line != "DOWNLOAD_DONE":
        if line.startswith("DOWNLOAD_RESULT:"):
            parts = line.split(":", 2)
            status, target = parts[1], parts[2]
            tag = "OK" if status == "OK" else "FAIL"
            stdscr.addstr(row, 2, f"[{tag}] {target}"[:60])
            stdscr.refresh()
            row += 1
        line = recv_line(sock)

    stdscr.addstr(row + 1, 2, "done. press any key.")
    stdscr.refresh()
    stdscr.getch()
    return "menu"


def playback_screen(stdscr, sock, songs):
    state = {"song_name": "", "duration": None, "position": None,
             "paused": False, "status": "buffering..."}
    lock = threading.Lock()
    next_flag = threading.Event()
    quit_flag = threading.Event()
    back_flag = threading.Event()
    mpv_proc = [None]

    def start_mpv():
        if mpv_proc[0]:
            mpv_proc[0].terminate()
        if os.path.exists(IPC_PATH):
            os.remove(IPC_PATH)
        mpv_proc[0] = subprocess.Popen(
            ["mpv", "--no-video", "--input-ipc-server=" + IPC_PATH,
             "--idle=yes", "--really-quiet"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        wait_for_ipc()

    def streaming_loop():
        start_mpv()
        while not quit_flag.is_set() and not back_flag.is_set():
            line = recv_line(sock)
            if line is None:
                with lock: state["status"] = "disconnected"
                break
            if line.startswith("LIBRARY_CHANGED:"):
                payload = line[len("LIBRARY_CHANGED:"):]
                new_songs = payload.split("|") if payload else []
                songs[:] = new_songs
                with lock: state["library_note"] = "library updated"
                continue
            if not line.startswith("PLAYING:"):
                continue
            parts = line[len("PLAYING:"):].split(":")
            song_name = parts[0]
            quality = parts[1] if len(parts) > 1 else "HQ"
            with lock:
                state["song_name"] = song_name
                state["quality"] = quality
                state["status"] = "buffering..."
                state["library_note"] = ""
            size_line = recv_line(sock)
            if size_line is None: break
            ok = receive_to_file(sock, int(size_line), TMP_TRACK)
            if not ok: break
            mpv_send(["loadfile", TMP_TRACK, "replace"])
            with lock:
                state["status"] = "playing"
                state["paused"] = False
            recv_line(sock)  # DONE
            while not quit_flag.is_set() and not back_flag.is_set():
                if mpv_get("eof-reached") or next_flag.is_set():
                    break
                time.sleep(0.3)
            next_flag.clear()
            if quit_flag.is_set() or back_flag.is_set(): break
            sock.sendall(b"NEXT\n")
        if mpv_proc[0]: mpv_proc[0].terminate()

    def poll_mpv():
        while not quit_flag.is_set() and not back_flag.is_set():
            pos = mpv_get("time-pos")
            dur = mpv_get("duration")
            paused = mpv_get("pause")
            with lock:
                state["position"] = pos
                state["duration"] = dur
                if paused is not None: state["paused"] = paused
            time.sleep(0.5)

    threading.Thread(target=streaming_loop, daemon=True).start()
    threading.Thread(target=poll_mpv, daemon=True).start()

    stdscr.nodelay(True)
    stdscr.timeout(200)
    curses.curs_set(0)

    while not quit_flag.is_set():
        with lock: s = dict(state)
        draw_tui(stdscr, s)
        key = stdscr.getch()
        if key == ord("q"):
            quit_flag.set()
            mpv_send(["stop"])
            mpv_send(["quit"])
            sock.sendall(b"QUIT\n")
            return "quit"
        elif key == ord("b"):
            back_flag.set()
            mpv_send(["stop"])
            mpv_send(["quit"])
            sock.sendall(b"QUIT\n")
            time.sleep(0.3)
            return "menu"
        elif key == ord("p"):
            paused = mpv_get("pause")
            if paused is not None: mpv_set("pause", not paused)
        elif key == ord("n"):
            next_flag.set()
            mpv_send(["stop"])
    return "quit"


def run(stdscr):
    curses.curs_set(0)
    sock, songs = connect_and_authenticate(stdscr)
    if sock is None:
        return
    while True:
        action = main_menu(stdscr)
        if action == "quit":
            sock.sendall(b"QUIT\n")
            break
        elif action == "browse":
            result = browse_screen(stdscr, sock, songs)
            if result == "quit": break
        elif action == "playlists":
            result = playlists_screen(stdscr, sock, songs)
            if result == "quit": break
        elif action == "create":
            result = create_playlist_screen(stdscr, sock, songs)
            if result == "quit": break
        elif action == "download":
            result = download_screen(stdscr, sock)
            if result == "quit": break
        elif action == "refresh":
            sock.sendall(b"GET_SONGS\n")
            response = recv_line(sock)
            if response and response.startswith("SONGS:"):
                payload = response[len("SONGS:"):]
                songs[:] = payload.split("|") if payload else []
    sock.close()


def main():
    curses.wrapper(run)


if __name__ == "__main__":
    main()