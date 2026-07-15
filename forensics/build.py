import base64
import random
import subprocess
from PIL import Image
from PIL.PngImagePlugin import PngInfo

ZIP_PASSWORD = "CTF{st3g_m3_1f_y0u_c4n}"   
REAL_FLAG = "CTF{ex1f_lsb_z1p_c43s4r_ch41n}"
DELIMITER = "#####END#####"

COVER_IMAGE = "cover.png"
FLAG_FILE = "flag.txt"
ZIP_FILE = "secret.zip"


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


def str_to_bits(s: str) -> str:
    return "".join(f"{byte:08b}" for byte in s.encode())


def embed_lsb(image_path: str, payload: str, out_path: str):
    img = Image.open(image_path).convert("RGB")
    pixels = list(img.getdata())

    bits = str_to_bits(payload + DELIMITER)
    if len(bits) > len(pixels) * 3:
        raise ValueError("Image too small to hold payload")

    flat = [channel for pixel in pixels for channel in pixel]

    for i, bit in enumerate(bits):
        flat[i] = (flat[i] & ~1) | int(bit)

    new_pixels = [tuple(flat[i:i + 3]) for i in range(0, len(flat), 3)]
    img.putdata(new_pixels)

    meta = PngInfo()
    meta.add_text("Comment", "Check the least significant bits ;)")
    img.save(out_path, pnginfo=meta)


def make_cover_image(path: str, width: int, height: int):
    img = Image.new("RGB", (width, height))
    pixels = []
    for y in range(height):
        for x in range(width):
            pixels.append(((x * 3) % 256, (y * 3) % 256, ((x + y) * 2) % 256))
    img.putdata(pixels)
    img.save(path)


def make_secret_zip(flag_text: str, shift: int):
    scrambled = caesar_shift(flag_text[::-1], shift)
    with open(FLAG_FILE, "w") as f:
        f.write(scrambled)

    subprocess.run(
        ["zip", "-P", ZIP_PASSWORD, "-j", ZIP_FILE, FLAG_FILE],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    return scrambled


if __name__ == "__main__":
    shift = random.randint(1, 25)

    hint_b64 = base64.b64encode(ZIP_PASSWORD.encode()).decode()
    print(f"[build] Caesar shift chosen: {shift}")
    print(f"[build] Base64 hint (to hide via LSB): {hint_b64}")

    make_cover_image(COVER_IMAGE, width=40, height=40)
    embed_lsb(COVER_IMAGE, hint_b64, COVER_IMAGE)

    scrambled = make_secret_zip(REAL_FLAG, shift)

    print(f"[build] Scrambled flag written into {FLAG_FILE}: {scrambled}")
    print(f"[build] {ZIP_FILE} created, password-protected")
    print(f"[build] Done. Challenge files: {COVER_IMAGE}, {ZIP_FILE}")