import json


def create_traits_table(curs):
    sql = '\n'.join([
        "CREATE TABLE traits (",
        "  trait_id INTEGER PRIMARY KEY,",
        "  game_id TEXT NOT NULL UNIQUE,",
        "  name TEXT NOT NULL,",
        "  classes TEXT,",
        "  trait TEXT"
        ")"])
    curs.execute(sql)


def create_traits_index(curs):
    sql = '\n'.join([
        "CREATE INDEX traits_game_id",
        " ON traits (game_id)"])
    curs.execute(sql)


def truncate_traits(curs):
    sql = '\n'.join([
        "DELETE FROM traits"])
    curs.execute(sql)


def insert_trait(curs, trait):
    text = json.dumps(trait)
    values = [trait['game-id'], trait['name'].lower(),
              json.dumps(trait.get('classes', [])), text]
    sql = '\n'.join([
        "INSERT INTO traits",
        " (game_id, name, classes, trait)",
        " VALUES",
        " (?, ?, ?, ?)"])
    curs.execute(sql, values)


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
