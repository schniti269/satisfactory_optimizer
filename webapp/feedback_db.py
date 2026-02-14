"""
Feedback Database — SQLite store for user annotations on issue tracebacks.

Stores:
- User ratings (correct/wrong/partial) for each issue diagnosis
- Free-text comments explaining what's actually happening
- Snapshot of the graph context (building info, flow rates, trace path)
  so we can later analyze WHY the diagnosis was wrong
- Tags for categorizing feedback patterns
"""

import hashlib
import sqlite3
import json
import os
import time
from contextlib import contextmanager

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "feedback.db")


def get_db():
    """Get a database connection, creating tables if needed."""
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    _ensure_tables(db)
    return db


@contextmanager
def get_db_ctx():
    """Context manager for database connections."""
    db = get_db()
    try:
        yield db
        db.commit()
    finally:
        db.close()


def _ensure_tables(db):
    """Create tables if they don't exist."""
    db.executescript("""
        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at REAL NOT NULL,

            -- Issue identification
            session_name TEXT,
            building_id TEXT NOT NULL,
            building_name TEXT,
            recipe TEXT,
            issue_category TEXT,
            issue_title TEXT,
            issue_severity TEXT,

            -- User rating
            rating TEXT NOT NULL CHECK(rating IN ('correct', 'wrong', 'partial', 'unsure')),
            comment TEXT,
            tags TEXT,  -- JSON array of tags

            -- Graph context snapshot (for debugging/analysis)
            trace_snapshot TEXT,  -- JSON: full trace data (node_info, edges, layers)
            issue_snapshot TEXT,  -- JSON: the original issue dict
            flow_context TEXT,   -- JSON: {avail_in, expected_in, avail_out, expected_out, clock}

            -- Root cause analysis feedback
            actual_cause TEXT,        -- User's description of the real cause
            suggested_fix TEXT,       -- User's suggested fix
            diagnosis_root_cause TEXT, -- What the system said the root cause was
            diagnosis_suggestion TEXT   -- What the system suggested
        );

        CREATE TABLE IF NOT EXISTS feedback_tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            color TEXT DEFAULT '#58a6ff',
            count INTEGER DEFAULT 0
        );

        -- Pre-populate common tags
        INSERT OR IGNORE INTO feedback_tags (name, color) VALUES
            ('belt-issue', '#d29922'),
            ('pipe-issue', '#a371f7'),
            ('clock-wrong', '#f85149'),
            ('recipe-wrong', '#f85149'),
            ('missing-connection', '#d29922'),
            ('false-positive', '#8b949e'),
            ('correct-diagnosis', '#3fb950'),
            ('needs-more-context', '#58a6ff'),
            ('deadlock', '#f85149'),
            ('circular-dependency', '#d29922'),
            ('underproduction', '#d29922'),
            ('overproduction', '#d29922'),
            ('splitter-issue', '#58a6ff'),
            ('merger-issue', '#58a6ff');

        CREATE INDEX IF NOT EXISTS idx_feedback_building ON feedback(building_id);
        CREATE INDEX IF NOT EXISTS idx_feedback_category ON feedback(issue_category);
        CREATE INDEX IF NOT EXISTS idx_feedback_rating ON feedback(rating);
        CREATE INDEX IF NOT EXISTS idx_feedback_session ON feedback(session_name);

        -- ── Tickets (work orders with lifecycle) ─────────────────────
        CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,

            -- Status workflow
            status TEXT NOT NULL DEFAULT 'OPEN'
                CHECK(status IN ('OPEN', 'IN_PROGRESS', 'RESOLVED', 'WONT_FIX')),
            assigned_to TEXT,

            -- Priority (calculated from impact)
            priority INTEGER NOT NULL DEFAULT 0,
            priority_reason TEXT,

            -- Issue identification
            session_name TEXT,
            building_id TEXT NOT NULL,
            building_name TEXT,
            recipe TEXT,
            issue_category TEXT NOT NULL,
            issue_title TEXT NOT NULL,
            issue_severity TEXT,
            issue_hash TEXT,

            -- Impact metrics
            items_per_min_lost REAL DEFAULT 0,
            mw_lost REAL DEFAULT 0,
            affected_downstream INTEGER DEFAULT 0,

            -- Resolution
            resolved_at REAL,
            resolution_note TEXT,
            auto_resolved BOOLEAN DEFAULT 0,

            -- Dominator info
            dominator_id TEXT,
            root_cause TEXT,

            -- Link to feedback
            feedback_id INTEGER REFERENCES feedback(id)
        );

        CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status);
        CREATE INDEX IF NOT EXISTS idx_tickets_hash ON tickets(issue_hash);
        CREATE INDEX IF NOT EXISTS idx_tickets_building ON tickets(building_id);
        CREATE INDEX IF NOT EXISTS idx_tickets_priority ON tickets(priority DESC);
    """)


