from __future__ import annotations

SESSION_COLUMN_NAMES = (
    "session_id",
    "provider",
    "cli",
    "run_id",
    "cwd",
    "workspace_slug",
    "workspace_hash",
    "native_session_id",
    "minted",
    "source_descriptor",
    "home_dir",
    "template_provenance",
    "owner",
    "session_purpose",
    "session_visibility",
    "status",
    "title",
    "parent_session_id",
    "forked_at_seq",
    "started_at",
    "created_at",
    "updated_at",
)
SESSION_COLUMNS = ", ".join(SESSION_COLUMN_NAMES)
SESSION_VIEW_COLUMNS = ", ".join(f"s.{name}" for name in SESSION_COLUMN_NAMES)
CHILD_SESSION_COLUMNS = ", ".join(f"c.{name}" for name in SESSION_COLUMN_NAMES)
EVENT_COLUMN_NAMES = (
    "session_id",
    "seq",
    "kind",
    "native_turn_id",
    "parent_native_id",
    "parent_seq",
    "run_id",
    "provider",
    "cli",
    "role",
    "is_sidechain",
    "ts",
    "model",
    "raw",
    "ir",
    "source_path",
    "source_line",
    "search_text",
    "created_at",
)
EVENT_COLUMNS = ", ".join(EVENT_COLUMN_NAMES)
EVENT_OWNER_COLUMNS = ", ".join(f"e.{name}" for name in EVENT_COLUMN_NAMES)
ARTIFACT_COLUMNS = "hash, media_type, size_bytes, bytes, created_at"


UPSERT_SESSION_SQL = f"""
INSERT INTO "session" (
    session_id, provider, cli, run_id, cwd, workspace_slug, workspace_hash,
    native_session_id, minted, source_descriptor, home_dir, template_provenance, owner, session_purpose,
    session_visibility, status, title, parent_session_id, forked_at_seq, started_at
) VALUES (
    %(session_id)s, %(provider)s, %(cli)s, %(run_id)s, %(cwd)s, %(workspace_slug)s,
    %(workspace_hash)s, %(native_session_id)s, %(minted)s, %(source_descriptor)s,
    %(home_dir)s, %(template_provenance)s, %(owner)s, %(session_purpose)s,
    %(session_visibility)s, %(status)s, %(title)s, %(parent_session_id)s,
    %(forked_at_seq)s, %(started_at)s
)
ON CONFLICT (session_id) DO UPDATE SET
    provider = EXCLUDED.provider,
    cli = COALESCE("session".cli, EXCLUDED.cli),
    run_id = EXCLUDED.run_id,
    cwd = COALESCE(NULLIF("session".cwd, ''), EXCLUDED.cwd),
    workspace_slug = EXCLUDED.workspace_slug,
    workspace_hash = EXCLUDED.workspace_hash,
    native_session_id = COALESCE("session".native_session_id, EXCLUDED.native_session_id),
    minted = "session".minted OR EXCLUDED.minted,
    source_descriptor = COALESCE("session".source_descriptor, EXCLUDED.source_descriptor),
    home_dir = COALESCE("session".home_dir, EXCLUDED.home_dir),
    template_provenance = COALESCE("session".template_provenance, EXCLUDED.template_provenance),
    owner = EXCLUDED.owner,
    session_purpose = COALESCE("session".session_purpose, EXCLUDED.session_purpose),
    session_visibility = COALESCE("session".session_visibility, EXCLUDED.session_visibility),
    status = EXCLUDED.status,
    title = COALESCE(EXCLUDED.title, "session".title),
    parent_session_id = COALESCE("session".parent_session_id, EXCLUDED.parent_session_id),
    forked_at_seq = COALESCE("session".forked_at_seq, EXCLUDED.forked_at_seq),
    updated_at = now()
RETURNING {SESSION_COLUMNS}
"""

