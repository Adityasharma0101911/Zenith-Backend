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
