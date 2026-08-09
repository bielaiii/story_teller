from __future__ import annotations

import hashlib
import time

from storyteller import SCHEMA_VERSION
from storyteller.colors import content_color


ENTITY_KINDS = (
    "character",
    "plot",
    "entry",
    "fragment",
    "relationship",
    "timeline_line",
    "chapter",
)

MERGE_SCHEMA_SQL = r"""
CREATE TABLE merge_sessions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    source_path TEXT NOT NULL DEFAULT '',
    base_hash TEXT NOT NULL,
    ours_hash TEXT NOT NULL,
    theirs_hash TEXT NOT NULL,
    base_revision INTEGER NOT NULL DEFAULT 0,
    ours_revision INTEGER NOT NULL DEFAULT 0,
    theirs_revision INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open', 'resolved')),
    conflict_count INTEGER NOT NULL DEFAULT 0 CHECK(conflict_count >= 0),
    created_at INTEGER NOT NULL,
    resolved_at INTEGER
);
CREATE INDEX merge_sessions_status ON merge_sessions(project_id, status, created_at);

CREATE TABLE merge_conflicts (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES merge_sessions(id) ON DELETE CASCADE,
    table_name TEXT NOT NULL,
    primary_key_json TEXT NOT NULL,
    entity_id TEXT,
    title TEXT NOT NULL,
    base_json TEXT,
    ours_json TEXT,
    theirs_json TEXT,
    merged_json TEXT,
    conflict_columns_json TEXT NOT NULL,
    resolution_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open', 'resolved')),
    created_at INTEGER NOT NULL,
    resolved_at INTEGER,
    UNIQUE(session_id, table_name, primary_key_json)
);
CREATE INDEX merge_conflicts_status ON merge_conflicts(session_id, status, table_name);
"""


