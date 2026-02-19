# import sqlite3 to work with the database
import sqlite3

# this function creates a connection to the zenith database
def get_db_connection():
    conn = sqlite3.connect("zenith.db")
    conn.row_factory = sqlite3.Row
    return conn

# creates all the tables the app needs
def init_db():
    conn = get_db_connection()

    # users table with survey data column
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL,
            token TEXT,
            name TEXT,
            spending_profile TEXT,
            balance REAL DEFAULT 0.0,
            stress_level INTEGER DEFAULT 1,
            survey_data TEXT
        )
    """)

    # purchase ledger
    conn.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            item_name TEXT,
            amount REAL,
            status TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # stores backboard assistant ids per section
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ai_assistants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE,
            assistant_id TEXT
        )
    """)

    # stores per-user thread ids for each ai section
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_threads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            assistant_name TEXT,
            thread_id TEXT,
            initialized INTEGER DEFAULT 0,
            UNIQUE(user_id, assistant_name)
        )
    """)

    # add survey_data column if upgrading from old schema
    try:
        conn.execute("ALTER TABLE users ADD COLUMN survey_data TEXT")
    except Exception:
        pass

    conn.commit()
    conn.close()

# run init_db when this file is imported
init_db()
