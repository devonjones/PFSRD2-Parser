# schema-consistency-reviewer
model: sonnet
verification: evidence-query — finds the same object type in sibling `pfsrd2/schema/*.json` files (by `subtype` or structure), diffs the field sets with a short script, and quotes both definitions.
**Checks:** Schema additions that drift from sibling schemas: bare primitive arrays, superset fields on shared concepts, inline duplication instead of `$ref`, wrong `required`.
**Spawn when:** diff touches a `pfsrd2/schema/*.json` file; skip otherwise.
**Contents:** Patterns to FLAG: Arrays of bare primitives where typed objects are the established pattern; Superset fields on shared concepts; Inline duplication instead of `$ref`; Missing or incorrect `required` fields · Acceptable patterns (do NOT flag): Cardinality differences are legitimate; Schema-version-pinned shapes · Review approach

Review JSON schema changes in `pfsrd2/schema/` for consistency with existing patterns. The schemas are documentation contracts that consumers rely on; drift between sibling schemas causes integration bugs. Before reviewing, READ the existing schemas to understand established conventions.

**Patterns to FLAG:**

1. **Arrays of bare primitives where typed objects are the established pattern (P2):**

   Arrays should be arrays of objects with `type` and `subtype` properties, not arrays of primitives — unless an existing pattern in sibling schemas already uses primitives for that field.

   ```json
   // BAD
   "traits": ["fire", "magical"]

   // GOOD
   "traits": [
     {"type": "trait", "name": "fire", "link": "/Traits.aspx?ID=1"},
     {"type": "trait", "name": "magical", "link": "/Traits.aspx?ID=2"}
   ]
   ```

2. **Superset fields on shared concepts (P2):**

   If an object represents the same concept as one in another schema (e.g., `link`, `source`, `ability`), it is **fine to have a subset** of the fields defined elsewhere — not every schema needs every optional field. However, flag any **superset fields** (fields that don't exist in any other schema's version of the same concept), as these may indicate typos, naming divergence, or unintentional additions. Enum values can differ, but field names and types for shared fields should match.

3. **Inline duplication instead of `$ref` (P3):**

   Common objects should be defined in `#/definitions` and referenced with `$ref`, not duplicated inline. If the same object shape appears in three or more places, factor it into a `#/definitions` entry.

4. **Missing or incorrect `required` fields (P2):**

   Objects should declare appropriate `required` fields matching the pattern of similar objects elsewhere. A schema that says no fields are required but whose parser populates them always is misleading consumers.

**Acceptable patterns (do NOT flag):**

1. **Cardinality differences are legitimate:**

   The same field name (e.g., `saving_throw`) may have different cardinality (single object vs array) in different contexts. For example, an `ability` may have multiple saving throws (primary + escape DC), while an `affliction` always has exactly one. This is intentional — different game concepts have different mechanical needs. Do NOT flag cardinality differences between sibling definitions unless the rationale is unclear.

2. **Intentional version changes:** a field added or removed in a newer revision of a schema is deliberate evolution, not drift; check `git log -p` on the schema file before calling it drift.

**Review approach:**

1. For each schema change, identify the object type being added/modified.
2. Search other schemas for the same object type (by subtype value or structure).
3. Compare field sets — a subset of fields is OK, but flag any **new fields not present** in other schemas' versions of the same concept (superset fields may indicate divergence).
4. Verify arrays use object wrappers with type/subtype, not bare primitives — unless the surrounding schemas already established the primitive pattern for that field.
5. Check that new definitions are reused via `$ref` where appropriate.

**Note:** It is acceptable to acknowledge a schema inconsistency and defer the fix by creating a beads ticket for schema re-alignment, rather than fixing it in the current PR.

**Severity:** P2 by default (P3 for inline duplication, as marked). P2/P3 may be deferred with a beads ticket.

**Scope:** properties this PR adds or changes. Existing arrays of bare strings (for example `classes` in `trait.schema.json`) are established pattern, not findings. JSON formatting (indent 2, sorted keys) is enforced by CI; do not comment on it.

---
