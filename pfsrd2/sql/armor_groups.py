import json


def create_armor_groups_table(curs):
    sql = """
CREATE TABLE armor_groups (
  armor_group_id INTEGER PRIMARY KEY,
  game_id TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  edition TEXT,
  armor_group TEXT)
"""
    curs.execute(sql)


def create_armor_groups_index(curs):
    sql = """
CREATE INDEX armor_groups_game_id
 ON armor_groups (game_id)
"""
    curs.execute(sql)


def truncate_armor_groups(curs):
    sql = "DELETE FROM armor_groups"
    curs.execute(sql)


def insert_armor_group(curs, armor_group):
    text = json.dumps(armor_group)
    values = [armor_group["game-id"], armor_group["name"].lower(), armor_group["edition"], text]
    sql = """
INSERT INTO armor_groups
 (game_id, name, edition, armor_group)
 VALUES
 (?, ?, ?, ?)
"""
    curs.execute(sql, values)
    return curs.lastrowid


def fetch_armor_group_by_name(curs, name):
    values = [name.lower()]
    sql = """
SELECT ag.*
 FROM armor_groups ag
 WHERE ag.name = ?
"""
    curs.execute(sql, values)


def fetch_armor_group_by_game_id(curs, game_id):
    values = [game_id]
    sql = """
SELECT *
 FROM armor_groups
 WHERE game_id = ?
"""
    curs.execute(sql, values)
