import sqlite3

conn = sqlite3.connect('submissions.db')
cursor = conn.cursor()

try:
    # Adding 'views' column if it doesn't exist
    cursor.execute("ALTER TABLE submissions ADD COLUMN views INTEGER DEFAULT 0")
    print("Added 'views' column successfully.")
except sqlite3.OperationalError:
    print("'views' column already exists.")

try:
    # Adding 'earnings' column if it doesn't exist
    cursor.execute("ALTER TABLE submissions ADD COLUMN earnings REAL DEFAULT 0.0")
    print("Added 'earnings' column successfully.")
except sqlite3.OperationalError:
    print("'earnings' column already exists.")

conn.commit()
conn.close()
