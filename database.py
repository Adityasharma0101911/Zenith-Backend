# import sqlite3 to work with the database
import sqlite3

# this function creates a connection to the zenith database
def get_db_connection():
    # connect to the zenith.db file
    conn = sqlite3.connect("zenith.db")

    # set row_factory so we can access columns by name instead of index
    conn.row_factory = sqlite3.Row

    # return the connection so other parts of the app can use it
    return conn

# creates the main user table
def init_db():
    # get a connection to the database
    conn = get_db_connection()

    # create the users table if it doesn't already exist
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL,
            balance REAL DEFAULT 0.0
        )
    """)

    # save the changes to the database
    conn.commit()

    # close the connection
    conn.close()

# run init_db when this file is imported so the table is always ready
init_db()