GET_SESSION_SQL = f'SELECT {SESSION_COLUMNS} FROM "session" WHERE session_id = %(session_id)s'
GET_SESSION_FOR_OWNER_SQL = f"""
SELECT {SESSION_COLUMNS}
FROM "session"
WHERE session_id = %(session_id)s
  AND owner = %(owner)s
"""

SESSION_VIEW_SELECT_SQL = f"""
SELECT {SESSION_VIEW_COLUMNS},
       COALESCE(
           (SELECT max(e.ts) FROM "event" AS e WHERE e.session_id = s.session_id),
           s.updated_at,
           s.started_at
       ) AS last_activity_at,
       (
           SELECT count(*)::integer
           FROM "event" AS e
           WHERE e.session_id = s.session_id
             AND e.kind = 'turn'
             AND e.is_sidechain = false
       ) AS turn_count,
       CASE
           WHEN s.parent_session_id IS NULL OR s.forked_at_seq IS NULL THEN 0
           ELSE (
               SELECT count(*)::integer
               FROM "event" AS parent_event
               JOIN "session" AS parent_session
                 ON parent_session.session_id = parent_event.session_id
               WHERE parent_event.session_id = s.parent_session_id
                 AND parent_session.owner = s.owner
                 AND parent_event.kind = 'turn'
                 AND parent_event.is_sidechain = false
                 AND parent_event.seq <= s.forked_at_seq
           )
       END AS inherited_turn_count,
       (
           SELECT e.search_text
           FROM "event" AS e
           WHERE e.session_id = s.session_id
             AND e.kind = 'turn'
             AND e.is_sidechain = false
             AND NULLIF(e.search_text, '') IS NOT NULL
           ORDER BY e.seq DESC
           LIMIT 1
       ) AS last_message_preview
FROM "session" AS s
"""

GET_SESSION_VIEW_FOR_OWNER_SQL = f"""
{SESSION_VIEW_SELECT_SQL}
WHERE s.session_id = %(session_id)s
  AND s.owner = %(owner)s
"""

LIST_SESSIONS_SQL = f"""
SELECT {SESSION_COLUMNS}
FROM "session"
WHERE owner = %(owner)s
  AND (%(workspace_hash)s::text IS NULL OR workspace_hash = %(workspace_hash)s)
  AND (%(provider)s::text IS NULL OR provider = %(provider)s)
  AND (%(cli)s::text IS NULL OR cli = %(cli)s)
  AND (%(status)s::text IS NULL OR status = %(status)s)
ORDER BY started_at DESC, session_id
LIMIT %(limit)s
OFFSET %(offset)s
"""

LIST_SESSION_VIEWS_SQL = f"""
{SESSION_VIEW_SELECT_SQL}
WHERE s.owner = %(owner)s
  AND (%(workspace_id)s::text IS NULL OR s.workspace_slug || '/' || s.workspace_hash = %(workspace_id)s OR s.workspace_hash = %(workspace_id)s)
  AND (%(purpose)s::text IS NULL OR s.session_purpose = %(purpose)s)
  AND (%(visibility)s::text IS NULL OR s.session_visibility = %(visibility)s)
  AND (
      %(include_internal)s::boolean
      OR (
          s.session_visibility = 'user_visible'
          AND s.session_purpose = ANY(%(user_history_purposes)s::text[])
      )
  )
ORDER BY last_activity_at DESC, s.session_id
LIMIT %(limit)s
OFFSET %(offset)s
"""