def add_feedback(building_id, rating, comment=None, tags=None,
                 session_name=None, building_name=None, recipe=None,
                 issue_category=None, issue_title=None, issue_severity=None,
                 trace_snapshot=None, issue_snapshot=None, flow_context=None,
                 actual_cause=None, suggested_fix=None,
                 diagnosis_root_cause=None, diagnosis_suggestion=None):
    """Add a feedback entry."""
    with get_db_ctx() as db:
        db.execute("""
            INSERT INTO feedback (
                created_at, session_name, building_id, building_name, recipe,
                issue_category, issue_title, issue_severity,
                rating, comment, tags,
                trace_snapshot, issue_snapshot, flow_context,
                actual_cause, suggested_fix,
                diagnosis_root_cause, diagnosis_suggestion
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            time.time(), session_name, building_id, building_name, recipe,
            issue_category, issue_title, issue_severity,
            rating, comment, json.dumps(tags) if tags else None,
            json.dumps(trace_snapshot) if trace_snapshot else None,
            json.dumps(issue_snapshot) if issue_snapshot else None,
            json.dumps(flow_context) if flow_context else None,
            actual_cause, suggested_fix,
            diagnosis_root_cause, diagnosis_suggestion,
        ))

        # Update tag counts
        if tags:
            for tag in tags:
                db.execute("""
                    INSERT INTO feedback_tags (name, count)
                    VALUES (?, 1)
                    ON CONFLICT(name) DO UPDATE SET count = count + 1
                """, (tag,))

        return db.execute("SELECT last_insert_rowid()").fetchone()[0]


def get_feedback(building_id=None, category=None, rating=None,
                 session_name=None, limit=100, offset=0):
    """Query feedback entries with optional filters."""
    with get_db_ctx() as db:
        conditions = []
        params = []

        if building_id:
            conditions.append("building_id = ?")
            params.append(building_id)
        if category:
            conditions.append("issue_category = ?")
            params.append(category)
        if rating:
            conditions.append("rating = ?")
            params.append(rating)
        if session_name:
            conditions.append("session_name = ?")
            params.append(session_name)

        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        params.extend([limit, offset])

        rows = db.execute(f"""
            SELECT * FROM feedback {where}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
        """, params).fetchall()

        return [dict(row) for row in rows]


def get_feedback_stats(session_name=None):
    """Get aggregate feedback statistics."""
    with get_db_ctx() as db:
        where = " WHERE session_name = ?" if session_name else ""
        params = [session_name] if session_name else []

        total = db.execute(f"SELECT COUNT(*) FROM feedback{where}", params).fetchone()[0]

        ratings = {}
        for row in db.execute(f"""
            SELECT rating, COUNT(*) as cnt FROM feedback{where}
            GROUP BY rating
        """, params):
            ratings[row['rating']] = row['cnt']

        categories = {}
        for row in db.execute(f"""
            SELECT issue_category, rating, COUNT(*) as cnt FROM feedback{where}
            GROUP BY issue_category, rating
        """, params):
            cat = row['issue_category']
            if cat not in categories:
                categories[cat] = {}
            categories[cat][row['rating']] = row['cnt']

        # Most common actual causes (when rating = 'wrong')
        wrong_causes = []
        wrong_where = "WHERE rating = 'wrong'"
        wrong_params = []
        if session_name:
            wrong_where += " AND session_name = ?"
            wrong_params.append(session_name)
        for row in db.execute(f"""
            SELECT actual_cause, COUNT(*) as cnt FROM feedback
            {wrong_where}
            GROUP BY actual_cause
            HAVING actual_cause IS NOT NULL
            ORDER BY cnt DESC LIMIT 10
        """, wrong_params):
            wrong_causes.append({"cause": row['actual_cause'], "count": row['cnt']})

        return {
            "total": total,
            "ratings": ratings,
            "by_category": categories,
            "common_wrong_causes": wrong_causes,
        }


def get_feedback_by_id(feedback_id):
    """Get a single feedback entry by ID."""
    with get_db_ctx() as db:
        row = db.execute("SELECT * FROM feedback WHERE id = ?", (feedback_id,)).fetchone()
        return dict(row) if row else None


def get_all_tags():
    """Get all available tags."""
    with get_db_ctx() as db:
        rows = db.execute("SELECT * FROM feedback_tags ORDER BY count DESC").fetchall()
        return [dict(row) for row in rows]


def get_linked_feedback(building_id):
    """Get all feedback entries that involve this building in their trace."""
    with get_db_ctx() as db:
        # Direct match
        direct = db.execute("""
            SELECT * FROM feedback WHERE building_id = ?
            ORDER BY created_at DESC
        """, (building_id,)).fetchall()

        # Also search trace snapshots for this building ID
        in_trace = db.execute("""
            SELECT * FROM feedback
            WHERE trace_snapshot LIKE ?
            AND building_id != ?
            ORDER BY created_at DESC LIMIT 20
        """, (f'%{building_id}%', building_id)).fetchall()

        return {
            "direct": [dict(r) for r in direct],
            "in_trace": [dict(r) for r in in_trace],
        }


# ═══════════════════════════════════════════════════════════════════════════════
# Ticket System
# ═══════════════════════════════════════════════════════════════════════════════


def _compute_issue_hash(issue):
    """Deterministic hash for matching issues across save reloads."""
    key = f"{issue.get('building_id', '')}|{issue.get('category', '')}|{issue.get('recipe', '')}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def _compute_priority(issue):
    """Calculate priority score from impact metrics.

    Higher score = more urgent. Factors:
    - Severity (error=300, warning=200, info=100)
    - Items/min deficit
    - Belt overflow
    """
    score = 0
    severity_score = {"error": 300, "warning": 200, "info": 100}
    score += severity_score.get(issue.get("severity"), 0)

    expected = issue.get("expected_input", 0)
    actual = issue.get("actual_input", 0)
    if expected and actual:
        deficit = expected - actual
        if deficit > 0:
            score += int(deficit * 10)

    flow = issue.get("flow_rate", 0)
    max_rate = issue.get("max_rate", 0)
    if flow and max_rate and flow > max_rate:
        score += int((flow - max_rate) * 5)

    return score


def create_tickets_from_issues(issues, session_name=None):
    """Create or update tickets from current issue list."""
    with get_db_ctx() as db:
        created = 0
        updated = 0
        for issue in issues:
            issue_hash = _compute_issue_hash(issue)
            priority = _compute_priority(issue)

            existing = db.execute(
                "SELECT id, status FROM tickets WHERE issue_hash = ? AND status != 'RESOLVED'",
                (issue_hash,)
            ).fetchone()

            if existing:
                db.execute("""
                    UPDATE tickets SET
                        updated_at = ?, priority = ?, session_name = ?
                    WHERE id = ?
                """, (time.time(), priority, session_name, existing['id']))
                updated += 1
            else:
                items_lost = 0
                if issue.get("expected_input") and issue.get("actual_input"):
                    items_lost = issue["expected_input"] - issue["actual_input"]

                db.execute("""
                    INSERT INTO tickets (
                        created_at, updated_at, status, priority, priority_reason,
                        session_name, building_id, building_name, recipe,
                        issue_category, issue_title, issue_severity, issue_hash,
                        items_per_min_lost, dominator_id, root_cause
                    ) VALUES (?, ?, 'OPEN', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    time.time(), time.time(), priority,
                    f"Score: {priority}",
                    session_name,
                    issue.get("building_id"),
                    issue.get("building_name"),
                    issue.get("recipe"),
                    issue.get("category"),
                    issue.get("title", issue.get("category", "Unknown")),
                    issue.get("severity"),
                    issue_hash,
                    max(items_lost, 0),
                    issue.get("dominator_id"),
                    issue.get("root_cause"),
                ))
                created += 1

        return {"created": created, "updated": updated}


