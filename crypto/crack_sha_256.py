import requests
import hashlib

BASE_URL = "http://127.0.0.1:5001"
SALT = "salt"

def get_target_hash():
    response = requests.get(f"{BASE_URL}/get-flag-hash")
    return response.json()["hash"]

def crack_pin(target_hash: str) -> str:
    for i in range(10000):
        pin = f"{i:04d}"
        guess_hash = hashlib.sha256((pin + SALT).encode()).hexdigest()
        if guess_hash == target_hash:
            return pin
    return None

def submit_pin(pin: str):
    response = requests.post(f"{BASE_URL}/submit-pin", json={"pin": pin})
    return response.json()

if __name__ == "__main__":
    target_hash = get_target_hash()
    print(f"Target hash: {target_hash}")

    cracked_pin = crack_pin(target_hash)
    print(f"Cracked PIN: {cracked_pin}")

    result = submit_pin(cracked_pin)
    print(f"Server response: {result}")