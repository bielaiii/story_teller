from __future__ import annotations

from storyteller import SCHEMA_VERSION


ENTITY_KINDS = (
    "character",
    "plot",
    "entry",
    "fragment",
    "relationship",
    "timeline_line",
    "chapter",
)


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
    graph_visible INTEGER CHECK(graph_visible IN (0, 1) OR graph_visible IS NULL)
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
    PRIMARY KEY(entry_id, character_id)
);

CREATE TABLE relationships (
    entity_id TEXT PRIMARY KEY REFERENCES entities(id) ON DELETE CASCADE,
    from_character_id TEXT NOT NULL REFERENCES characters(entity_id) ON DELETE CASCADE,
    to_character_id TEXT NOT NULL REFERENCES characters(entity_id) ON DELETE CASCADE,
    from_role TEXT NOT NULL DEFAULT '',
    to_role TEXT NOT NULL DEFAULT '',
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