def auto_resolve_tickets(current_issues, session_name=None):
    """Auto-resolve tickets whose issues no longer appear in current scan."""
    current_hashes = {_compute_issue_hash(i) for i in current_issues}

    with get_db_ctx() as db:
        open_tickets = db.execute(
            "SELECT id, issue_hash FROM tickets WHERE status IN ('OPEN', 'IN_PROGRESS')"
        ).fetchall()

        resolved_count = 0
        for ticket in open_tickets:
            if ticket['issue_hash'] not in current_hashes:
                db.execute("""
                    UPDATE tickets SET
                        status = 'RESOLVED', resolved_at = ?, updated_at = ?,
                        auto_resolved = 1,
                        resolution_note = 'Auto-resolved: issue no longer present in save'
                    WHERE id = ?
                """, (time.time(), time.time(), ticket['id']))
                resolved_count += 1

        return resolved_count


def get_tickets(status=None, limit=100, offset=0):
    """Query tickets with optional status filter."""
    with get_db_ctx() as db:
        conditions = []
        params = []

        if status:
            conditions.append("status = ?")
            params.append(status)

        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        params.extend([limit, offset])

        rows = db.execute(f"""
            SELECT * FROM tickets {where}
            ORDER BY priority DESC, created_at DESC
            LIMIT ? OFFSET ?
        """, params).fetchall()

        return [dict(row) for row in rows]


