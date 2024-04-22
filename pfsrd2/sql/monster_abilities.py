import json


def create_monster_abilities_table(curs):
    sql = '\n'.join([
        "CREATE TABLE monster_abilities (",
        "  monster_abilities_id INTEGER PRIMARY KEY,",
        "  game_id TEXT NOT NULL UNIQUE,",
        "  name TEXT NOT NULL,",
        "  classes TEXT,",
        "  monster_ability TEXT"
        ")"])
    curs.execute(sql)


def create_monster_abilities_index(curs):
    sql = '\n'.join([
        "CREATE INDEX monster_abilities_game_id",
        " ON monster_abilities (game_id)"])
    curs.execute(sql)


def truncate_monster_abilities(curs):
    sql = '\n'.join([
        "DELETE FROM monster_abilities"])
    curs.execute(sql)


def insert_monster_ability(curs, monster_ability):
    text = json.dumps(monster_ability)
    values = [monster_ability['game-id'], monster_ability['name'].lower(),
              json.dumps(monster_ability.get('classes', [])), text]
    sql = '\n'.join([
        "INSERT INTO monster_abilities",
        " (game_id, name, classes, monster_ability)",
        " VALUES",
        " (?, ?, ?, ?)"])
    curs.execute(sql, values)


def fetch_monster_ability(curs, game_id):
    values = [game_id]
    sql = '\n'.join([
        "SELECT *",
        " FROM monster_abilities",
        " WHERE game_id = ?"])
    curs.execute(sql, values)


def fetch_monster_ability_by_name(curs, name):
    values = [name.lower()]
    sql = '\n'.join([
        "SELECT ma.*",
        " FROM monster_abilities ma",
        " WHERE ma.name = ?"])
    curs.execute(sql, values)
