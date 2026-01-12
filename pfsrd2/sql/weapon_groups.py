import json


def create_weapon_groups_table(curs):
    sql = '\n'.join([
        "CREATE TABLE weapon_groups (",
        "  weapon_group_id INTEGER PRIMARY KEY,",
        "  game_id TEXT NOT NULL UNIQUE,",
        "  name TEXT NOT NULL,",
        "  edition TEXT,",
        "  weapon_group TEXT"
        ")"])
    curs.execute(sql)


def create_weapon_groups_index(curs):
    sql = '\n'.join([
        "CREATE INDEX weapon_groups_game_id",
        " ON weapon_groups (game_id)"])
    curs.execute(sql)


def truncate_weapon_groups(curs):
    sql = '\n'.join([
        "DELETE FROM weapon_groups"])
    curs.execute(sql)


def insert_weapon_group(curs, weapon_group):
    text = json.dumps(weapon_group)
    values = [weapon_group['game-id'], weapon_group['name'].lower(),
              weapon_group['edition'], text]
    sql = '\n'.join([
        "INSERT INTO weapon_groups",
        " (game_id, name, edition, weapon_group)",
        " VALUES",
        " (?, ?, ?, ?)"])
    curs.execute(sql, values)
    return curs.lastrowid


def fetch_weapon_group_by_name(curs, name):
    values = [name.lower()]
    sql = '\n'.join([
        "SELECT wg.*",
        " FROM weapon_groups wg",
        " WHERE wg.name = ?"])
    curs.execute(sql, values)


def fetch_weapon_group_by_game_id(curs, game_id):
    values = [game_id]
    sql = '\n'.join([
        "SELECT *",
        " FROM weapon_groups",
        " WHERE game_id = ?"])
    curs.execute(sql, values)
