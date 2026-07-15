from z3 import Solver, BitVec, sat

b0 = BitVec('b0', 32)
b1 = BitVec('b1', 32)
b2 = BitVec('b2', 32)

s = Solver()
s.add((b0 + 1337) == 2007)   # b0 + 1337 == 2007
s.add((b0 ^ b1) == 1570)     # b0 XOR b1 == 1570
s.add((b2 % b1) == 870)      # b2 mod b1 == 870
s.add((b2 / 2) == 22251)     # b2 // 2 == 22251 (unsigned/integer division)

assert s.check() == sat, "No solution found — constraints are unsatisfiable"
model = s.model()

b0_val = model[b0].as_long()
b1_val = model[b1].as_long()
b2_val = model[b2].as_long()

print(f"b0 = {b0_val}")
print(f"b1 = {b1_val}")
print(f"b2 = {b2_val}")

ALPHABET = "CDIKNOSUW"

def to_base9_string(n: int, width: int) -> str:
    digits = []
    for _ in range(width):
        n, rem = divmod(n, 9)
        digits.append(rem)
    digits.reverse()
    return "".join(ALPHABET[d] for d in digits)

chunk0 = to_base9_string(b0_val, 3)
chunk1 = to_base9_string(b1_val, 4)
chunk2 = to_base9_string(b2_val, 5)

key = f"{chunk0}-{chunk1}-{chunk2}"
print(f"\nRecovered key: {key}")