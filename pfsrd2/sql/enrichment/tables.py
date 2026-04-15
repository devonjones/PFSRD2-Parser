"""Table and index creation for the enrichment database."""


def create_ability_records_table(curs):
    sql = "\n".join(
        [
            "CREATE TABLE ability_records (",
            "  ability_id INTEGER PRIMARY KEY,",
            "  name TEXT NOT NULL,",
            "  identity_hash TEXT NOT NULL UNIQUE,",
            "  raw_json TEXT NOT NULL,",
            "  enriched_json TEXT,",
            "  enrichment_version INTEGER,",
            "  extraction_method TEXT,",
            "  human_verified INTEGER DEFAULT 0,",
            "  stale INTEGER DEFAULT 0,",
            "  created_at TEXT NOT NULL,",
            "  updated_at TEXT NOT NULL",
            ")",
        ]
    )
    curs.execute(sql)


def create_ability_records_index(curs):
    curs.execute("CREATE INDEX ability_records_identity_hash" " ON ability_records (identity_hash)")
    curs.execute("CREATE INDEX ability_records_name" " ON ability_records (name)")
    curs.execute("CREATE INDEX ability_records_stale" " ON ability_records (stale)")
    curs.execute(
        "CREATE INDEX ability_records_enrichment_version" " ON ability_records (enrichment_version)"
    )


def create_ability_creature_links_table(curs):
    sql = "\n".join(
        [
            "CREATE TABLE ability_creature_links (",
            "  link_id INTEGER PRIMARY KEY,",
            "  ability_id INTEGER NOT NULL,",
            "  creature_game_id TEXT NOT NULL,",
            "  creature_name TEXT NOT NULL,",
            "  creature_level INTEGER,",
            "  creature_traits TEXT,",
            "  source_name TEXT,",
            "  ability_category TEXT NOT NULL,",
            "  FOREIGN KEY (ability_id) REFERENCES ability_records(ability_id),",
            "  UNIQUE(ability_id, creature_game_id)",
            ")",
        ]
    )
    curs.execute(sql)


def create_ability_creature_links_index(curs):
    curs.execute(
        "CREATE INDEX ability_creature_links_ability_id" " ON ability_creature_links (ability_id)"
    )
    curs.execute(
        "CREATE INDEX ability_creature_links_creature_game_id"
        " ON ability_creature_links (creature_game_id)"
    )


# --- Change records (template/family rule enrichment) ---


def create_change_records_table(curs):
    sql = "\n".join(
        [
            "CREATE TABLE change_records (",
            "  change_id INTEGER PRIMARY KEY,",
            "  source_name TEXT NOT NULL,",
            "  source_type TEXT NOT NULL,",
            "  identity_hash TEXT NOT NULL UNIQUE,",
            "  raw_json TEXT NOT NULL,",
            "  enriched_json TEXT,",
            "  enrichment_version INTEGER,",
            "  extraction_method TEXT,",
            "  human_verified INTEGER DEFAULT 0,",
            "  needs_review INTEGER DEFAULT 0,",
            "  review_reason TEXT,",
            "  stale INTEGER DEFAULT 0,",
            "  created_at TEXT NOT NULL,",
            "  updated_at TEXT NOT NULL",
            ")",
        ]
    )
    curs.execute(sql)


def create_change_records_index(curs):
    curs.execute("CREATE INDEX change_records_identity_hash ON change_records (identity_hash)")
    curs.execute("CREATE INDEX change_records_source_name ON change_records (source_name)")
    curs.execute("CREATE INDEX change_records_source_type ON change_records (source_type)")
    curs.execute("CREATE INDEX change_records_stale ON change_records (stale)")
    curs.execute(
        "CREATE INDEX change_records_enrichment_version ON change_records (enrichment_version)"
    )
    curs.execute("CREATE INDEX change_records_needs_review ON change_records (needs_review)")


# --- Creature types (source of truth for trait routing) ---


def create_creature_types_table(curs):
    # COLLATE NOCASE so lookups and uniqueness are case-insensitive — template
    # link text may lowercase trait names while the canonical creature data
    # uses title case.
    sql = "\n".join(
        [
            "CREATE TABLE creature_types (",
            "  creature_type_id INTEGER PRIMARY KEY,",
            "  name TEXT NOT NULL UNIQUE COLLATE NOCASE,",
            "  created_at TEXT NOT NULL",
            ")",
        ]
    )
    curs.execute(sql)
