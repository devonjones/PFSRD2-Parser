import json


def create_traits_table(curs):
    sql = '\n'.join([
        "CREATE TABLE traits (",
        "  trait_id INTEGER PRIMARY KEY,",
        "  game_id TEXT NOT NULL UNIQUE,",
        "  name TEXT NOT NULL,",
        "  classes TEXT,",
        "  edition TEXT,",
        "  trait TEXT"
        ")"])
    curs.execute(sql)


def create_traits_index(curs):
    sql = '\n'.join([
        "CREATE INDEX traits_game_id",
        " ON traits (game_id)"])
    curs.execute(sql)


def create_trait_link_table(curs):
    sql = '\n'.join([
        "CREATE TABLE trait_links (",
        "  legacy_trait_id INTEGER,",
        "  remastered_trait_id INTEGER,",
        "  PRIMARY KEY (legacy_trait_id, remastered_trait_id)",
        ")"])
    curs.execute(sql)


def create_trait_link_index(curs):
    sql = '\n'.join([
        "CREATE INDEX trait_links_legacy_trait_id",
        " ON trait_links (legacy_trait_id)"])
    curs.execute(sql)


def truncate_traits(curs):
    sql = '\n'.join([
        "DELETE FROM traits"])
    curs.execute(sql)


def insert_trait(curs, trait):
    text = json.dumps(trait)
    values = [trait['game-id'], trait['name'].lower(),
              json.dumps(trait.get('classes', [])), trait['edition'], text]
    sql = '\n'.join([
        "INSERT INTO traits",
        " (game_id, name, classes, edition, trait)",
        " VALUES",
        " (?, ?, ?, ?, ?)"])
    curs.execute(sql, values)
    return curs.lastrowid


def fetch_trait(curs, game_id):
    values = [game_id]
    sql = '\n'.join([
        "SELECT *",
        " FROM traits",
        " WHERE game_id = ?"])
    curs.execute(sql, values)


def fetch_trait_by_name(curs, name):
    values = [name.lower()]
    sql = '\n'.join([
        "SELECT t.*",
        " FROM traits t",
        " WHERE t.name = ?"])
    curs.execute(sql, values)


def fetch_trait_by_id(curs, trait_id):
    sql = '\n'.join([
        "SELECT *",
        " FROM traits",
        " WHERE trait_id = ?"
    ])
    curs.execute(sql, (trait_id,))
    return curs.fetchone()


def fetch_trait_by_aonid(curs, aonid):
    sql = '\n'.join([
        "SELECT t.*",
        " FROM traits t",
        " JOIN trait_link_cache tlc ON t.trait_id = tlc.trait_id",
        " WHERE tlc.trait_aonid = ?"
    ])
    curs.execute(sql, (aonid,))
    return curs.fetchone()


def insert_trait_link(curs, legacy_trait_id, remastered_trait_id):
    sql = '\n'.join([
        "INSERT OR IGNORE INTO trait_links (legacy_trait_id, remastered_trait_id)",
        "VALUES (?, ?)"
    ])
    curs.execute(sql, (legacy_trait_id, remastered_trait_id))


def drop_trait_link_cache(curs):
    sql = 'DROP TABLE IF EXISTS trait_link_cache'
    curs.execute(sql)