import base64
import re
import subprocess
import zipfile
from PIL import Image

COVER_IMAGE = "cover.png"
ZIP_FILE = "secret.zip"
FLAG_FILE = "flag.txt"
DELIMITER = "#####END#####"
FLAG_PATTERN = re.compile(r"CTF\{.*?\}")


def read_exif_comment(image_path: str) -> str:
    output = subprocess.run(
        ["exiftool", "-Comment", image_path],
        capture_output=True, text=True, check=True
    ).stdout
    return output.split(":", 1)[1].strip()


def bits_to_str(bits: str) -> str:
    chars = [bits[i:i + 8] for i in range(0, len(bits), 8)]
    return "".join(chr(int(b, 2)) for b in chars)


def extract_lsb(image_path: str) -> str:
    img = Image.open(image_path).convert("RGB")
    pixels = list(img.getdata())
    flat = [channel for pixel in pixels for channel in pixel]

    bits = "".join(str(byte & 1) for byte in flat)

    decoded = ""
    for i in range(0, len(bits), 8):
        byte = bits[i:i + 8]
        if len(byte) < 8:
            break
        decoded += chr(int(byte, 2))
        if decoded.endswith(DELIMITER):
            return decoded[: -len(DELIMITER)]
    raise ValueError("Delimiter not found — payload may be corrupted")


def unlock_zip(zip_path: str, password: str) -> str:
    with zipfile.ZipFile(zip_path) as zf:
        name = zf.namelist()[0]
        with zf.open(name, pwd=password.encode()) as f:
            return f.read().decode()


def caesar_shift(text: str, shift: int) -> str:
    result = []
    for ch in text:
        if ch.isupper():
            result.append(chr((ord(ch) - ord('A') + shift) % 26 + ord('A')))
        elif ch.islower():
            result.append(chr((ord(ch) - ord('a') + shift) % 26 + ord('a')))
        else:
            result.append(ch)
    return "".join(result)


def crack_flag(scrambled: str) -> str:
    for shift in range(26):
        unshifted = caesar_shift(scrambled, -shift)
        candidate = unshifted[::-1]
        if FLAG_PATTERN.search(candidate):
            return candidate, shift
    return None, None


if __name__ == "__main__":
    comment = read_exif_comment(COVER_IMAGE)
    print(f"[solve] EXIF Comment: {comment}")

    hint_b64 = extract_lsb(COVER_IMAGE)
    print(f"[solve] LSB-extracted base64 hint: {hint_b64}")

    zip_password = base64.b64decode(hint_b64).decode()
    print(f"[solve] Decoded ZIP password: {zip_password}")

    scrambled = unlock_zip(ZIP_FILE, zip_password)
    print(f"[solve] Scrambled flag text from {FLAG_FILE}: {scrambled}")

    flag, shift = crack_flag(scrambled)
    print(f"[solve] Cracked Caesar shift: {shift}")
    print(f"[solve] Recovered flag: {flag}")