SCHEMA_SQL = r"""
CREATE TABLE metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE projects (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    eyebrow TEXT NOT NULL DEFAULT 'Story Teller',
    revision INTEGER NOT NULL DEFAULT 0 CHECK(revision >= 0),
    extra_json TEXT NOT NULL DEFAULT '{}',
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE TABLE entities (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK(kind IN (
        'character', 'plot', 'entry', 'fragment', 'relationship', 'timeline_line', 'chapter'
    )),
    stable_id TEXT NOT NULL,
    title TEXT NOT NULL,
    deleted_at INTEGER,
    purge_at INTEGER,
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision >= 1),
    extra_json TEXT NOT NULL DEFAULT '{}',
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    UNIQUE(project_id, kind, stable_id),
    CHECK((deleted_at IS NULL AND purge_at IS NULL) OR
          (deleted_at IS NOT NULL AND purge_at IS NOT NULL AND purge_at > deleted_at))
);
CREATE INDEX entities_activity ON entities(project_id, kind, deleted_at, stable_id);
CREATE INDEX entities_purge ON entities(purge_at) WHERE deleted_at IS NOT NULL;

CREATE TABLE chapters (
    entity_id TEXT PRIMARY KEY REFERENCES entities(id) ON DELETE CASCADE,
    label TEXT NOT NULL,
    sort_key TEXT NOT NULL,
    UNIQUE(sort_key)
);

CREATE TABLE characters (
    entity_id TEXT PRIMARY KEY REFERENCES entities(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    intro_markdown TEXT NOT NULL DEFAULT '',
    narrative_role TEXT NOT NULL CHECK(narrative_role IN ('主角', '配角')),
    character_scope TEXT NOT NULL CHECK(character_scope IN ('主线人物', '常驻人物', '待定角色', '一次性角色')),
    side TEXT NOT NULL CHECK(side IN ('主角方', '中立', '反派方')),
    main_plot_impact INTEGER NOT NULL DEFAULT 0 CHECK(main_plot_impact BETWEEN 0 AND 100),
    color TEXT NOT NULL DEFAULT '#7d6bd6',
    gradient TEXT NOT NULL DEFAULT '',
    group_name TEXT NOT NULL DEFAULT '',
    graph_visible INTEGER NOT NULL DEFAULT 0 CHECK(graph_visible IN (0, 1))
);

CREATE TABLE character_aliases (
    character_id TEXT NOT NULL REFERENCES characters(entity_id) ON DELETE CASCADE,
    alias TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(character_id, alias)
);

CREATE TABLE character_markers (
    character_id TEXT NOT NULL REFERENCES characters(entity_id) ON DELETE CASCADE,
    marker TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(character_id, marker)
);

CREATE TABLE character_facts (
    character_id TEXT NOT NULL REFERENCES characters(entity_id) ON DELETE CASCADE,
    fact_key TEXT NOT NULL,
    fact_value TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(character_id, fact_key)
);

CREATE TABLE character_supplements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    character_id TEXT NOT NULL REFERENCES characters(entity_id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE entries (
    entity_id TEXT PRIMARY KEY REFERENCES entities(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    subtype TEXT NOT NULL DEFAULT '',
    area TEXT NOT NULL DEFAULT '',
    body_markdown TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT '',
    accent TEXT NOT NULL DEFAULT '#7d6bd6'
);

CREATE TABLE entry_aliases (
    entry_id TEXT NOT NULL REFERENCES entries(entity_id) ON DELETE CASCADE,
    alias TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(entry_id, alias)
);

CREATE TABLE entry_tags (
    entry_id TEXT NOT NULL REFERENCES entries(entity_id) ON DELETE CASCADE,
    tag TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(entry_id, tag)
);

CREATE TABLE fragments (
    entity_id TEXT PRIMARY KEY REFERENCES entities(id) ON DELETE CASCADE,
    body_markdown TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT '',
    accent TEXT NOT NULL DEFAULT '#7d6bd6'
);

CREATE TABLE fragment_tags (
    fragment_id TEXT NOT NULL REFERENCES fragments(entity_id) ON DELETE CASCADE,
    tag TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(fragment_id, tag)
);

CREATE TABLE plots (
    entity_id TEXT PRIMARY KEY REFERENCES entities(id) ON DELETE CASCADE,
    chapter_id TEXT REFERENCES chapters(entity_id),
    sort_key TEXT NOT NULL,
    story_sort_key TEXT NOT NULL DEFAULT '',
    story_order_mode TEXT NOT NULL DEFAULT 'follow_reading' CHECK(story_order_mode IN ('follow_reading', 'fixed')),
    story_anchor_plot_id TEXT REFERENCES plots(entity_id),
    story_anchor_side TEXT CHECK(story_anchor_side IS NULL OR story_anchor_side IN ('before', 'after')),
    summary TEXT NOT NULL DEFAULT '',
    body_markdown TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT '草稿',
    accent TEXT NOT NULL DEFAULT '#7d6bd6',
    is_key INTEGER NOT NULL DEFAULT 0 CHECK(is_key IN (0, 1)),
    is_climax INTEGER NOT NULL DEFAULT 0 CHECK(is_climax IN (0, 1)),
    UNIQUE(sort_key)
);

CREATE TABLE plot_tags (
    plot_id TEXT NOT NULL REFERENCES plots(entity_id) ON DELETE CASCADE,
    tag TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(plot_id, tag)
);

CREATE TABLE plot_characters (
    plot_id TEXT NOT NULL REFERENCES plots(entity_id) ON DELETE CASCADE,
    character_id TEXT NOT NULL REFERENCES characters(entity_id) ON DELETE CASCADE,
    source TEXT NOT NULL DEFAULT 'metadata',
    PRIMARY KEY(plot_id, character_id)
);

CREATE TABLE plot_entries (
    plot_id TEXT NOT NULL REFERENCES plots(entity_id) ON DELETE CASCADE,
    entry_id TEXT NOT NULL REFERENCES entries(entity_id) ON DELETE CASCADE,
    source TEXT NOT NULL DEFAULT 'metadata',
    PRIMARY KEY(plot_id, entry_id)
);

CREATE TABLE entry_characters (
    entry_id TEXT NOT NULL REFERENCES entries(entity_id) ON DELETE CASCADE,
    character_id TEXT NOT NULL REFERENCES characters(entity_id) ON DELETE CASCADE,
    role TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT '现成员',
    sort_key INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(entry_id, character_id)
);

CREATE TABLE relationships (
    entity_id TEXT PRIMARY KEY REFERENCES entities(id) ON DELETE CASCADE,
    from_character_id TEXT NOT NULL REFERENCES characters(entity_id) ON DELETE CASCADE,
    to_character_id TEXT NOT NULL REFERENCES characters(entity_id) ON DELETE CASCADE,
    from_role TEXT NOT NULL DEFAULT '',
    to_role TEXT NOT NULL DEFAULT '',
    from_impression TEXT NOT NULL DEFAULT '',
    to_impression TEXT NOT NULL DEFAULT '',
    graph_scope TEXT NOT NULL DEFAULT 'core' CHECK(graph_scope IN ('core', 'focus', 'hidden')),
    graph_line_mode TEXT NOT NULL DEFAULT 'single' CHECK(graph_line_mode IN ('single', 'double')),
    label TEXT NOT NULL DEFAULT '',
    type TEXT NOT NULL DEFAULT '',
    color TEXT NOT NULL DEFAULT '#8b95a7',
    body_markdown TEXT NOT NULL DEFAULT '',
    CHECK(from_character_id <> to_character_id)
);
CREATE UNIQUE INDEX relationship_pair ON relationships(
    min(from_character_id, to_character_id), max(from_character_id, to_character_id)
);

CREATE TABLE timeline_settings (
    project_id TEXT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
    main_line_id TEXT REFERENCES timeline_lines(entity_id) DEFERRABLE INITIALLY DEFERRED,
    line_spacing INTEGER NOT NULL DEFAULT 72,
    top_padding INTEGER NOT NULL DEFAULT 64,
    side_padding INTEGER NOT NULL DEFAULT 36,
    pixels_per_story_unit INTEGER NOT NULL DEFAULT 760,
    extra_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE timeline_lines (
    entity_id TEXT PRIMARY KEY REFERENCES entities(id) ON DELETE CASCADE,
    color TEXT NOT NULL DEFAULT '#3f7fc1',
    side TEXT NOT NULL DEFAULT 'right' CHECK(side IN ('center', 'left', 'right')),
    sort_key TEXT NOT NULL,
    start_plot_id TEXT REFERENCES plots(entity_id),
    end_plot_id TEXT REFERENCES plots(entity_id),
    UNIQUE(sort_key),
    CHECK(start_plot_id IS NULL OR end_plot_id IS NULL OR start_plot_id <> end_plot_id)
);

CREATE TABLE plot_timeline_lines (
    plot_id TEXT NOT NULL REFERENCES plots(entity_id) ON DELETE CASCADE,
    line_id TEXT NOT NULL REFERENCES timeline_lines(entity_id) ON DELETE CASCADE,
    story_sort_key TEXT NOT NULL,
    PRIMARY KEY(plot_id, line_id),
    UNIQUE(line_id, story_sort_key)
);

CREATE TABLE timeline_connections (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    source_line_id TEXT NOT NULL REFERENCES timeline_lines(entity_id) ON DELETE CASCADE,
    target_line_id TEXT NOT NULL REFERENCES timeline_lines(entity_id) ON DELETE CASCADE,
    source_plot_id TEXT REFERENCES plots(entity_id) ON DELETE CASCADE,
    target_plot_id TEXT REFERENCES plots(entity_id) ON DELETE CASCADE,
    CHECK(source_line_id <> target_line_id)
);

CREATE TABLE graph_settings (
    project_id TEXT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
    node_spacing REAL NOT NULL DEFAULT 116,
    initial_jitter REAL NOT NULL DEFAULT 38,
    relationship_distance REAL NOT NULL DEFAULT 250,
    leaf_distance_extra REAL NOT NULL DEFAULT 48,
    center_strength REAL NOT NULL DEFAULT 1,
    group_strength REAL NOT NULL DEFAULT 1,
    leaf_strength REAL NOT NULL DEFAULT 1,
    extra_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE graph_nodes (
    character_id TEXT PRIMARY KEY REFERENCES characters(entity_id) ON DELETE CASCADE,
    orbit_of TEXT REFERENCES characters(entity_id) ON DELETE CASCADE,
    orbit_distance REAL,
    orbit_angle REAL,
    strength REAL,
    anchor_x REAL,
    anchor_y REAL,
    CHECK(character_id <> orbit_of)
);

CREATE TABLE graph_distances (
    from_character_id TEXT NOT NULL REFERENCES characters(entity_id) ON DELETE CASCADE,
    to_character_id TEXT NOT NULL REFERENCES characters(entity_id) ON DELETE CASCADE,
    distance REAL NOT NULL,
    strength REAL NOT NULL,
    PRIMARY KEY(from_character_id, to_character_id),
    CHECK(from_character_id <> to_character_id)
);

CREATE TABLE graph_clusters (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    label TEXT NOT NULL,
    center_x REAL,
    center_y REAL,
    radius REAL,
    strength REAL,
    sort_key TEXT NOT NULL
);

CREATE TABLE graph_cluster_members (
    cluster_id TEXT NOT NULL REFERENCES graph_clusters(id) ON DELETE CASCADE,
    character_id TEXT NOT NULL REFERENCES characters(entity_id) ON DELETE CASCADE,
    PRIMARY KEY(cluster_id, character_id)
);

CREATE TABLE entity_references (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_entity_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    target_entity_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    context TEXT NOT NULL DEFAULT 'body',
    marker TEXT NOT NULL DEFAULT '',
    start_offset INTEGER,
    end_offset INTEGER,
    source TEXT NOT NULL DEFAULT 'editor',
    UNIQUE(source_entity_id, target_entity_id, context, marker, start_offset),
    CHECK(source_entity_id <> target_entity_id),
    CHECK(start_offset IS NULL OR (start_offset >= 0 AND end_offset >= start_offset))
);

CREATE TABLE assets (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    entity_id TEXT REFERENCES entities(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    media_type TEXT NOT NULL,
    content BLOB NOT NULL,
    content_hash TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    UNIQUE(project_id, filename)
);

CREATE TABLE operations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    actor TEXT NOT NULL DEFAULT 'local-user',
    label TEXT NOT NULL,
    action TEXT NOT NULL DEFAULT 'update',
    entity_kind TEXT NOT NULL DEFAULT 'content',
    base_revision INTEGER NOT NULL,
    result_revision INTEGER NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}',
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    undone_at INTEGER,
    undone_by INTEGER REFERENCES operations(id),
    CHECK(result_revision = base_revision + 1)
);
CREATE INDEX operations_history ON operations(project_id, created_at DESC, id DESC);
CREATE INDEX operations_retention ON operations(expires_at);

CREATE TABLE operation_changes (
    operation_id INTEGER NOT NULL REFERENCES operations(id) ON DELETE CASCADE,
    table_name TEXT NOT NULL,
    primary_key_json TEXT NOT NULL,
    before_json TEXT,
    after_json TEXT,
    before_revision INTEGER,
    after_revision INTEGER,
    PRIMARY KEY(operation_id, table_name, primary_key_json)
);
""" + MERGE_SCHEMA_SQL + r"""
CREATE TABLE export_state (
    project_id TEXT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
    requested_revision INTEGER NOT NULL DEFAULT 0,
    exported_revision INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'ready' CHECK(status IN ('ready', 'pending', 'failed')),
    last_error TEXT NOT NULL DEFAULT '',
    updated_at INTEGER NOT NULL
);

CREATE VIEW active_entities AS
SELECT * FROM entities WHERE deleted_at IS NULL;

CREATE VIEW active_characters AS
SELECT c.*, e.project_id, e.stable_id, e.title, e.revision, e.extra_json
FROM characters c JOIN entities e ON e.id = c.entity_id
WHERE e.deleted_at IS NULL;

CREATE VIEW active_plots AS
SELECT p.*, e.project_id, e.stable_id, e.title, e.revision, e.extra_json,
       ROW_NUMBER() OVER (PARTITION BY e.project_id ORDER BY p.sort_key, e.stable_id) AS display_sequence
FROM plots p JOIN entities e ON e.id = p.entity_id
WHERE e.deleted_at IS NULL;

CREATE VIEW active_entries AS
SELECT d.*, e.project_id, e.stable_id, e.title, e.revision, e.extra_json
FROM entries d JOIN entities e ON e.id = d.entity_id
WHERE e.deleted_at IS NULL;

CREATE VIEW active_fragments AS
SELECT f.*, e.project_id, e.stable_id, e.title, e.revision, e.extra_json
FROM fragments f JOIN entities e ON e.id = f.entity_id
WHERE e.deleted_at IS NULL;

CREATE VIEW active_chapters AS
SELECT c.*, e.project_id, e.stable_id, e.title, e.revision
FROM chapters c JOIN entities e ON e.id = c.entity_id
WHERE e.deleted_at IS NULL;

CREATE VIEW active_timeline_lines AS
SELECT l.*, e.project_id, e.stable_id, e.title, e.revision
FROM timeline_lines l JOIN entities e ON e.id = l.entity_id
WHERE e.deleted_at IS NULL;

CREATE VIEW active_relationships AS
SELECT r.*, relationship_entity.project_id, relationship_entity.stable_id,
       relationship_entity.revision
FROM relationships r
JOIN entities relationship_entity ON relationship_entity.id = r.entity_id
JOIN entities from_entity ON from_entity.id = r.from_character_id
JOIN entities to_entity ON to_entity.id = r.to_character_id
WHERE relationship_entity.deleted_at IS NULL
  AND from_entity.deleted_at IS NULL
  AND to_entity.deleted_at IS NULL;

CREATE VIEW active_plot_characters AS
SELECT pc.* FROM plot_characters pc
JOIN entities plot_entity ON plot_entity.id = pc.plot_id
JOIN entities character_entity ON character_entity.id = pc.character_id
WHERE plot_entity.deleted_at IS NULL AND character_entity.deleted_at IS NULL;

CREATE VIEW active_plot_entries AS
SELECT pe.* FROM plot_entries pe
JOIN entities plot_entity ON plot_entity.id = pe.plot_id
JOIN entities entry_entity ON entry_entity.id = pe.entry_id
WHERE plot_entity.deleted_at IS NULL AND entry_entity.deleted_at IS NULL;

CREATE VIEW active_graph_nodes AS
SELECT n.* FROM graph_nodes n
JOIN entities character_entity ON character_entity.id = n.character_id
LEFT JOIN entities orbit_entity ON orbit_entity.id = n.orbit_of
WHERE character_entity.deleted_at IS NULL
  AND (n.orbit_of IS NULL OR orbit_entity.deleted_at IS NULL);

CREATE VIEW active_graph_distances AS
SELECT d.* FROM graph_distances d
JOIN entities from_entity ON from_entity.id = d.from_character_id
JOIN entities to_entity ON to_entity.id = d.to_character_id
WHERE from_entity.deleted_at IS NULL AND to_entity.deleted_at IS NULL;

CREATE VIEW active_timeline_nodes AS
SELECT ptl.* FROM plot_timeline_lines ptl
JOIN entities plot_entity ON plot_entity.id = ptl.plot_id
JOIN entities line_entity ON line_entity.id = ptl.line_id
WHERE plot_entity.deleted_at IS NULL AND line_entity.deleted_at IS NULL;

CREATE VIEW active_entity_references AS
SELECT r.* FROM entity_references r
JOIN entities source_entity ON source_entity.id = r.source_entity_id
JOIN entities target_entity ON target_entity.id = r.target_entity_id
WHERE source_entity.deleted_at IS NULL AND target_entity.deleted_at IS NULL;

CREATE VIEW trash_items AS
SELECT id, project_id, kind, stable_id, title, deleted_at, purge_at, revision
FROM entities WHERE deleted_at IS NOT NULL;
"""