INSERT_EVENT_SQL = f"""
INSERT INTO "event" (
    session_id, seq, kind, native_turn_id, parent_native_id, parent_seq, run_id,
    provider, cli, role, is_sidechain, ts, model, raw, ir, source_path,
    source_line, search_text
) VALUES (
    %(session_id)s, %(seq)s, %(kind)s, %(native_turn_id)s, %(parent_native_id)s,
    %(parent_seq)s, %(run_id)s, %(provider)s, %(cli)s, %(role)s, %(is_sidechain)s,
    %(ts)s, %(model)s, %(raw)s, %(ir)s, %(source_path)s, %(source_line)s,
    %(search_text)s
)
ON CONFLICT (session_id, seq) DO UPDATE SET
    kind = EXCLUDED.kind,
    native_turn_id = EXCLUDED.native_turn_id,
    parent_native_id = EXCLUDED.parent_native_id,
    parent_seq = EXCLUDED.parent_seq,
    run_id = EXCLUDED.run_id,
    provider = EXCLUDED.provider,
    cli = EXCLUDED.cli,
    role = EXCLUDED.role,
    is_sidechain = EXCLUDED.is_sidechain,
    ts = EXCLUDED.ts,
    model = EXCLUDED.model,
    raw = EXCLUDED.raw,
    ir = EXCLUDED.ir,
    source_path = EXCLUDED.source_path,
    source_line = EXCLUDED.source_line,
    search_text = EXCLUDED.search_text
RETURNING {EVENT_COLUMNS}
"""

INSERT_DEAD_LETTER_SQL = """
INSERT INTO event_dead_letter (
    session_id, seq, scope, run_id, native_session_id, provider, cli, source_path,
    source_line, event_kind, byte_start, byte_end, error_sqlstate, error_class,
    error_message, raw_excerpt, raw_sha256, raw_byte_len, attempts
) VALUES (
    %(session_id)s, %(seq)s, %(scope)s, %(run_id)s, %(native_session_id)s, %(provider)s,
    %(cli)s, %(source_path)s, %(source_line)s, %(event_kind)s, %(byte_start)s,
    %(byte_end)s, %(error_sqlstate)s, %(error_class)s, %(error_message)s,
    %(raw_excerpt)s, %(raw_sha256)s, %(raw_byte_len)s, %(attempts)s
)
ON CONFLICT (session_id, byte_start, byte_end) DO NOTHING
"""

COUNT_DEAD_LETTERS_BY_RUN_SQL = """
SELECT run_id, count(*)::integer AS dead_letter_count
FROM event_dead_letter
WHERE run_id = ANY(%(run_ids)s::text[])
GROUP BY run_id
"""

COUNT_DEAD_LETTERS_BY_SESSION_SQL = """
SELECT session_id, count(*)::integer AS dead_letter_count
FROM event_dead_letter
WHERE session_id = ANY(%(session_ids)s::text[])
GROUP BY session_id
"""

GET_EVENTS_SQL = f"""
SELECT {EVENT_COLUMNS}
FROM "event"
WHERE session_id = %(session_id)s
  AND (%(from_seq)s::integer IS NULL OR seq >= %(from_seq)s::integer)
  AND (%(to_seq)s::integer IS NULL OR seq <= %(to_seq)s::integer)
ORDER BY seq
"""
GET_EVENTS_FOR_OWNER_SQL = f"""
SELECT {EVENT_OWNER_COLUMNS}
FROM "event" AS e
JOIN "session" AS s ON s.session_id = e.session_id
WHERE e.session_id = %(session_id)s
  AND s.owner = %(owner)s
  AND (%(from_seq)s::integer IS NULL OR e.seq >= %(from_seq)s::integer)
  AND (%(to_seq)s::integer IS NULL OR e.seq <= %(to_seq)s::integer)
ORDER BY e.seq
LIMIT %(limit)s
"""

GET_LATEST_TURN_BEFORE_WITH_RAW_FOR_OWNER_SQL = f"""
SELECT {EVENT_OWNER_COLUMNS}
FROM "event" AS e
JOIN "session" AS s ON s.session_id = e.session_id
WHERE e.session_id = %(session_id)s
  AND s.owner = %(owner)s
  AND e.kind = 'turn'
  AND e.is_sidechain = false
  AND e.seq < %(before_seq)s
ORDER BY e.seq DESC
LIMIT 1
"""

