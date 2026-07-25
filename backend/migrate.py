"""Apply SQLite schema migrations for the voice clone app."""
import database as db


if __name__ == "__main__":
    db.init_db()
    print("Migration complete")
