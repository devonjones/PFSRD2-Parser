def create_link_cache_table(curs):
    sql = '\n'.join([
        "CREATE TABLE link_cache (",
        "  item_id INTEGER,",
        "  item_aonid INTEGER,",
        "  target_aonid INTEGER",
        ")"])
    curs.execute(sql)

def drop_link_cache_table(curs):
    sql = 'DROP TABLE IF EXISTS link_cache'
    curs.execute(sql)

def insert_link_cache(curs, item_id, item_aonid, target_aonid):
    sql = '\n'.join([
        "INSERT OR IGNORE INTO link_cache",
        " (item_id, item_aonid, target_aonid)",
        " VALUES",
        " (?, ?, ?)"
    ])
    curs.execute(sql, [item_id, item_aonid, target_aonid])

def fetch_all_link_cache(curs):
    sql = '\n'.join([
        "SELECT item_id, item_aonid, target_aonid",
        " FROM link_cache"])
    curs.execute(sql)
    return curs.fetchall()

def create_legacy_remastered_relations(curs, link_cache, fetch_item_by_id, item_id_col='item_id'):
    """
    link_cache: iterable of dicts or tuples with item_id, item_aonid, target_aonid
    fetch_item_by_id: function(curs, item_id) -> row with 'edition' and id column
    item_id_col: the column name for the id (default 'item_id')
    Returns set of (legacy_id, remastered_id) pairs.
    """
    relations = set()
    for link in link_cache:
        target_aonid = link.get('target_aonid')
        item = fetch_item_by_id(curs, link['item_id'])
        if not item:
            continue
        edition = item.get('edition')
        # Find the target item by matching aonid in link_cache
        target = None
        for candidate in link_cache:
            cand_aonid = candidate.get('item_aonid')
            cand_id = candidate.get('item_id')
            if cand_aonid == target_aonid:
                target = fetch_item_by_id(curs, cand_id)
                break
        assert target, f"No target found for {link}"
        target_edition = target.get('edition')

        item_id_val = item[item_id_col]
        target_id_val = target[item_id_col]
        if edition == 'legacy' and target_edition == 'remastered':
            relations.add((item_id_val, target_id_val))
        elif edition == 'remastered' and target_edition == 'legacy':
            relations.add((target_id_val, item_id_val))
        else:
            print(f"No relation found for {link} {edition} {target_edition}")
            raise
    return relations
