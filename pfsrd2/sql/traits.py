import json

from universal.universal import test_key_is_value, walk

# Expected schema versions for nested objects pulled from the database.
# When we embed DB objects (traits, monster abilities) inside other structures,
# we validate their schema_version matches what we expect, then strip it —
# schema_version is reserved for the top-level document only.
EXPECTED_TRAIT_SCHEMA_VERSION = 1.1


def strip_nested_metadata(db_obj, expected_version):
    """Validate and strip schema_version from a DB object embedded in another structure.

    Schema_version is reserved for top-level documents. Nested objects pulled from
    the database have their own schema_version which we validate matches expectations,
    then remove. License is kept so license_consolidation_pass can merge it into
    the top-level license.
    """
    actual = db_obj.get("schema_version")
    assert actual == expected_version, (
        f"Nested object '{db_obj.get('name')}' has schema_version {actual}, "
        f"expected {expected_version}"
    )
    del db_obj["schema_version"]


def trait_db_pass(struct, pre_process=None, edition_required=True):
    """Enrich minimal trait objects with full trait data from database.

    Walks the struct finding all objects with subtype=="trait", looks up
    each in the database, and replaces the minimal trait with the full
    database version (including classes, sources, edition, etc.).

    Args:
        struct: The parsed structure to walk.
        pre_process: Optional function(trait, parent, curs) called before DB
            lookup. Use for parser-specific logic like value extraction,
            alignment splitting, or name fixes. The curs parameter allows
            DB lookups in pre-processing (e.g., splitting alignment traits).
            If it returns True, the trait is considered fully handled and the
            default DB replacement is skipped.
        edition_required: If True (default), assert that struct has 'edition'
            set before doing edition matching. Set to False for parsers like
            monster_ability that legitimately lack edition.
    """
    from pfsrd2.sql import get_db_connection, get_db_path

    def _merge_classes(trait, db_trait):
        trait_classes = set(trait.get("classes", []))
        db_trait_classes = set(db_trait.get("classes", []))
        merged = sorted(trait_classes | db_trait_classes)
        if merged:
            db_trait["classes"] = merged
        else:
            db_trait.pop("classes", None)

    def _handle_trait_link(db_trait):
        trait = json.loads(db_trait["trait"])
        edition = trait["edition"]
        if not edition_required and "edition" not in struct:
            return trait
        if edition_required:
            assert "edition" in struct, (
                f"struct missing 'edition' but edition_required=True " f"(trait: {trait['name']})"
            )
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
        if pre_process and pre_process(trait, parent, curs):
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
        strip_nested_metadata(db_trait, EXPECTED_TRAIT_SCHEMA_VERSION)
        if "classes" in db_trait:
            db_trait["classes"].sort()
        parent[index] = db_trait

    db_path = get_db_path("pfsrd2.db")
    with get_db_connection(db_path) as conn:
        curs = conn.cursor()
        walk(struct, test_key_is_value("subtype", "trait"), _check_trait)


def create_traits_table(curs):
    sql = """
CREATE TABLE traits (
  trait_id INTEGER PRIMARY KEY,
  game_id TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  classes TEXT,
  edition TEXT,
  trait TEXT)
"""
    curs.execute(sql)


def create_traits_index(curs):
    sql = """
CREATE INDEX traits_game_id
 ON traits (game_id)
"""
    curs.execute(sql)


def create_trait_link_table(curs):
    sql = """
CREATE TABLE trait_links (
  legacy_trait_id INTEGER,
  remastered_trait_id INTEGER,
  PRIMARY KEY (legacy_trait_id, remastered_trait_id)
)
"""
    curs.execute(sql)


def create_trait_link_index(curs):
    sql = """
CREATE INDEX trait_links_legacy_trait_id
 ON trait_links (legacy_trait_id)
"""
    curs.execute(sql)


def truncate_traits(curs):
    sql = "DELETE FROM traits"
    curs.execute(sql)


def truncate_trait_links(curs):
    sql = "DELETE FROM trait_links"
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
    sql = """
INSERT INTO traits
 (game_id, name, classes, edition, trait)
 VALUES
 (?, ?, ?, ?, ?)
"""
    curs.execute(sql, values)
    return curs.lastrowid


def fetch_trait(curs, game_id):
    values = [game_id]
    sql = """
SELECT *
 FROM traits
 WHERE game_id = ?
"""
    curs.execute(sql, values)
    return curs.fetchone()


def fetch_trait_by_name(curs, name):
    values = [name.lower()]
    sql = """
SELECT t.*
 FROM traits t
 WHERE t.name = ?
"""
    curs.execute(sql, values)
    return curs.fetchone()


def fetch_trait_by_id(curs, trait_id):
    sql = """
SELECT *
 FROM traits
 WHERE trait_id = ?
"""
    curs.execute(sql, (trait_id,))
    return curs.fetchone()


def fetch_trait_by_aonid(curs, aonid):
    sql = """
SELECT t.*
 FROM traits t
 JOIN trait_link_cache tlc ON t.trait_id = tlc.trait_id
 WHERE tlc.trait_aonid = ?
"""
    curs.execute(sql, (aonid,))
    return curs.fetchone()


def fetch_trait_by_link(curs, legacy_trait_id=None, remastered_trait_id=None):
    if legacy_trait_id:
        sql = """
SELECT t.*
 FROM traits t
 JOIN trait_links tl ON t.trait_id = tl.remastered_trait_id
 WHERE tl.legacy_trait_id = ?
"""
        curs.execute(sql, (legacy_trait_id,))
    elif remastered_trait_id:
        sql = """
SELECT t.*
 FROM traits t
 JOIN trait_links tl ON t.trait_id = tl.legacy_trait_id
 WHERE tl.remastered_trait_id = ?
"""
        curs.execute(sql, (remastered_trait_id,))
    else:
        raise ValueError("Either legacy_trait_id or remastered_trait_id must be provided")
    return curs.fetchone()


def insert_trait_link(curs, legacy_trait_id, remastered_trait_id):
    sql = """
INSERT OR IGNORE INTO trait_links (legacy_trait_id, remastered_trait_id)
VALUES (?, ?)
"""
    curs.execute(sql, (legacy_trait_id, remastered_trait_id))


def drop_trait_link_cache(curs):
    sql = "DROP TABLE IF EXISTS trait_link_cache"
    curs.execute(sql)