def initialize_schema(connection) -> None:
    connection.executescript(SCHEMA_SQL)
    connection.execute(
        "INSERT INTO metadata(key, value) VALUES('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def migrate_v3_to_v4(connection) -> None:
    """Add durable Git merge sessions without rewriting normalized content."""
    connection.executescript(
        "BEGIN IMMEDIATE;\n"
        + MERGE_SCHEMA_SQL
        + f"""
        UPDATE metadata SET value='4' WHERE key='schema_version';
        PRAGMA user_version = 4;
        COMMIT;
        """
    )

def migrate_v4_to_v5(connection) -> None:
    """Persist story chronology separately from reading order."""
    columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(plots)")}
    additions = []
    if "story_sort_key" not in columns:
        additions.append("ALTER TABLE plots ADD COLUMN story_sort_key TEXT NOT NULL DEFAULT '';\n")
    if "story_order_mode" not in columns:
        additions.append(
            "ALTER TABLE plots ADD COLUMN story_order_mode TEXT NOT NULL DEFAULT 'follow_reading' "
            "CHECK(story_order_mode IN ('follow_reading', 'fixed'));\n"
        )
    if "story_anchor_plot_id" not in columns:
        additions.append(
            "ALTER TABLE plots ADD COLUMN story_anchor_plot_id TEXT REFERENCES plots(entity_id);\n"
        )
    if "story_anchor_side" not in columns:
        additions.append(
            "ALTER TABLE plots ADD COLUMN story_anchor_side TEXT "
            "CHECK(story_anchor_side IS NULL OR story_anchor_side IN ('before', 'after'));\n"
        )
    connection.executescript(
        "BEGIN IMMEDIATE;\n"
        + "".join(additions)
        +
        "UPDATE plots SET story_sort_key = COALESCE((SELECT MIN(story_sort_key) FROM plot_timeline_lines WHERE plot_id=plots.entity_id), sort_key) WHERE story_sort_key='';\n"
        "UPDATE metadata SET value='5' WHERE key='schema_version';\n"
        "PRAGMA user_version = 5;\n"
        "COMMIT;"
    )


def migrate_v5_to_v6(connection) -> None:
    """Store each endpoint's independent impression of the other person."""
    columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(relationships)")}
    additions = []
    if "from_impression" not in columns:
        additions.append(
            "ALTER TABLE relationships ADD COLUMN from_impression TEXT NOT NULL DEFAULT '';\n"
        )
    if "to_impression" not in columns:
        additions.append(
            "ALTER TABLE relationships ADD COLUMN to_impression TEXT NOT NULL DEFAULT '';\n"
        )
    connection.executescript(
        "BEGIN IMMEDIATE;\n"
        + "".join(additions)
        +
        "UPDATE metadata SET value='6' WHERE key='schema_version';\n"
        "PRAGMA user_version = 6;\n"
        "COMMIT;"
    )


def migrate_v6_to_v7(connection) -> None:
    """Separate organization membership and graph presentation from pairwise notes."""
    entry_columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(entry_characters)")}
    relationship_columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(relationships)")}
    connection.execute("BEGIN IMMEDIATE")
    try:
        if "role" not in entry_columns:
            connection.execute("ALTER TABLE entry_characters ADD COLUMN role TEXT NOT NULL DEFAULT ''")
        if "status" not in entry_columns:
            connection.execute(
                "ALTER TABLE entry_characters ADD COLUMN status TEXT NOT NULL DEFAULT '现成员'"
            )
        if "sort_key" not in entry_columns:
            connection.execute(
                "ALTER TABLE entry_characters ADD COLUMN sort_key INTEGER NOT NULL DEFAULT 0"
            )
        if "graph_scope" not in relationship_columns:
            connection.execute(
                "ALTER TABLE relationships ADD COLUMN graph_scope TEXT NOT NULL DEFAULT 'core' "
                "CHECK(graph_scope IN ('core', 'focus', 'hidden'))"
            )
        connection.execute(
            """
            UPDATE relationships SET graph_scope='focus'
            WHERE type IN ('父子','父女','母子','母女','兄妹','姐妹','姐弟','哥弟','兄弟','姐弟妹','伴侣','夫妻')
            """
        )
        connection.execute(
            """
            UPDATE relationships SET graph_scope='hidden'
            WHERE trim(label)='' AND trim(type)='' AND trim(from_role)='' AND trim(to_role)=''
              AND trim(body_markdown)='' AND (trim(from_impression)<>'' OR trim(to_impression)<>'')
            """
        )

        now = int(time.time())
        groups = list(connection.execute(
            """
            SELECT DISTINCT e.project_id, trim(c.group_name) AS group_name
            FROM characters c JOIN entities e ON e.id=c.entity_id
            WHERE e.deleted_at IS NULL
              AND (trim(c.group_name) LIKE '%家族' OR trim(c.group_name) LIKE '%家庭')
            ORDER BY e.project_id, group_name
            """
        ))
        for project_id, group_name in groups:
            group_name = str(group_name)
            existing = connection.execute(
                """
                SELECT d.entity_id FROM entries d JOIN entities e ON e.id=d.entity_id
                WHERE e.project_id=? AND e.deleted_at IS NULL AND d.type='组织' AND d.name=?
                LIMIT 1
                """,
                (project_id, group_name),
            ).fetchone()
            if existing:
                organization_id = str(existing[0])
            else:
                digest = hashlib.sha1(f"{project_id}\0{group_name}".encode("utf-8")).hexdigest()[:12]
                stable_id = f"organization-{digest}"
                organization_id = f"entry:{stable_id}"
                connection.execute(
                    """
                    INSERT INTO entities(
                        id, project_id, kind, stable_id, title, revision, extra_json, created_at, updated_at
                    ) VALUES(?, ?, 'entry', ?, ?, 1, '{}', ?, ?)
                    """,
                    (organization_id, project_id, stable_id, group_name, now, now),
                )
                subtype = "家庭"
                connection.execute(
                    """
                    INSERT INTO entries(entity_id, name, type, subtype, area, body_markdown, status, accent)
                    VALUES(?, ?, '组织', ?, '', '', '活跃', '#6f75c9')
                    """,
                    (organization_id, group_name, subtype),
                )
            members = list(connection.execute(
                """
                SELECT c.entity_id, c.name,
                       COALESCE((SELECT fact_value FROM character_facts f
                                 WHERE f.character_id=c.entity_id AND f.fact_key IN ('家庭身份','家族身份','组织身份','身份')
                                 ORDER BY CASE f.fact_key WHEN '家庭身份' THEN 0 WHEN '家族身份' THEN 1
                                          WHEN '组织身份' THEN 2 ELSE 3 END, f.position LIMIT 1), '') AS role
                FROM characters c JOIN entities e ON e.id=c.entity_id
                WHERE e.project_id=? AND e.deleted_at IS NULL AND trim(c.group_name)=?
                ORDER BY c.main_plot_impact DESC, c.entity_id
                """,
                (project_id, group_name),
            ))
            family_token = group_name.removesuffix("家族").removesuffix("家庭").strip()
            confirmed_members = [
                (character_id, role)
                for character_id, character_name, role in members
                if not family_token or family_token in str(character_name) or family_token in str(role)
            ]
            confirmed_ids = {str(item[0]) for item in confirmed_members}
            role_priority = {
                "父亲": 0, "母亲": 0, "丈夫": 1, "妻子": 1,
                "长子": 2, "长女": 2, "大女儿": 2, "小女儿": 2,
                "儿子": 3, "女儿": 3, "哥哥": 4, "姐姐": 4, "弟弟": 5, "妹妹": 5,
            }
            enriched_members = []
            for character_id, role in confirmed_members:
                clean_role = str(role).strip()
                if not clean_role:
                    candidates = []
                    for row in connection.execute(
                        """
                        SELECT from_character_id, to_character_id, from_role, to_role
                        FROM relationships
                        WHERE from_character_id=? OR to_character_id=?
                        """,
                        (character_id, character_id),
                    ):
                        other_id = str(row[1]) if str(row[0]) == str(character_id) else str(row[0])
                        if other_id not in confirmed_ids:
                            continue
                        candidate = str(row[2]) if str(row[0]) == str(character_id) else str(row[3])
                        if candidate:
                            candidates.append(candidate)
                    if candidates:
                        clean_role = min(candidates, key=lambda value: (role_priority.get(value, 99), len(value), value))
                enriched_members.append((character_id, clean_role))
            for position, (character_id, role) in enumerate(enriched_members):
                connection.execute(
                    """
                    INSERT INTO entry_characters(entry_id, character_id, role, status, sort_key)
                    VALUES(?, ?, ?, '现成员', ?)
                    ON CONFLICT(entry_id, character_id) DO UPDATE SET
                        role=CASE WHEN entry_characters.role='' THEN excluded.role ELSE entry_characters.role END,
                        sort_key=excluded.sort_key
                    """,
                    (organization_id, character_id, str(role)[:120], position),
                )
        connection.execute("UPDATE metadata SET value='7' WHERE key='schema_version'")
        connection.execute("PRAGMA user_version = 7")
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def migrate_v7_to_v8(connection) -> None:
    """Allow one relationship record to render as one shared or two directional lines."""
    columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(relationships)")}
    connection.execute("BEGIN IMMEDIATE")
    try:
        if "graph_line_mode" not in columns:
            connection.execute(
                "ALTER TABLE relationships ADD COLUMN graph_line_mode TEXT NOT NULL DEFAULT 'single' "
                "CHECK(graph_line_mode IN ('single', 'double'))"
            )
        connection.execute(
            """
            UPDATE relationships SET graph_line_mode='double'
            WHERE graph_scope<>'hidden'
              AND trim(from_impression)<>'' AND trim(to_impression)<>''
              AND trim(from_impression)<>trim(to_impression)
            """
        )
        connection.execute(
            """
            UPDATE export_state
            SET requested_revision=(SELECT revision FROM projects WHERE projects.id=export_state.project_id),
                status='pending', last_error='', updated_at=?
            """,
            (int(time.time()),),
        )
        connection.execute("UPDATE metadata SET value='8' WHERE key='schema_version'")
        connection.execute("PRAGMA user_version = 8")
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def migrate_v8_to_v9(connection) -> None:
    """Spread untouched character and entry defaults across one curated palette."""
    connection.execute("BEGIN IMMEDIATE")
    try:
        for entity_id, in connection.execute(
            "SELECT entity_id FROM characters WHERE lower(color) IN ('#7d6bd6', '#3f7fc1')"
        ):
            connection.execute(
                "UPDATE characters SET color=? WHERE entity_id=?",
                (content_color(f"character:{entity_id}"), entity_id),
            )
        for entity_id, in connection.execute(
            "SELECT entity_id FROM entries WHERE lower(accent) IN ('#7d6bd6', '#3f7fc1', '#6f75c9')"
        ):
            connection.execute(
                "UPDATE entries SET accent=? WHERE entity_id=?",
                (content_color(f"entry:{entity_id}"), entity_id),
            )
        connection.execute(
            """
            UPDATE export_state
            SET requested_revision=(SELECT revision FROM projects WHERE projects.id=export_state.project_id),
                status='pending', last_error='', updated_at=?
            """,
            (int(time.time()),),
        )
        connection.execute("UPDATE metadata SET value='9' WHERE key='schema_version'")
        connection.execute("PRAGMA user_version = 9")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
