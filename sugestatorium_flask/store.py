from __future__ import annotations

import csv
import hashlib
import io
import json
import random
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CSV_FIELDS = [
    "pk",
    "sk",
    "currentImplementationCode",
    "currentImplementationDescription",
    "groupedIssuesId",
    "gsi1pk",
    "gsi1sk",
    "impactOnUsers",
    "recommendedFixCode",
    "recommendedFixDescription",
    "reportId",
    "ruleId",
    "status",
    "tenantId",
    "whyThisFails",
]
REVIEW_STATUSES = ["unreviewed", "good", "acceptable", "needs-work", "bad", "discuss"]
REVIEW_ACTIONS = ["none", "prompt-fix", "implementation-fix", "both"]
FRONTMATTER_PATTERN = re.compile(r"^---\n(.*?)\n---\n?(.*)$", re.DOTALL)


def initialize_storage(root_path: Path) -> None:
    storage_path = root_path / "storage"
    (storage_path / "imports").mkdir(parents=True, exist_ok=True)
    (storage_path / "prompt_snapshots").mkdir(parents=True, exist_ok=True)
    db = get_connection(root_path)
    db.executescript(
        """
        PRAGMA foreign_keys = ON;

        CREATE TABLE IF NOT EXISTS runs (
            id TEXT PRIMARY KEY,
            source_filename TEXT NOT NULL,
            imported_at TEXT NOT NULL,
            prompt_id TEXT NOT NULL,
            prompt_name TEXT NOT NULL,
            prompt_model TEXT NOT NULL,
            prompt_temperature REAL NOT NULL,
            prompt_notes TEXT NOT NULL,
            prompt_snapshot_path TEXT NOT NULL,
            note TEXT NOT NULL,
            row_count INTEGER NOT NULL,
            rules_count INTEGER NOT NULL,
            artifact_path TEXT NOT NULL,
            artifact_hash TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS suggestions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
            row_id TEXT NOT NULL,
            pk TEXT NOT NULL,
            sk TEXT NOT NULL,
            current_implementation_code TEXT NOT NULL,
            current_implementation_description TEXT NOT NULL,
            grouped_issues_id TEXT NOT NULL,
            gsi1pk TEXT NOT NULL,
            gsi1sk TEXT NOT NULL,
            impact_on_users TEXT NOT NULL,
            recommended_fix_code TEXT NOT NULL,
            recommended_fix_description TEXT NOT NULL,
            report_id TEXT NOT NULL,
            rule_id TEXT NOT NULL,
            source_status TEXT NOT NULL,
            tenant_id TEXT NOT NULL,
            why_this_fails TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            UNIQUE(run_id, row_id)
        );

        CREATE TABLE IF NOT EXISTS reviews (
            suggestion_id INTEGER PRIMARY KEY REFERENCES suggestions(id) ON DELETE CASCADE,
            review_status TEXT NOT NULL DEFAULT 'unreviewed',
            score INTEGER,
            comment TEXT NOT NULL DEFAULT '',
            action TEXT NOT NULL DEFAULT 'none',
            resolved INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS review_tags (
            suggestion_id INTEGER NOT NULL REFERENCES suggestions(id) ON DELETE CASCADE,
            tag TEXT NOT NULL,
            PRIMARY KEY (suggestion_id, tag)
        );

        CREATE TABLE IF NOT EXISTS artifacts (
            hash TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            relative_path TEXT NOT NULL,
            original_name TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_suggestions_run_id ON suggestions(run_id);
        CREATE INDEX IF NOT EXISTS idx_suggestions_rule_id ON suggestions(rule_id);
        CREATE INDEX IF NOT EXISTS idx_reviews_status ON reviews(review_status);
        CREATE INDEX IF NOT EXISTS idx_runs_imported_at ON runs(imported_at DESC);
        """
    )
    db.commit()
    _migrate_legacy_files(root_path, db)
    db.close()


