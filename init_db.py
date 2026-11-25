import sqlite3
with open("schema.sql", encoding="utf-8") as f:
    schema = f.read()
conn = sqlite3.connect("database.db")
conn.executescript(schema)
conn.commit()
conn.close()
print("Database siap.")
