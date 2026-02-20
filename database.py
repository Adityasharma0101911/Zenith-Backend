# import sqlite3 to work with the database
import sqlite3
import os

# database file lives next to this script
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "zenith.db")

# this function creates a connection to the zenith database
def get_db_connection():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
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

    # caches ai briefs so we don't re-request every page load
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ai_briefs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            section TEXT,
            brief TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, section)
        )
    """)

    # stores daily stress levels for the calendar heatmap
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pulse_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            stress_level INTEGER,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # add new columns if upgrading from old schema
    for col in ["survey_data TEXT", "token TEXT", "name TEXT", "spending_profile TEXT", "balance REAL DEFAULT 0.0", "stress_level INTEGER DEFAULT 1"]:
        try:
            conn.execute(f"ALTER TABLE users ADD COLUMN {col}")
        except Exception:
            pass

    conn.commit()
    conn.close()