def update_ticket(ticket_id, status=None, assigned_to=None, resolution_note=None):
    """Update a ticket's status or assignment."""
    with get_db_ctx() as db:
        updates = ["updated_at = ?"]
        params = [time.time()]

        if status:
            updates.append("status = ?")
            params.append(status)
            if status == "RESOLVED":
                updates.append("resolved_at = ?")
                params.append(time.time())

        if assigned_to is not None:
            updates.append("assigned_to = ?")
            params.append(assigned_to)

        if resolution_note is not None:
            updates.append("resolution_note = ?")
            params.append(resolution_note)

        params.append(ticket_id)
        db.execute(f"""
            UPDATE tickets SET {', '.join(updates)} WHERE id = ?
        """, params)

        return db.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()


def get_ticket_stats():
    """Get ticket statistics."""
    with get_db_ctx() as db:
        total = db.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]

        statuses = {}
        for row in db.execute("SELECT status, COUNT(*) as cnt FROM tickets GROUP BY status"):
            statuses[row['status']] = row['cnt']

        # Top categories
        categories = {}
        for row in db.execute("""
            SELECT issue_category, COUNT(*) as cnt FROM tickets
            WHERE status IN ('OPEN', 'IN_PROGRESS')
            GROUP BY issue_category ORDER BY cnt DESC LIMIT 10
        """):
            categories[row['issue_category']] = row['cnt']

        avg_priority = db.execute(
            "SELECT AVG(priority) FROM tickets WHERE status IN ('OPEN', 'IN_PROGRESS')"
        ).fetchone()[0] or 0

        return {
            "total": total,
            "statuses": statuses,
            "open_categories": categories,
            "avg_priority": round(avg_priority),
        }
