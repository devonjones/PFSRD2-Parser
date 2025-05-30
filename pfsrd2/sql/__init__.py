import os
import sqlite3
from pfsrd2.sql.traits import create_traits_table, create_traits_index
from pfsrd2.sql.traits import create_trait_link_table, create_trait_link_index
from pfsrd2.sql.monster_abilities import create_monster_abilities_table, create_monster_abilities_index
from pfsrd2.sql.sources import create_sources_table, create_sources_index


def get_db_path(db_name):
    path = os.path.expanduser("~/.pfsrd2")
    if not os.path.exists(path):
        os.makedirs(path)
    return os.path.abspath(path + "/" + db_name)


def create_db(db_path, replace=False):
    if os.path.exists(db_path) and replace:
        os.remove(db_path)
    return get_db_connection(db_path)


def check_db_version(curs):
    sql = "".join([
        "SELECT MAX(version)",
        " FROM database_version"])
    curs.execute(sql)
    row = curs.fetchone()
    return row[0]


def set_version(curs, ver):
    sql = "".join([
        "INSERT INTO database_version",
        " (version)", " VALUES (?)"])
    curs.execute(sql, (str(ver),))


def create_db_v_1(conn, curs):
    sql = "".join([
        "CREATE TABLE IF NOT EXISTS database_version(",
        "  id INTEGER PRIMARY KEY,",
        "  version INTEGER)",
    ]
    )
    curs.execute(sql)
    ver = check_db_version(curs)
    if not ver:
        ver = 1
        set_version(curs, ver)
    conn.commit()
    return ver


def create_db_v_2(conn, curs, ver, source=None):
    if ver >= 2:
        return ver
    ver = 2
    create_traits_table(curs)
    create_traits_index(curs)
    set_version(curs, ver)
    conn.commit()
    return ver


def create_db_v_3(conn, curs, ver, source=None):
    if ver >= 3:
        return ver
    ver = 3
    create_monster_abilities_table(curs)
    create_monster_abilities_index(curs)
    set_version(curs, ver)
    conn.commit()
    return ver


def create_db_v_4(conn, curs, ver, source=None):
    if ver >= 4:
        return ver
    ver = 4
    create_trait_link_table(curs)
    create_trait_link_index(curs)
    set_version(curs, ver)
    conn.commit()
    return ver


def create_db_v_5(conn, curs, ver, source=None):
    if ver >= 5:
        return ver
    ver = 5
    create_sources_table(curs)
    create_sources_index(curs)
    set_version(curs, ver)
    conn.commit()
    return ver


def dict_factory(cursor, row):
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d


def get_db_connection(db, source=None):
    conn = sqlite3.connect(os.path.expanduser(db))
    curs = conn.cursor()
    try:
        ver = create_db_v_1(conn, curs)
        ver = create_db_v_2(conn, curs, ver, source)
        ver = create_db_v_3(conn, curs, ver, source)
        ver = create_db_v_4(conn, curs, ver, source)
        ver = create_db_v_5(conn, curs, ver, source)
    finally:
        curs.close()
    conn.row_factory = dict_factory
    return conn
