import sqlite3

conn = sqlite3.connect("students.db")
cur = conn.cursor()

cur.execute("DROP TABLE IF EXISTS students")
cur.execute("""
    CREATE TABLE students (
        roll_number INTEGER PRIMARY KEY,
        password TEXT,
        mark INTEGER
    )
""")

students = [
    (1, "pass1apple",   62),
    (2, "pass2banana",  74),
    (3, "pass3cherry",  81),
    (4, "pass4date",    55),
    (5, "pass5elder",   69),
    (6, "pass6fig",     88),
    (7, "pass7grape",   97),   # top scorer
    (8, "pass8honey",   73),
    (9, "pass9ivy",     60),
    (10, "pass10jam",   79),
]

cur.executemany("INSERT INTO students VALUES (?, ?, ?)", students)
conn.commit()
conn.close()

print("students.db seeded with 10 records. Top mark is roll_number 7 (97).")