import json

from universal.universal import test_key_is_value, walk


def trait_db_pass(struct, pre_process=None):
    """Enrich minimal trait objects with full trait data from database.

    Walks the struct finding all objects with subtype=="trait", looks up
    each in the database, and replaces the minimal trait with the full
    database version (including classes, sources, edition, etc.).

    Args:
        struct: The parsed structure to walk.
        pre_process: Optional function(trait, parent) called before DB lookup.
            Use for parser-specific logic like value extraction, alignment
            splitting, or name fixes. If it returns True, the trait is
            considered fully handled and the default DB replacement is skipped.
    """
    from pfsrd2.sql import get_db_connection, get_db_path

    def _merge_classes(trait, db_trait):
        trait_classes = set(trait.get("classes", []))
        db_trait_classes = set(db_trait.get("classes", []))
        db_trait["classes"] = sorted(trait_classes | db_trait_classes)

    def _handle_trait_link(db_trait):
        trait = json.loads(db_trait["trait"])
        edition = trait["edition"]
        if edition == struct["edition"]:
            return trait
        if "alternate_link" not in trait:
            return trait
        kwargs = {}
        if edition == "legacy":
            kwargs["legacy_trait_id"] = db_trait["trait_id"]
        else:
            kwargs["remastered_trait_id"] = db_trait["trait_id"]
        data = fetch_trait_by_link(curs, **kwargs)
        assert (
            data
        ), f"Trait has alternate_link but linked trait not found in DB: {trait['name']} (id={db_trait['trait_id']})"
        return json.loads(data["trait"])

    def _check_trait(trait, parent):
        if pre_process and pre_process(trait, parent):
            return
        data = fetch_trait_by_name(curs, trait["name"])
        assert data, f"Trait not found in database: {trait}"
        db_trait = _handle_trait_link(data)
        _merge_classes(trait, db_trait)
        assert isinstance(parent, list), parent
        index = parent.index(trait)
        if "value" in trait:
            db_trait["value"] = trait["value"]
        if "aonid" in db_trait:
            del db_trait["aonid"]
        if "license" in db_trait:
            del db_trait["license"]
        parent[index] = db_trait

    db_path = get_db_path("pfsrd2.db")
    conn = get_db_connection(db_path)
    curs = conn.cursor()
    walk(struct, test_key_is_value("subtype", "trait"), _check_trait)
    conn.close()


def create_traits_table(curs):
    sql = "\n".join(
        [
            "CREATE TABLE traits (",
            "  trait_id INTEGER PRIMARY KEY,",
            "  game_id TEXT NOT NULL UNIQUE,",
            "  name TEXT NOT NULL,",
            "  classes TEXT,",
            "  edition TEXT,",
            "  trait TEXT" ")",
        ]
    )
    curs.execute(sql)


def create_traits_index(curs):
    sql = "\n".join(["CREATE INDEX traits_game_id", " ON traits (game_id)"])
    curs.execute(sql)


def create_trait_link_table(curs):
    sql = "\n".join(
        [
            "CREATE TABLE trait_links (",
            "  legacy_trait_id INTEGER,",
            "  remastered_trait_id INTEGER,",
            "  PRIMARY KEY (legacy_trait_id, remastered_trait_id)",
            ")",
        ]
    )
    curs.execute(sql)


def create_trait_link_index(curs):
    sql = "\n".join(
        ["CREATE INDEX trait_links_legacy_trait_id", " ON trait_links (legacy_trait_id)"]
    )
    curs.execute(sql)


def truncate_traits(curs):
    sql = "\n".join(["DELETE FROM traits"])
    curs.execute(sql)


def truncate_trait_links(curs):
    sql = "\n".join(["DELETE FROM trait_links"])
    curs.execute(sql)


def insert_trait(curs, trait):
    text = json.dumps(trait)
    values = [
        trait["game-id"],
        trait["name"].lower(),
        json.dumps(trait.get("classes", [])),
        trait["edition"],
        text,
    ]
    sql = "\n".join(
        [
            "INSERT INTO traits",
            " (game_id, name, classes, edition, trait)",
            " VALUES",
            " (?, ?, ?, ?, ?)",
        ]
    )
    curs.execute(sql, values)
    return curs.lastrowid


def fetch_trait(curs, game_id):
    values = [game_id]
    sql = "\n".join(["SELECT *", " FROM traits", " WHERE game_id = ?"])
    curs.execute(sql, values)
    return curs.fetchone()


def fetch_trait_by_name(curs, name):
    values = [name.lower()]
    sql = "\n".join(["SELECT t.*", " FROM traits t", " WHERE t.name = ?"])
    curs.execute(sql, values)
    return curs.fetchone()


def fetch_trait_by_id(curs, trait_id):
    sql = "\n".join(["SELECT *", " FROM traits", " WHERE trait_id = ?"])
    curs.execute(sql, (trait_id,))
    return curs.fetchone()


def fetch_trait_by_aonid(curs, aonid):
    sql = "\n".join(
        [
            "SELECT t.*",
            " FROM traits t",
            " JOIN trait_link_cache tlc ON t.trait_id = tlc.trait_id",
            " WHERE tlc.trait_aonid = ?",
        ]
    )
    curs.execute(sql, (aonid,))
    return curs.fetchone()


def fetch_trait_by_link(curs, legacy_trait_id=None, remastered_trait_id=None):
    if legacy_trait_id:
        sql = "\n".join(
            [
                "SELECT t.*",
                " FROM traits t",
                " JOIN trait_links tl ON t.trait_id = tl.remastered_trait_id",
                " WHERE tl.legacy_trait_id = ?",
            ]
        )
        curs.execute(sql, (legacy_trait_id,))
    elif remastered_trait_id:
        sql = "\n".join(
            [
                "SELECT t.*",
                " FROM traits t",
                " JOIN trait_links tl ON t.trait_id = tl.legacy_trait_id",
                " WHERE tl.remastered_trait_id = ?",
            ]
        )
        curs.execute(sql, (remastered_trait_id,))
    else:
        raise ValueError("Either legacy_trait_id or remastered_trait_id must be provided")
    return curs.fetchone()


def insert_trait_link(curs, legacy_trait_id, remastered_trait_id):
    sql = "\n".join(
        [
            "INSERT OR IGNORE INTO trait_links (legacy_trait_id, remastered_trait_id)",
            "VALUES (?, ?)",
        ]
    )
    curs.execute(sql, (legacy_trait_id, remastered_trait_id))


def drop_trait_link_cache(curs):
    sql = "DROP TABLE IF EXISTS trait_link_cache"
    curs.execute(sql)
