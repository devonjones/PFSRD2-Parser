import json


def create_monster_families_table(curs):
    sql = """
CREATE TABLE monster_families (
  monster_family_id INTEGER PRIMARY KEY,
  game_id TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  aonid INTEGER NOT NULL,
  edition TEXT,
  monster_family TEXT
)
"""
    curs.execute(sql)


def create_monster_families_index(curs):
    sql = """
CREATE INDEX monster_families_game_id
 ON monster_families (game_id)
"""
    curs.execute(sql)


def create_monster_families_aonid_index(curs):
    sql = """
CREATE INDEX monster_families_aonid
 ON monster_families (aonid)
"""
    curs.execute(sql)


def create_monster_families_name_index(curs):
    sql = """
CREATE INDEX monster_families_name
 ON monster_families (name)
"""
    curs.execute(sql)


def create_monster_family_link_table(curs):
    sql = """
CREATE TABLE monster_family_links (
  legacy_monster_family_id INTEGER,
  remastered_monster_family_id INTEGER,
  PRIMARY KEY (legacy_monster_family_id, remastered_monster_family_id)
)
"""
    curs.execute(sql)


def create_monster_family_link_index(curs):
    sql = """
CREATE INDEX monster_family_links_legacy
 ON monster_family_links (legacy_monster_family_id)
"""
    curs.execute(sql)


def truncate_monster_families(curs):
    sql = "DELETE FROM monster_families"
    curs.execute(sql)


def truncate_monster_family_links(curs):
    sql = "DELETE FROM monster_family_links"
    curs.execute(sql)


def insert_monster_family(curs, family):
    text = json.dumps(family)
    values = [
        family["game-id"],
        family["name"].lower(),
        family["aonid"],
        family.get("edition"),
        text,
    ]
    sql = """
INSERT INTO monster_families
 (game_id, name, aonid, edition, monster_family)
 VALUES
 (?, ?, ?, ?, ?)
"""
    curs.execute(sql, values)
    return curs.lastrowid


def fetch_monster_family(curs, game_id):
    sql = """
SELECT *
 FROM monster_families
 WHERE game_id = ?
"""
    curs.execute(sql, (game_id,))
    return curs.fetchone()


def fetch_monster_family_by_name(curs, name):
    sql = """
SELECT *
 FROM monster_families
 WHERE name = ?
"""
    curs.execute(sql, (name.lower(),))
    return curs.fetchone()


def fetch_monster_family_by_id(curs, monster_family_id):
    sql = """
SELECT *
 FROM monster_families
 WHERE monster_family_id = ?
"""
    curs.execute(sql, (monster_family_id,))
    return curs.fetchone()


def fetch_monster_family_by_aonid(curs, aonid):
    sql = """
SELECT *
 FROM monster_families
 WHERE aonid = ?
"""
    curs.execute(sql, (aonid,))
    return curs.fetchone()


def fetch_monster_family_by_link(
    curs, legacy_monster_family_id=None, remastered_monster_family_id=None
):
    if legacy_monster_family_id:
        sql = """
SELECT mf.*
 FROM monster_families mf
 JOIN monster_family_links mfl
   ON mf.monster_family_id = mfl.remastered_monster_family_id
 WHERE mfl.legacy_monster_family_id = ?
"""
        curs.execute(sql, (legacy_monster_family_id,))
    elif remastered_monster_family_id:
        sql = """
SELECT mf.*
 FROM monster_families mf
 JOIN monster_family_links mfl
   ON mf.monster_family_id = mfl.legacy_monster_family_id
 WHERE mfl.remastered_monster_family_id = ?
"""
        curs.execute(sql, (remastered_monster_family_id,))
    else:
        raise ValueError(
            "Either legacy_monster_family_id or remastered_monster_family_id must be provided"
        )
    return curs.fetchone()


def insert_monster_family_link(curs, legacy_monster_family_id, remastered_monster_family_id):
    sql = """
INSERT OR IGNORE INTO monster_family_links
 (legacy_monster_family_id, remastered_monster_family_id)
 VALUES (?, ?)
"""
    curs.execute(sql, (legacy_monster_family_id, remastered_monster_family_id))