GET_FIRST_TURN_WITH_RAW_FOR_OWNER_SQL = f"""
SELECT {EVENT_OWNER_COLUMNS}
FROM "event" AS e
JOIN "session" AS s ON s.session_id = e.session_id
WHERE e.session_id = %(session_id)s
  AND s.owner = %(owner)s
  AND e.kind = 'turn'
  AND e.is_sidechain = false
  AND (%(role)s::text IS NULL OR e.role = %(role)s::text)
ORDER BY e.seq
LIMIT 1
"""

GET_LATEST_TURN_WITH_RAW_FOR_OWNER_SQL = f"""
SELECT {EVENT_OWNER_COLUMNS}
FROM "event" AS e
JOIN "session" AS s ON s.session_id = e.session_id
WHERE e.session_id = %(session_id)s
  AND s.owner = %(owner)s
  AND e.kind = 'turn'
  AND e.is_sidechain = false
  AND (%(role)s::text IS NULL OR e.role = %(role)s::text)
ORDER BY e.seq DESC
LIMIT 1
"""

COUNT_TURNS_BEFORE_FOR_OWNER_SQL = """
SELECT count(*)::integer AS turn_count
FROM "event" AS e
JOIN "session" AS s ON s.session_id = e.session_id
WHERE e.session_id = %(session_id)s
  AND s.owner = %(owner)s
  AND e.kind = 'turn'
  AND e.is_sidechain = false
  AND e.seq < %(before_seq)s
"""

LIST_CHILD_SESSIONS_FOR_OWNER_SQL = f"""
SELECT {CHILD_SESSION_COLUMNS}, min(e.seq) AS first_seq, max(e.seq) AS last_seq
FROM "session" AS c
JOIN "session" AS p ON p.session_id = c.parent_session_id
LEFT JOIN "event" AS e ON e.session_id = c.session_id
WHERE c.parent_session_id = %(parent_session_id)s
  AND c.owner = %(owner)s
  AND p.owner = %(owner)s
GROUP BY {CHILD_SESSION_COLUMNS}
ORDER BY c.forked_at_seq, c.started_at, c.session_id
"""

IR_SEARCH_SQL = f"""
SELECT {EVENT_COLUMNS}
FROM "event"
WHERE kind = 'turn'
  AND ir @> %(filter)s
ORDER BY session_id, seq
LIMIT %(limit)s
"""

TEXT_SEARCH_SQL = f"""
SELECT {EVENT_COLUMNS}
FROM "event"
WHERE kind = 'turn'
  AND content_tsv @@ websearch_to_tsquery('english', %(query)s)
ORDER BY ts_rank_cd(content_tsv, websearch_to_tsquery('english', %(query)s)) DESC, session_id, seq
LIMIT %(limit)s
"""

UPSERT_ARTIFACT_SQL = f"""
INSERT INTO artifact (hash, media_type, size_bytes, bytes)
VALUES (%(hash)s, %(media_type)s, %(size_bytes)s, %(bytes)s)
ON CONFLICT (hash) DO NOTHING
RETURNING {ARTIFACT_COLUMNS}
"""

GET_ARTIFACT_SQL = f"SELECT {ARTIFACT_COLUMNS} FROM artifact WHERE hash = %(hash)s"

LINK_ARTIFACT_SQL = """
INSERT INTO event_artifact (session_id, seq, artifact_hash, ref)
VALUES (%(session_id)s, %(seq)s, %(artifact_hash)s, %(ref)s)
ON CONFLICT (session_id, seq, artifact_hash) DO UPDATE SET ref = EXCLUDED.ref
RETURNING session_id, seq, artifact_hash, ref
"""

GET_EVENT_ARTIFACTS_FOR_SEQS_SQL = """
SELECT ea.session_id, ea.seq, ea.artifact_hash, ea.ref, a.media_type, a.size_bytes
FROM event_artifact AS ea
JOIN artifact AS a ON a.hash = ea.artifact_hash
WHERE ea.session_id = %(session_id)s
  AND ea.seq = ANY(%(seqs)s::integer[])
ORDER BY ea.seq, ea.artifact_hash
"""
