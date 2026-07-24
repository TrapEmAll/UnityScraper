"""GPD inventory, profile comparison, and snapshot-first Xenia migration."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

from app_paths import DATABASE_PATH
from database_migrations import ensure_application_schema
from gpd_parser import GpdReport, parse_gpd
from profile_manager import PROFILE_ID_RE, ProfileSaveManager, utc_now
from xenia_bridge import (
    MigrationPlan,
    build_migration_plan,
    execute_migration_plan,
    find_xenia_content_root,
)


class ProfileIntelligenceError(RuntimeError):
    """Raised when an intelligence or migration operation is invalid."""


class ProfileIntelligenceService:
    """Persist read-only GPD facts and orchestrate safe migration previews."""

    def __init__(
        self,
        db_path: str | Path = DATABASE_PATH,
        profile_manager: ProfileSaveManager | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        backup_root = self.db_path.parent / "profile_backups"
        self.profile_manager = profile_manager or ProfileSaveManager(
            db_path=db_path,
            backup_root=backup_root,
        )
        with self._connect() as connection:
            ensure_application_schema(connection)

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def import_gpd(
        self,
        path: str | Path,
        *,
        profile_id: str = "",
        title_id: str = "",
    ) -> int:
        normalized_profile = profile_id.strip().upper()
        if normalized_profile and not PROFILE_ID_RE.fullmatch(normalized_profile):
            raise ProfileIntelligenceError(f"Invalid profile ID: {profile_id}")
        report = parse_gpd(path, title_id=title_id)
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO profile_gpd_files(
                    profile_id, titleid, source_path, sha256, size, version,
                    entry_count, achievement_count, unlocked_count,
                    gamerscore_earned, gamerscore_possible, parsed_at, status,
                    warnings_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'parsed', ?)
                ON CONFLICT(source_path) DO UPDATE SET
                    profile_id=excluded.profile_id,
                    titleid=excluded.titleid,
                    sha256=excluded.sha256,
                    size=excluded.size,
                    version=excluded.version,
                    entry_count=excluded.entry_count,
                    achievement_count=excluded.achievement_count,
                    unlocked_count=excluded.unlocked_count,
                    gamerscore_earned=excluded.gamerscore_earned,
                    gamerscore_possible=excluded.gamerscore_possible,
                    parsed_at=excluded.parsed_at,
                    status=excluded.status,
                    warnings_json=excluded.warnings_json
                """,
                (
                    normalized_profile,
                    report.title_id,
                    str(report.path.resolve()),
                    report.sha256,
                    report.size,
                    report.version,
                    report.entry_count,
                    len(report.achievements),
                    report.unlocked_count,
                    report.gamerscore_earned,
                    report.gamerscore_possible,
                    utc_now(),
                    json.dumps(report.warnings),
                ),
            )
            row = connection.execute(
                "SELECT id FROM profile_gpd_files WHERE source_path=?",
                (str(report.path.resolve()),),
            ).fetchone()
            if row is None:
                if cursor.lastrowid is None:
                    raise ProfileIntelligenceError("GPD import was not recorded")
                gpd_id = int(cursor.lastrowid)
            else:
                gpd_id = int(row["id"])
            connection.execute(
                "DELETE FROM profile_achievements WHERE gpd_file_id=?", (gpd_id,)
            )
            connection.executemany(
                """
                INSERT INTO profile_achievements(
                    gpd_file_id, achievement_id, title, locked_description,
                    unlocked_description, gamerscore, unlock_state, unlocked_at,
                    image_id, entry_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    (
                        gpd_id,
                        item.achievement_id,
                        item.title,
                        item.locked_description,
                        item.unlocked_description,
                        item.gamerscore,
                        item.state,
                        item.unlocked_at,
                        item.image_id,
                        item.entry_id,
                    )
                    for item in report.achievements
                ),
            )
        return gpd_id

    def scan_gpd_directory(
        self, root: str | Path, *, profile_id: str = ""
    ) -> dict[str, Any]:
        directory = Path(root).expanduser().resolve()
        if not directory.is_dir():
            raise FileNotFoundError(directory)
        imported: list[int] = []
        errors: list[str] = []
        for candidate in directory.rglob("*"):
            if not candidate.is_file():
                continue
            try:
                with candidate.open("rb") as handle:
                    if handle.read(4) != b"XDBF":
                        continue
                imported.append(self.import_gpd(candidate, profile_id=profile_id))
            except (OSError, ValueError) as exc:
                errors.append(f"{candidate}: {exc}")
        return {"imported": len(imported), "errors": errors}

    def list_gpd_files(self, profile_id: str = "") -> list[dict[str, Any]]:
        with self._connect() as connection:
            if profile_id:
                rows = connection.execute(
                    """
                    SELECT * FROM profile_gpd_files
                    WHERE profile_id=? ORDER BY titleid, source_path
                    """,
                    (profile_id,),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM profile_gpd_files ORDER BY parsed_at DESC"
                ).fetchall()
        return [dict(row) for row in rows]

    def list_achievements(
        self,
        gpd_file_id: int,
        *,
        state: str = "",
        search: str = "",
    ) -> list[dict[str, Any]]:
        clauses = ["gpd_file_id=?"]
        values: list[Any] = [gpd_file_id]
        if state:
            clauses.append("unlock_state=?")
            values.append(state)
        if search.strip():
            clauses.append(
                "(title LIKE ? OR locked_description LIKE ? "
                "OR unlocked_description LIKE ?)"
            )
            term = f"%{search.strip()}%"
            values.extend((term, term, term))
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM profile_achievements
                WHERE {' AND '.join(clauses)}
                ORDER BY achievement_id
                """,
                values,
            ).fetchall()
        return [dict(row) for row in rows]

    def compare_profiles(self, left_profile_id: str, right_profile_id: str) -> dict[str, Any]:
        left = left_profile_id.strip().upper()
        right = right_profile_id.strip().upper()
        if left == right:
            raise ProfileIntelligenceError("Choose two different profiles")
        if not PROFILE_ID_RE.fullmatch(left) or not PROFILE_ID_RE.fullmatch(right):
            raise ProfileIntelligenceError("Both profile IDs must be 16 hexadecimal digits")
        with self._connect() as connection:
            saves = connection.execute(
                """
                SELECT profile_id, titleid, name, sha256, size
                FROM profile_saves WHERE profile_id IN (?, ?)
                """,
                (left, right),
            ).fetchall()
            achievements = connection.execute(
                """
                SELECT g.profile_id, g.titleid, a.achievement_id, a.title,
                       a.gamerscore, a.unlock_state
                FROM profile_achievements a
                JOIN profile_gpd_files g ON g.id=a.gpd_file_id
                WHERE g.profile_id IN (?, ?)
                """,
                (left, right),
            ).fetchall()
        summary = _comparison_summary(left, right, saves, achievements)
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO profile_comparisons(
                    left_profile_id, right_profile_id, created_at, summary_json
                ) VALUES (?, ?, ?, ?)
                """,
                (left, right, utc_now(), json.dumps(summary, sort_keys=True)),
            )
            summary["comparison_id"] = int(cursor.lastrowid or 0)
        return summary

    def preview_xenia_migration(
        self,
        profile_id: str,
        destination: str | Path,
        *,
        target_profile_id: str = "",
        save_ids: Iterable[int] | None = None,
    ) -> MigrationPlan:
        saves = self._migration_saves(profile_id, save_ids)
        content = find_xenia_content_root(destination)
        if content is None:
            selected = Path(destination).expanduser().resolve()
            if selected.name.casefold() == "content":
                content = selected
            else:
                content = selected / "content"
        return build_migration_plan(
            ((row["source_path"], row["titleid"]) for row in saves),
            content,
            source_profile_id=profile_id,
            target_profile_id=target_profile_id or profile_id,
        )

    def execute_xenia_migration(
        self,
        plan: MigrationPlan,
        *,
        save_ids: Iterable[int] | None = None,
    ) -> dict[str, Any]:
        selected_ids = list(save_ids) if save_ids is not None else [
            int(row["id"]) for row in self._migration_saves(plan.source_profile_id, None)
        ]
        snapshot_id = self.profile_manager.create_snapshot(
            plan.source_profile_id,
            save_ids=selected_ids,
            label="Automatic snapshot before Xenia migration",
        )
        plan_json = json.dumps(
            {
                "items": [
                    {
                        **asdict(item),
                        "source": str(item.source),
                        "destination": str(item.destination),
                        "relative_path": item.relative_path.as_posix(),
                    }
                    for item in plan.items
                ]
            },
            sort_keys=True,
        )
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO xenia_migration_runs(
                    source_profile_id, target_profile_id, destination_root,
                    snapshot_id, created_at, status, plan_json
                ) VALUES (?, ?, ?, ?, ?, 'running', ?)
                """,
                (
                    plan.source_profile_id,
                    plan.target_profile_id,
                    str(plan.destination_content),
                    snapshot_id,
                    utc_now(),
                    plan_json,
                ),
            )
            run_id = int(cursor.lastrowid or 0)
        try:
            copied, skipped, conflicts = execute_migration_plan(plan)
            with self._connect() as connection:
                connection.execute(
                    """
                    UPDATE xenia_migration_runs
                    SET completed_at=?, status='completed', copied_count=?,
                        skipped_count=?, conflict_count=? WHERE id=?
                    """,
                    (utc_now(), copied, skipped, conflicts, run_id),
                )
            return {
                "run_id": run_id,
                "snapshot_id": snapshot_id,
                "copied": copied,
                "skipped": skipped,
                "conflicts": conflicts,
            }
        except Exception as exc:
            with self._connect() as connection:
                connection.execute(
                    """
                    UPDATE xenia_migration_runs
                    SET completed_at=?, status='failed', error_message=? WHERE id=?
                    """,
                    (utc_now(), str(exc), run_id),
                )
            raise

    def _migration_saves(
        self, profile_id: str, save_ids: Iterable[int] | None
    ) -> list[dict[str, Any]]:
        saves = self.profile_manager.list_saves(profile_id)
        if save_ids is None:
            selected = saves
        else:
            wanted = {int(value) for value in save_ids}
            selected = [row for row in saves if int(row["id"]) in wanted]
        if not selected:
            raise ProfileIntelligenceError("No indexed saves were selected")
        return selected


