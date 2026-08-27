# delta-t3 — CTF Challenge Suite (Build + Solve)

A self-contained set of **5 CTF challenges** across pwn, crypto, web, forensics, and reverse-engineering categories, each shipped with both the vulnerable target **and** a working exploit/solver. Built as a Delta Force induction task — designed to be run, attacked, and verified end-to-end, not just theoretical.

## Challenges

### 1. Pwn — Stack Buffer Overflow (`pwn/`)
`vuln.c` reads 200 bytes into a 64-byte stack buffer with no bounds checking (`read(0, buffer, 200)`), while an unreachable `win()` function sits in the binary printing the flag.
`exploit.py` (via `pwntools`) computes the exact saved-return-address offset (`OFFSET=72`), builds a `b'A'*72 + p64(win_addr)` payload, and redirects execution straight into `win()` — classic ret2win.

```bash
gcc -fno-stack-protector -no-pie pwn/vuln.c -o pwn/vuln
python3 pwn/exploit.py
```

### 2. Crypto — MD5+Salt PIN Cracking (`crypto/`)
`server.py` is a Flask service that exposes `MD5(PIN + salt)` for a secret 4-digit PIN without exposing the PIN itself.
`crack.py` brute-forces all 10,000 possible 4-digit PINs, matching hashes locally, then submits the recovered PIN to `/submit-pin` to retrieve the flag.

```bash
python3 crypto/server.py &
python3 crypto/crack.py
```
Also includes a SHA-256 variant (`server_sha_256.py` / `crack_sha_256.py`) to compare crack time against MD5.

### 3. Web — Blind SQL Injection (`web/`)
`server.py` builds its login query with raw string concatenation (`f"SELECT * FROM students WHERE roll_number={roll} AND password='{password}'"`), making it trivially injectable.
`exploit.py` uses a boolean-based injection (`x' OR roll_number={n} -- `) to log in as every roll number in sequence without knowing any password, pulls each student's mark from `/my-mark`, and reports the top scorer — demonstrating full account enumeration via SQLi.

```bash
python3 web/seed_db.py   # build students.db
python3 web/server.py &
python3 web/exploit.py
```

### 4. Forensics — Steganography Chain (`forensics/`)
A multi-layered hidden-data challenge (`build.py` generates it, `solve.py` reverses it):
1. EXIF comment on `cover.png` hints to check least-significant bits
2. LSB-decoding the image pixels yields a Base64 string
3. Base64-decoding gives the password to `secret.zip`
4. The unzipped file contains a **reversed + Caesar-shifted** flag
5. Brute-forcing all 26 Caesar shifts and un-reversing recovers the real flag, matched against a `CTF{...}` regex

```bash
python3 forensics/build.py   # (re)generate the challenge artifacts
python3 forensics/solve.py   # solve chain: EXIF -> LSB -> base64 -> zip -> Caesar
```

### 5. Reverse Engineering — Constraint-Based Key Recovery (`reverse_engineering/`)
`validate.c` defines a key-validation function using arithmetic/bitwise constraints on three 32-bit integers (addition, XOR, modulo, division).
`solve.py` uses the **Z3 SMT solver** to recover the only values of `b0`, `b1`, `b2` satisfying all four constraints simultaneously, then re-encodes them into a custom base-9 alphabet (`CDIKNOSUW`) to produce the final license-key-style string.

```bash
python3 reverse_engineering/solve.py
```

## Infra

`docker-compose.yml` / `Dockerfile` / `nginx/nginx.conf` containerize the web and crypto challenge services for consistent deployment during the CTF.

## What it demonstrates

- End-to-end exploit development, not just vulnerability description: every challenge ships a working automated solver
- `pwntools` for binary exploitation (offset-finding, `p64` packing, symbol resolution from the ELF)
- Z3 for constraint solving instead of brute force where the search space is too large for exhaustive search
- Practical understanding of common real-world bug classes: stack overflows, SQL injection, weak hashing, and steganographic data hiding
- Challenge design discipline: build/solve symmetry so every challenge is independently verifiable
