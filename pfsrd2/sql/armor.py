import json


def create_armor_table(curs):
    sql = '\n'.join([
        "CREATE TABLE armor (",
        "  armor_id INTEGER PRIMARY KEY,",
        "  game_id TEXT NOT NULL UNIQUE,",
        "  name TEXT NOT NULL,",
        "  aonid INTEGER NOT NULL,",
        "  category TEXT,",
        "  armor_group TEXT,",
        "  armor TEXT"
        ")"])
    curs.execute(sql)


def create_armor_index(curs):
    sql = '\n'.join([
        "CREATE INDEX armor_game_id",
        " ON armor (game_id)"])
    curs.execute(sql)


def create_armor_aonid_index(curs):
    sql = '\n'.join([
        "CREATE INDEX armor_aonid",
        " ON armor (aonid)"])
    curs.execute(sql)


def create_armor_category_index(curs):
    sql = '\n'.join([
        "CREATE INDEX armor_category",
        " ON armor (category)"])
    curs.execute(sql)


def truncate_armor(curs):
    sql = '\n'.join([
        "DELETE FROM armor"])
    curs.execute(sql)


def insert_armor(curs, armor):
    text = json.dumps(armor)
    stat_block = armor.get('stat_block', {})
    values = [
        armor['game-id'],
        armor['name'].lower(),
        armor['aonid'],
        stat_block.get('category'),
        stat_block.get('group'),
        text
    ]
    sql = '\n'.join([
        "INSERT INTO armor",
        " (game_id, name, aonid, category, armor_group, armor)",
        " VALUES",
        " (?, ?, ?, ?, ?, ?)"])
    curs.execute(sql, values)
    return curs.lastrowid


def fetch_armor(curs, game_id):
    values = [game_id]
    sql = '\n'.join([
        "SELECT *",
        " FROM armor",
        " WHERE game_id = ?"])
    curs.execute(sql, values)
    return curs.fetchone()


def fetch_armor_by_name(curs, name):
    values = [name.lower()]
    sql = '\n'.join([
        "SELECT a.*",
        " FROM armor a",
        " WHERE a.name = ?"])
    curs.execute(sql, values)
    return curs.fetchone()


def fetch_armor_by_id(curs, armor_id):
    sql = '\n'.join([
        "SELECT *",
        " FROM armor",
        " WHERE armor_id = ?"
    ])
    curs.execute(sql, (armor_id,))
    return curs.fetchone()


def fetch_armor_by_aonid(curs, aonid):
    sql = '\n'.join([
        "SELECT a.*",
        " FROM armor a",
        " WHERE a.aonid = ?"
    ])
    curs.execute(sql, (aonid,))
    return curs.fetchone()


def fetch_armor_by_category(curs, category):
    sql = '\n'.join([
        "SELECT a.*",
        " FROM armor a",
        " WHERE a.category = ?"
    ])
    curs.execute(sql, (category,))
    return curs.fetchall()


def fetch_armor_by_group(curs, group):
    sql = '\n'.join([
        "SELECT a.*",
        " FROM armor a",
        " WHERE a.armor_group = ?"
    ])
    curs.execute(sql, (group,))
    return curs.fetchall()