def get_connection(root_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(root_path / "storage" / "sugestatorium.sqlite3")
    connection.row_factory = sqlite3.Row
    return connection


def list_prompts(root_path: Path) -> list[dict[str, Any]]:
    prompts: list[dict[str, Any]] = []
    for file_path in sorted((root_path / "prompts").glob("*.md"), reverse=True):
        prompts.append(read_prompt_file(file_path))
    return prompts


def get_prompt(root_path: Path, prompt_id: str) -> dict[str, Any] | None:
    for prompt in list_prompts(root_path):
        if prompt["id"] == prompt_id:
            return prompt
    return None


def create_prompt(root_path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    prompt_id = (
        slugify(str(payload["name"]))
        or f"prompt-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    )
    file_path = root_path / "prompts" / f"{prompt_id}.md"
    suffix = 1
    while file_path.exists():
        file_path = root_path / "prompts" / f"{prompt_id}-{suffix}.md"
        suffix += 1
    prompt_id = file_path.stem
    content = (
        "---\n"
        f"id: {prompt_id}\n"
        f"name: {str(payload['name']).strip()}\n"
        f"model: {str(payload['model']).strip()}\n"
        f"temperature: {float(payload['temperature'])}\n"
        f"createdAt: {datetime.now(timezone.utc).date().isoformat()}\n"
        f"notes: {str(payload.get('notes', '')).strip()}\n"
        "---\n\n"
        f"{str(payload['content']).strip()}\n"
    )
    file_path.write_text(content, encoding="utf-8")
    return read_prompt_file(file_path)


def list_workspace_csv_files(root_path: Path) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    for file_path in root_path.glob("*.csv"):
        stat = file_path.stat()
        files.append(
            {
                "name": file_path.name,
                "path": str(file_path),
                "size": stat.st_size,
                "updated_at": datetime.fromtimestamp(
                    stat.st_mtime, tz=timezone.utc
                ).isoformat(),
            }
        )
    return sorted(files, key=lambda item: item["updated_at"], reverse=True)


def import_run(
    root_path: Path, source_filename: str, raw_bytes: bytes, prompt_id: str, note: str
) -> str:
    prompt = get_prompt(root_path, prompt_id)
    if not prompt:
        raise ValueError("Prompt not found.")

    artifact_hash, artifact_rel_path = store_artifact(
        root_path, "import", source_filename, raw_bytes
    )
    rows = parse_csv_rows(raw_bytes)
    run_id = create_run_id(source_filename)
    imported_at = now_iso()
    prompt_snapshot_path = snapshot_prompt(
        root_path, run_id, prompt["file_name"], prompt["raw"]
    )
    rule_count = len({row["ruleId"] for row in rows})

    db = get_connection(root_path)
    db.execute(
        """
        INSERT INTO runs (
            id, source_filename, imported_at, prompt_id, prompt_name, prompt_model,
            prompt_temperature, prompt_notes, prompt_snapshot_path, note, row_count,
            rules_count, artifact_path, artifact_hash
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            source_filename,
            imported_at,
            prompt["id"],
            prompt["name"],
            prompt["model"],
            prompt["temperature"],
            prompt.get("notes", ""),
            prompt_snapshot_path,
            note.strip(),
            len(rows),
            rule_count,
            artifact_rel_path,
            artifact_hash,
        ),
    )

    for index, row in enumerate(rows, start=1):
        row_id = row.get("sk") or f"{row['ruleId']}-{index}"
        content_hash = sha256_text(
            "\n".join(row.get(field, "") for field in CSV_FIELDS)
        )
        cursor = db.execute(
            """
            INSERT INTO suggestions (
                run_id, row_id, pk, sk, current_implementation_code,
                current_implementation_description, grouped_issues_id, gsi1pk, gsi1sk,
                impact_on_users, recommended_fix_code, recommended_fix_description,
                report_id, rule_id, source_status, tenant_id, why_this_fails, content_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                row_id,
                row["pk"],
                row["sk"],
                row["currentImplementationCode"],
                row["currentImplementationDescription"],
                row["groupedIssuesId"],
                row["gsi1pk"],
                row["gsi1sk"],
                row["impactOnUsers"],
                row["recommendedFixCode"],
                row["recommendedFixDescription"],
                row["reportId"],
                row["ruleId"],
                row["status"],
                row["tenantId"],
                row["whyThisFails"],
                content_hash,
            ),
        )
        db.execute(
            "INSERT INTO reviews (suggestion_id, review_status, score, comment, action, resolved, updated_at) VALUES (?, 'unreviewed', NULL, '', 'none', 0, NULL)",
            (cursor.lastrowid,),
        )

    db.commit()
    db.close()
    return run_id


def get_dashboard(root_path: Path) -> dict[str, Any]:
    runs = list_runs(root_path)
    return {
        "prompts": list_prompts(root_path),
        "runs": runs,
        "workspace_csv_files": list_workspace_csv_files(root_path),
        "total_suggestions": sum(run["row_count"] for run in runs),
        "reviewed_suggestions": sum(run["reviewed_count"] for run in runs),
        "average_score": average(
            [run["average_score"] for run in runs if run["average_score"] is not None]
        ),
    }


def list_runs(root_path: Path) -> list[dict[str, Any]]:
    db = get_connection(root_path)
    rows = db.execute(
        """
        SELECT
            r.*,
            SUM(CASE WHEN reviews.review_status != 'unreviewed' THEN 1 ELSE 0 END) AS reviewed_count,
            AVG(reviews.score) AS average_score,
            SUM(CASE WHEN reviews.action IN ('prompt-fix', 'both') THEN 1 ELSE 0 END) AS prompt_fix_count,
            SUM(CASE WHEN reviews.action IN ('implementation-fix', 'both') THEN 1 ELSE 0 END) AS implementation_fix_count
        FROM runs r
        JOIN suggestions ON suggestions.run_id = r.id
        JOIN reviews ON reviews.suggestion_id = suggestions.id
        GROUP BY r.id
        ORDER BY r.imported_at DESC
        """
    ).fetchall()
    db.close()
    return [dict(row) for row in rows]


def get_run(root_path: Path, run_id: str) -> dict[str, Any] | None:
    db = get_connection(root_path)
    row = db.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    db.close()
    return dict(row) if row else None


def get_run_region(
    root_path: Path, run_id: str, filters: dict[str, str]
) -> dict[str, Any] | None:
    run = get_run(root_path, run_id)
    if not run:
        return None
    items = query_suggestions(root_path, run_id=run_id, filters=filters)
    reviewed_count = sum(1 for item in items if item["review_status"] != "unreviewed")
    return {
        "run": run,
        "items": items,
        "rule_options": sorted(
            {item["rule_id"] for item in items}
            | set(_get_run_rule_ids(root_path, run_id))
        ),
        "reviewed_count": reviewed_count,
        "filtered_count": len(items),
        "filters": filters,
    }


def get_insights(root_path: Path) -> dict[str, Any]:
    runs = list_runs(root_path)
    db = get_connection(root_path)
    review_distribution = [
        dict(row)
        for row in db.execute(
            "SELECT review_status AS status, COUNT(*) AS count FROM reviews GROUP BY review_status ORDER BY count DESC"
        ).fetchall()
    ]
    prompt_breakdown = [
        dict(row)
        for row in db.execute(
            """
            SELECT
                runs.prompt_id,
                runs.prompt_name,
                COUNT(DISTINCT runs.id) AS runs,
                AVG(reviews.score) AS average_score,
                SUM(CASE WHEN reviews.review_status != 'unreviewed' THEN 1 ELSE 0 END) AS reviewed_suggestions
            FROM runs
            JOIN suggestions ON suggestions.run_id = runs.id
            JOIN reviews ON reviews.suggestion_id = suggestions.id
            GROUP BY runs.prompt_id, runs.prompt_name
            ORDER BY runs DESC, runs.prompt_name ASC
            """
        ).fetchall()
    ]
    top_rules = [
        dict(row)
        for row in db.execute(
            "SELECT rule_id, COUNT(*) AS count FROM suggestions GROUP BY rule_id ORDER BY count DESC LIMIT 8"
        ).fetchall()
    ]
    db.close()

    return {
        "total_runs": len(runs),
        "total_suggestions": sum(run["row_count"] for run in runs),
        "reviewed_suggestions": sum(run["reviewed_count"] for run in runs),
        "average_score": average(
            [run["average_score"] for run in runs if run["average_score"] is not None]
        ),
        "review_distribution": review_distribution,
        "prompt_breakdown": prompt_breakdown,
        "top_rules": top_rules,
        "recent_runs": runs[:6],
    }


def get_global_review_region(
    root_path: Path, filters: dict[str, str], reviewed_only: bool = True
) -> dict[str, Any]:
    items = query_suggestions(root_path, filters=filters, reviewed_only=reviewed_only)
    return {
        "items": items,
        "filters": filters,
        "rule_options": sorted(
            {
                item["rule_id"]
                for item in query_suggestions(root_path, reviewed_only=reviewed_only)
            }
        ),
        "prompt_options": sorted(
            {
                item["prompt_id"]
                for item in query_suggestions(root_path, reviewed_only=reviewed_only)
            }
        ),
        "match_count": len(items),
    }


def query_suggestions(
    root_path: Path,
    *,
    run_id: str | None = None,
    filters: dict[str, str] | None = None,
    reviewed_only: bool = False,
) -> list[dict[str, Any]]:
    filters = filters or {}
    clauses = []
    values: list[Any] = []

    if run_id:
        clauses.append("suggestions.run_id = ?")
        values.append(run_id)
    if reviewed_only:
        clauses.append("reviews.review_status != 'unreviewed'")
    if filters.get("rule") and filters["rule"] != "all":
        clauses.append("suggestions.rule_id = ?")
        values.append(filters["rule"])
    if filters.get("status") and filters["status"] != "all":
        clauses.append("reviews.review_status = ?")
        values.append(filters["status"])
    if filters.get("action") and filters["action"] != "all":
        clauses.append("reviews.action = ?")
        values.append(filters["action"])
    if filters.get("prompt") and filters["prompt"] != "all":
        clauses.append("runs.prompt_id = ?")
        values.append(filters["prompt"])
    if filters.get("score") and filters["score"] != "all":
        if filters["score"] == "unscored":
            clauses.append("reviews.score IS NULL")
        else:
            clauses.append("reviews.score = ?")
            values.append(int(filters["score"]))
    if filters.get("q"):
        query = f"%{filters['q'].strip().lower()}%"
        clauses.append(
            "("
            + " OR ".join(
                [
                    "LOWER(suggestions.rule_id) LIKE ?",
                    "LOWER(suggestions.current_implementation_description) LIKE ?",
                    "LOWER(suggestions.recommended_fix_description) LIKE ?",
                    "LOWER(suggestions.why_this_fails) LIKE ?",
                    "LOWER(COALESCE(reviews.comment, '')) LIKE ?",
                    "LOWER(runs.source_filename) LIKE ?",
                    "LOWER(runs.prompt_name) LIKE ?",
                ]
            )
            + ")"
        )
        values.extend([query] * 7)

    where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    db = get_connection(root_path)
    rows = db.execute(
        f"""
        SELECT
            suggestions.id,
            suggestions.run_id,
            suggestions.row_id,
            suggestions.pk,
            suggestions.sk,
            suggestions.current_implementation_code,
            suggestions.current_implementation_description,
            suggestions.grouped_issues_id,
            suggestions.gsi1pk,
            suggestions.gsi1sk,
            suggestions.impact_on_users,
            suggestions.recommended_fix_code,
            suggestions.recommended_fix_description,
            suggestions.report_id,
            suggestions.rule_id,
            suggestions.source_status,
            suggestions.tenant_id,
            suggestions.why_this_fails,
            reviews.review_status,
            reviews.score,
            reviews.comment,
            reviews.action,
            reviews.resolved,
            reviews.updated_at,
            runs.source_filename,
            runs.imported_at,
            runs.prompt_id,
            runs.prompt_name,
            GROUP_CONCAT(review_tags.tag, ', ') AS tags
        FROM suggestions
        JOIN reviews ON reviews.suggestion_id = suggestions.id
        JOIN runs ON runs.id = suggestions.run_id
        LEFT JOIN review_tags ON review_tags.suggestion_id = suggestions.id
        {where_clause}
        GROUP BY suggestions.id
        ORDER BY runs.imported_at DESC, suggestions.rule_id ASC, suggestions.id ASC
        """,
        values,
    ).fetchall()
    db.close()
    items = []
    for row in rows:
        item = dict(row)
        item["tags"] = [
            tag.strip() for tag in (item.get("tags") or "").split(",") if tag.strip()
        ]
        items.append(item)
    return items


def get_suggestion_detail(root_path: Path, suggestion_id: int) -> dict[str, Any] | None:
    db = get_connection(root_path)
    row = db.execute(
        """
        SELECT
            suggestions.*,
            reviews.review_status,
            reviews.score,
            reviews.comment,
            reviews.action,
            reviews.resolved,
            reviews.updated_at,
            runs.source_filename,
            runs.imported_at,
            runs.prompt_id,
            runs.prompt_name,
            GROUP_CONCAT(review_tags.tag, ', ') AS tags
        FROM suggestions
        JOIN reviews ON reviews.suggestion_id = suggestions.id
        JOIN runs ON runs.id = suggestions.run_id
        LEFT JOIN review_tags ON review_tags.suggestion_id = suggestions.id
        WHERE suggestions.id = ?
        GROUP BY suggestions.id
        """,
        (suggestion_id,),
    ).fetchone()
    db.close()
    if not row:
        return None
    item = dict(row)
    item["tags"] = [
        tag.strip() for tag in (item.get("tags") or "").split(",") if tag.strip()
    ]
    return item


def update_review(root_path: Path, suggestion_id: int, payload: dict[str, Any]) -> None:
    db = get_connection(root_path)
    field = payload.get("field", "")
    value = payload.get("value")
    now = now_iso()

    if field == "review_status" and value in REVIEW_STATUSES:
        db.execute(
            "UPDATE reviews SET review_status = ?, updated_at = ? WHERE suggestion_id = ?",
            (value, now, suggestion_id),
        )
    elif field == "score":
        score = None if value in (None, "", "unscored") else int(value)
        db.execute(
            "UPDATE reviews SET score = ?, updated_at = ? WHERE suggestion_id = ?",
            (score, now, suggestion_id),
        )
    elif field == "action" and value in REVIEW_ACTIONS:
        db.execute(
            "UPDATE reviews SET action = ?, updated_at = ? WHERE suggestion_id = ?",
            (value, now, suggestion_id),
        )
    elif field == "resolved":
        db.execute(
            "UPDATE reviews SET resolved = ?, updated_at = ? WHERE suggestion_id = ?",
            (
                1 if str(value).lower() in {"1", "true", "on", "yes"} else 0,
                now,
                suggestion_id,
            ),
        )
    elif field == "comment":
        db.execute(
            "UPDATE reviews SET comment = ?, updated_at = ? WHERE suggestion_id = ?",
            (str(value or ""), now, suggestion_id),
        )
    elif field == "tags":
        tags = [tag.strip() for tag in str(value or "").split(",") if tag.strip()]
        db.execute("DELETE FROM review_tags WHERE suggestion_id = ?", (suggestion_id,))
        for tag in tags:
            db.execute(
                "INSERT OR IGNORE INTO review_tags (suggestion_id, tag) VALUES (?, ?)",
                (suggestion_id, tag),
            )
        db.execute(
            "UPDATE reviews SET updated_at = ? WHERE suggestion_id = ?",
            (now, suggestion_id),
        )
    else:
        db.close()
        raise ValueError("Unsupported review update.")

    db.commit()
    db.close()


def search(root_path: Path, query: str) -> list[dict[str, str]]:
    normalized = query.strip().lower()
    if not normalized:
        return []
    runs = list_runs(root_path)
    prompts = list_prompts(root_path)
    rule_rows = query_suggestions(root_path, reviewed_only=False)
    rule_ids = sorted({item["rule_id"] for item in rule_rows})
    results: list[dict[str, str]] = []

    for run in runs:
        haystack = f"{run['source_filename']} {run['prompt_name']} {run['prompt_id']} {run['note']}".lower()
        if normalized in haystack:
            results.append(
                {
                    "label": run["source_filename"],
                    "meta": f"{run['prompt_name']} | {run['reviewed_count']}/{run['row_count']} reviewed",
                    "href": f"/runs/{run['id']}",
                    "kind": "run",
                }
            )
    for prompt in prompts:
        haystack = f"{prompt['id']} {prompt['name']} {prompt['model']} {prompt.get('notes', '')}".lower()
        if normalized in haystack:
            results.append(
                {
                    "label": prompt["name"],
                    "meta": f"{prompt['model']} | temp {prompt['temperature']}",
                    "href": f"/prompts?prompt_id={prompt['id']}",
                    "kind": "prompt",
                }
            )
    for rule_id in rule_ids:
        if normalized in rule_id.lower():
            results.append(
                {
                    "label": rule_id,
                    "meta": "Review matching rows across imported batches",
                    "href": f"/insights/reviews?rule={rule_id}",
                    "kind": "rule",
                }
            )
    for status in REVIEW_STATUSES:
        if normalized in status:
            results.append(
                {
                    "label": status,
                    "meta": "Open all rows matching this review status",
                    "href": f"/insights/reviews?status={status}",
                    "kind": "review-status",
                }
            )
    return results[:8]


def parse_filters(args: dict[str, Any]) -> dict[str, str]:
    return {
        "q": str(args.get("q", "")).strip(),
        "rule": str(args.get("rule", "all")).strip() or "all",
        "status": str(args.get("status", "all")).strip() or "all",
        "action": str(args.get("action", "all")).strip() or "all",
        "score": str(args.get("score", "all")).strip() or "all",
        "prompt": str(args.get("prompt", "all")).strip() or "all",
    }


def read_prompt_file(file_path: Path) -> dict[str, Any]:
    raw = file_path.read_text(encoding="utf-8")
    match = FRONTMATTER_PATTERN.match(raw)
    if not match:
        raise ValueError(f"Prompt file {file_path.name} has invalid frontmatter.")
    frontmatter, body = match.groups()
    metadata: dict[str, Any] = {}
    for line in frontmatter.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip()
    metadata["temperature"] = float(metadata.get("temperature", 0))
    return {
        "id": metadata.get("id") or file_path.stem,
        "name": metadata.get("name") or file_path.stem,
        "model": metadata.get("model") or "unknown",
        "temperature": metadata.get("temperature", 0.0),
        "created_at": metadata.get("createdAt", ""),
        "createdAt": metadata.get("createdAt", ""),
        "notes": metadata.get("notes", ""),
        "content": body.strip(),
        "file_name": file_path.name,
        "raw": raw,
    }


def parse_csv_rows(raw_bytes: bytes) -> list[dict[str, str]]:
    text = raw_bytes.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    rows: list[dict[str, str]] = []
    for row in reader:
        normalized = {field: row.get(field, "") or "" for field in CSV_FIELDS}
        rows.append(normalized)
    return rows


def store_artifact(
    root_path: Path, kind: str, original_name: str, raw_bytes: bytes
) -> tuple[str, str]:
    digest = hashlib.sha256(raw_bytes).hexdigest()
    extension = Path(original_name).suffix or ".bin"
    relative_path = Path("storage") / "imports" / f"{digest}{extension}"
    full_path = root_path / relative_path
    if not full_path.exists():
        full_path.write_bytes(raw_bytes)
    db = get_connection(root_path)
    db.execute(
        "INSERT OR IGNORE INTO artifacts (hash, kind, relative_path, original_name, size_bytes, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (digest, kind, str(relative_path), original_name, len(raw_bytes), now_iso()),
    )
    db.commit()
    db.close()
    return digest, str(relative_path)


def snapshot_prompt(
    root_path: Path, run_id: str, prompt_file_name: str, raw_prompt: str
) -> str:
    relative_path = (
        Path("storage") / "prompt_snapshots" / f"{run_id}-{prompt_file_name}"
    )
    (root_path / relative_path).write_text(raw_prompt, encoding="utf-8")
    return str(relative_path)


def create_run_id(source_filename: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    suffix = random.randint(1000, 9999)
    return f"run-{stamp}-{slugify(source_filename)}-{suffix}"


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:80]


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def average(values: list[float | int]) -> float | None:
    if not values:
        return None
    return sum(float(value) for value in values) / len(values)


def _get_run_rule_ids(root_path: Path, run_id: str) -> list[str]:
    db = get_connection(root_path)
    rows = db.execute(
        "SELECT DISTINCT rule_id FROM suggestions WHERE run_id = ? ORDER BY rule_id ASC",
        (run_id,),
    ).fetchall()
    db.close()
    return [row[0] for row in rows]


def _migrate_legacy_files(root_path: Path, db: sqlite3.Connection) -> None:
    existing = db.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
    if existing:
        return
    legacy_runs = sorted((root_path / "storage" / "runs").glob("*.json"))
    if not legacy_runs:
        return
    for run_file in legacy_runs:
        run = json.loads(run_file.read_text(encoding="utf-8"))
        reviews_path = root_path / "storage" / "reviews" / run_file.name
        reviews = (
            json.loads(reviews_path.read_text(encoding="utf-8"))
            if reviews_path.exists()
            else {}
        )
        db.execute(
            """
            INSERT OR IGNORE INTO runs (
                id, source_filename, imported_at, prompt_id, prompt_name, prompt_model,
                prompt_temperature, prompt_notes, prompt_snapshot_path, note, row_count,
                rules_count, artifact_path, artifact_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run["id"],
                run["sourceFileName"],
                run["importedAt"],
                run["promptId"],
                run["promptName"],
                "unknown",
                0.0,
                "",
                "",
                run.get("note", ""),
                run["rowCount"],
                run["rulesCount"],
                "",
                "",
            ),
        )
        for row in run["rows"]:
            row_id = row.get("rowId") or row.get("sk")
            cursor = db.execute(
                """
                INSERT OR IGNORE INTO suggestions (
                    run_id, row_id, pk, sk, current_implementation_code,
                    current_implementation_description, grouped_issues_id, gsi1pk, gsi1sk,
                    impact_on_users, recommended_fix_code, recommended_fix_description,
                    report_id, rule_id, source_status, tenant_id, why_this_fails, content_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run["id"],
                    row_id,
                    row["pk"],
                    row["sk"],
                    row["currentImplementationCode"],
                    row["currentImplementationDescription"],
                    row["groupedIssuesId"],
                    row["gsi1pk"],
                    row["gsi1sk"],
                    row["impactOnUsers"],
                    row["recommendedFixCode"],
                    row["recommendedFixDescription"],
                    row["reportId"],
                    row["ruleId"],
                    row["status"],
                    row["tenantId"],
                    row["whyThisFails"],
                    sha256_text(
                        "\n".join(str(row.get(field, "")) for field in row.keys())
                    ),
                ),
            )
            review = reviews.get(row_id, {})
            suggestion_id = (
                cursor.lastrowid
                or db.execute(
                    "SELECT id FROM suggestions WHERE run_id = ? AND row_id = ?",
                    (run["id"], row_id),
                ).fetchone()[0]
            )
            db.execute(
                "INSERT OR REPLACE INTO reviews (suggestion_id, review_status, score, comment, action, resolved, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    suggestion_id,
                    review.get("reviewStatus", "unreviewed"),
                    review.get("score"),
                    review.get("comment", ""),
                    review.get("action", "none"),
                    1 if review.get("resolved") else 0,
                    review.get("updatedAt"),
                ),
            )
            for tag in review.get("tags", []):
                db.execute(
                    "INSERT OR IGNORE INTO review_tags (suggestion_id, tag) VALUES (?, ?)",
                    (suggestion_id, tag),
                )
    db.commit()
