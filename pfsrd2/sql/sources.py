import json


def set_edition_from_db_pass(struct):
    """Set struct edition based on source book edition from DB."""
    from pfsrd2.sql import get_db_connection, get_db_path

    db_path = get_db_path("pfsrd2.db")
    with get_db_connection(db_path) as conn:
        curs = conn.cursor()
        for source in struct.get("sources", []):
            fetch_source_by_name(curs, source["name"])
            row = curs.fetchone()
            if row and row.get("edition"):
                struct["edition"] = row["edition"]
                return
    assert "edition" in struct, (
        f"set_edition_from_db_pass: could not resolve edition from sources "
        f"{[s.get('name') for s in struct.get('sources', [])]}"
    )


def create_sources_table(curs):
    sql = """
CREATE TABLE sources (
  source_id INTEGER PRIMARY KEY,
  game_id TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  edition TEXT,
  license TEXT
)
"""
    curs.execute(sql)


def create_sources_index(curs):
    sql = """
CREATE INDEX sources_game_id
 ON sources (game_id)
"""
    curs.execute(sql)


def truncate_sources(curs):
    sql = "DELETE FROM sources"
    curs.execute(sql)


def insert_source(curs, source):
    text = json.dumps(source["license"])
    values = [source["game-id"], source["name"], source.get("edition"), text]
    sql = """
INSERT INTO sources
 (game_id, name, edition, license)
 VALUES
 (?, ?, ?, ?)
"""
    curs.execute(sql, values)
    return curs.lastrowid


def fetch_source(curs, game_id):
    values = [game_id]
    sql = """
SELECT *
 FROM sources
 WHERE game_id = ?
"""
    curs.execute(sql, values)


def fetch_source_by_name(curs, name):
    values = [name]
    sql = """
SELECT s.*
 FROM sources s
 WHERE s.name = ?
"""
    curs.execute(sql, values)