def _comparison_summary(
    left: str,
    right: str,
    saves: Iterable[sqlite3.Row],
    achievements: Iterable[sqlite3.Row],
) -> dict[str, Any]:
    save_maps: dict[str, dict[str, set[str]]] = {
        left: {},
        right: {},
    }
    for row in saves:
        save_maps[str(row["profile_id"])].setdefault(str(row["titleid"]), set()).add(
            str(row["sha256"])
        )
    left_titles = set(save_maps[left])
    right_titles = set(save_maps[right])
    different = sorted(
        title
        for title in left_titles & right_titles
        if save_maps[left][title] != save_maps[right][title]
    )

    unlocked: dict[str, set[tuple[str, int]]] = {left: set(), right: set()}
    for row in achievements:
        if str(row["unlock_state"]).startswith("unlocked"):
            unlocked[str(row["profile_id"])].add(
                (str(row["titleid"]), int(row["achievement_id"]))
            )
    return {
        "left_profile_id": left,
        "right_profile_id": right,
        "save_titles_only_left": sorted(left_titles - right_titles),
        "save_titles_only_right": sorted(right_titles - left_titles),
        "save_titles_different": different,
        "save_titles_identical": sorted(
            (left_titles & right_titles) - set(different)
        ),
        "achievements_only_left": sorted(unlocked[left] - unlocked[right]),
        "achievements_only_right": sorted(unlocked[right] - unlocked[left]),
        "achievements_shared": len(unlocked[left] & unlocked[right]),
    }
