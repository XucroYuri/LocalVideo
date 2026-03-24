#!/usr/bin/env python3
"""Migrate legacy CHARACTER stage data and character assets to REFERENCE format.

What this script migrates:
- stage_executions.stage_type: CHARACTER -> REFERENCE (with dedup/merge)
- JSON payload keys: characters/character_images/character_count/only_character_id
- Legacy ids: char_XX -> ref_XX
- Legacy paths: .../characters/char_XX.* -> .../references/ref_XX.*
- project config JSON (if any legacy keys/ids are present)
- filesystem assets: copy characters/* -> references/* with ref_XX names

The script is designed to be idempotent.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

KEY_RENAMES = {
    "characters": "references",
    "character_images": "reference_images",
    "character_count": "reference_count",
    "only_character_id": "only_reference_id",
    "character_ids": "reference_ids",
    "first_frame_prompt_character_identity": "first_frame_prompt_reference_identity",
    "use_character_consistency": "use_reference_consistency",
}

ID_PATTERN = re.compile(r"^char_(\d+)$")
ID_IN_TEXT_PATTERN = re.compile(r"\bchar_(\d+)\b")


@dataclass
class Stats:
    json_rows_updated: int = 0
    project_config_updated: int = 0
    project_ids_migrated: int = 0
    promoted_character_rows: int = 0
    reference_rows_merged: int = 0
    character_rows_deleted: int = 0
    duplicate_reference_rows_deleted: int = 0
    filesystem_dirs_migrated: int = 0
    filesystem_files_copied: int = 0


class Migrator:
    def __init__(self, db_path: Path, storage_path: Path, dry_run: bool = False):
        self.db_path = db_path
        self.storage_path = storage_path
        self.backend_dir = db_path.parent
        self.dry_run = dry_run
        self.stats = Stats()

    @staticmethod
    def _convert_id(value: Any) -> Any:
        if not isinstance(value, str):
            return value
        match = ID_PATTERN.fullmatch(value.strip())
        if not match:
            return value
        return f"ref_{match.group(1)}"

    @staticmethod
    def _replace_legacy_string(value: str) -> str:
        text = value
        text = text.replace("/characters/", "/references/")
        text = text.replace("\\characters\\", "\\references\\")
        text = ID_IN_TEXT_PATTERN.sub(lambda m: f"ref_{m.group(1)}", text)
        return text

    def _migrate_obj(self, obj: Any) -> Any:
        if isinstance(obj, dict):
            migrated: dict[str, Any] = {}
            for key, value in obj.items():
                new_key = KEY_RENAMES.get(key, key)
                new_value = self._migrate_obj(value)

                if new_key == "id":
                    new_value = self._convert_id(new_value)
                elif new_key == "reference_ids" and isinstance(new_value, list):
                    new_value = [self._convert_id(item) for item in new_value]

                migrated[new_key] = new_value
            return migrated

        if isinstance(obj, list):
            return [self._migrate_obj(item) for item in obj]

        if isinstance(obj, str):
            return self._replace_legacy_string(obj)

        return obj

    @staticmethod
    def _parse_json_field(raw: Any) -> Any:
        if raw is None:
            return None
        if isinstance(raw, dict | list):
            return raw
        if not isinstance(raw, str):
            return None
        text = raw.strip()
        if not text:
            return None
        try:
            return json.loads(text)
        except Exception:
            return None

    @staticmethod
    def _to_json_text(value: Any) -> str | None:
        if value is None:
            return None
        return json.dumps(value, ensure_ascii=False)

    @staticmethod
    def _has_reference_payload(data: Any) -> bool:
        if not isinstance(data, dict):
            return False
        refs = data.get("references")
        ref_images = data.get("reference_images")
        return (isinstance(refs, list) and len(refs) > 0) or (
            isinstance(ref_images, list) and len(ref_images) > 0
        )

    def _normalize_reference_payload(self, data: Any) -> dict[str, Any]:
        if not isinstance(data, dict):
            return {}

        payload = self._migrate_obj(data)
        if not isinstance(payload, dict):
            return {}

        references = payload.get("references")
        if isinstance(references, list):
            normalized_refs: list[Any] = []
            for idx, item in enumerate(references):
                if isinstance(item, dict):
                    entry = dict(item)
                    current_id = self._convert_id(entry.get("id"))
                    if not isinstance(current_id, str) or not current_id.strip():
                        current_id = f"ref_{idx + 1:02d}"
                    entry["id"] = current_id
                    normalized_refs.append(entry)
                else:
                    normalized_refs.append(item)
            payload["references"] = normalized_refs
            payload["reference_count"] = len(normalized_refs)

        ref_images = payload.get("reference_images")
        if isinstance(ref_images, list):
            normalized_images: list[Any] = []
            for idx, item in enumerate(ref_images):
                if isinstance(item, dict):
                    entry = dict(item)
                    current_id = self._convert_id(entry.get("id"))
                    if not isinstance(current_id, str) or not current_id.strip():
                        current_id = f"ref_{idx + 1:02d}"
                    entry["id"] = current_id
                    normalized_images.append(entry)
                else:
                    normalized_images.append(item)
            payload["reference_images"] = normalized_images
            payload.setdefault(
                "generated_count",
                sum(
                    1
                    for i in normalized_images
                    if isinstance(i, dict) and (i.get("generated") or i.get("uploaded"))
                ),
            )

        return payload

    def _merge_reference_payload(self, base: Any, extra: Any) -> dict[str, Any]:
        merged = self._normalize_reference_payload(base)
        incoming = self._normalize_reference_payload(extra)

        if not merged.get("references") and incoming.get("references"):
            merged["references"] = incoming["references"]

        if not merged.get("reference_images") and incoming.get("reference_images"):
            merged["reference_images"] = incoming["reference_images"]

        for key in (
            "reference_count",
            "generated_count",
            "runtime_provider",
            "image_provider",
            "failed_items",
        ):
            if key not in merged and key in incoming:
                merged[key] = incoming[key]

        if isinstance(merged.get("references"), list):
            merged["reference_count"] = len(merged["references"])

        if isinstance(merged.get("reference_images"), list) and "generated_count" not in merged:
            merged["generated_count"] = sum(
                1
                for item in merged["reference_images"]
                if isinstance(item, dict) and (item.get("generated") or item.get("uploaded"))
            )

        return merged

    def backup_database(self) -> Path:
        ts = time.strftime("%Y%m%d_%H%M%S")
        backup_path = self.db_path.with_name(f"app.db.backup_character_to_reference_{ts}")
        with sqlite3.connect(self.db_path) as src, sqlite3.connect(backup_path) as dst:
            src.backup(dst)
        return backup_path

    def _resolve_output_dir(self, output_dir: str | None) -> Path | None:
        if not output_dir:
            return None
        path = Path(output_dir)
        if path.is_absolute():
            return path
        return (self.backend_dir / path).resolve()

    def migrate(self) -> None:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 5000")

        try:
            conn.execute("BEGIN IMMEDIATE")

            self._migrate_stage_json_payloads(conn)
            self._migrate_project_config(conn)
            self._merge_character_stage_to_reference(conn)

            if self.dry_run:
                conn.rollback()
            else:
                conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

        self._migrate_filesystem_assets()

    def _migrate_stage_json_payloads(self, conn: sqlite3.Connection) -> None:
        rows = conn.execute(
            "SELECT id, input_data, output_data FROM stage_executions ORDER BY id"
        ).fetchall()

        for row in rows:
            row_id = row["id"]
            updates: dict[str, Any] = {}

            for field in ("input_data", "output_data"):
                raw_value = row[field]
                parsed = self._parse_json_field(raw_value)
                if parsed is None:
                    continue
                migrated = self._migrate_obj(parsed)
                if migrated != parsed:
                    updates[field] = self._to_json_text(migrated)

            if updates:
                updates["updated_at"] = "CURRENT_TIMESTAMP"
                set_clause_parts = []
                values: list[Any] = []
                for key, value in updates.items():
                    if key == "updated_at":
                        set_clause_parts.append("updated_at = CURRENT_TIMESTAMP")
                    else:
                        set_clause_parts.append(f"{key} = ?")
                        values.append(value)
                values.append(row_id)
                sql = f"UPDATE stage_executions SET {', '.join(set_clause_parts)} WHERE id = ?"
                conn.execute(sql, values)
                self.stats.json_rows_updated += 1

    def _migrate_project_config(self, conn: sqlite3.Connection) -> None:
        rows = conn.execute("SELECT id, config FROM projects ORDER BY id").fetchall()
        for row in rows:
            project_id = row["id"]
            parsed = self._parse_json_field(row["config"])
            if parsed is None:
                continue
            migrated = self._migrate_obj(parsed)
            if migrated != parsed:
                conn.execute(
                    "UPDATE projects SET config = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (self._to_json_text(migrated), project_id),
                )
                self.stats.project_config_updated += 1

    def _merge_character_stage_to_reference(self, conn: sqlite3.Connection) -> None:
        project_ids = [
            row[0]
            for row in conn.execute(
                "SELECT DISTINCT project_id FROM stage_executions ORDER BY project_id"
            ).fetchall()
        ]

        for project_id in project_ids:
            rows = conn.execute(
                """
                SELECT id, project_id, stage_type, stage_number, status, progress,
                       input_data, output_data, error_message
                FROM stage_executions
                WHERE project_id = ? AND stage_type IN ('CHARACTER', 'REFERENCE')
                ORDER BY id
                """,
                (project_id,),
            ).fetchall()

            if not rows:
                continue

            char_rows = [row for row in rows if row["stage_type"] == "CHARACTER"]
            ref_rows = [row for row in rows if row["stage_type"] == "REFERENCE"]

            if not char_rows:
                continue

            self.stats.project_ids_migrated += 1

            source_char = max(
                char_rows,
                key=lambda row: (
                    1
                    if self._has_reference_payload(self._parse_json_field(row["output_data"]))
                    else 0,
                    row["id"],
                ),
            )
            source_input = self._migrate_obj(self._parse_json_field(source_char["input_data"]))
            source_output = self._normalize_reference_payload(
                self._parse_json_field(source_char["output_data"])
            )

            target_ref = None
            if ref_rows:
                target_ref = max(
                    ref_rows,
                    key=lambda row: (
                        1
                        if self._has_reference_payload(self._parse_json_field(row["output_data"]))
                        else 0,
                        row["id"],
                    ),
                )

            if target_ref is None:
                target_id = source_char["id"]
                merged_input = source_input
                merged_output = source_output
                status = (
                    "COMPLETED"
                    if self._has_reference_payload(merged_output)
                    else source_char["status"]
                )
                progress = 100 if status == "COMPLETED" else source_char["progress"]
                error_message = None if status == "COMPLETED" else source_char["error_message"]

                conn.execute(
                    """
                    UPDATE stage_executions
                    SET stage_type = 'REFERENCE',
                        input_data = ?,
                        output_data = ?,
                        status = ?,
                        progress = ?,
                        error_message = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (
                        self._to_json_text(merged_input),
                        self._to_json_text(merged_output),
                        status,
                        progress,
                        error_message,
                        target_id,
                    ),
                )
                self.stats.promoted_character_rows += 1
            else:
                target_id = target_ref["id"]
                target_input = self._migrate_obj(self._parse_json_field(target_ref["input_data"]))
                target_output = self._normalize_reference_payload(
                    self._parse_json_field(target_ref["output_data"])
                )

                merged_output = self._merge_reference_payload(target_output, source_output)
                merged_input = target_input if target_input is not None else source_input

                for extra_ref in ref_rows:
                    if extra_ref["id"] == target_id:
                        continue
                    extra_output = self._normalize_reference_payload(
                        self._parse_json_field(extra_ref["output_data"])
                    )
                    merged_output = self._merge_reference_payload(merged_output, extra_output)
                    self.stats.reference_rows_merged += 1

                status = target_ref["status"]
                progress = target_ref["progress"]
                error_message = target_ref["error_message"]
                if self._has_reference_payload(merged_output):
                    status = "COMPLETED"
                    progress = 100
                    error_message = None

                conn.execute(
                    """
                    UPDATE stage_executions
                    SET input_data = ?,
                        output_data = ?,
                        status = ?,
                        progress = ?,
                        error_message = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (
                        self._to_json_text(merged_input),
                        self._to_json_text(merged_output),
                        status,
                        progress,
                        error_message,
                        target_id,
                    ),
                )

                for extra_ref in ref_rows:
                    if extra_ref["id"] == target_id:
                        continue
                    conn.execute("DELETE FROM stage_executions WHERE id = ?", (extra_ref["id"],))
                    self.stats.duplicate_reference_rows_deleted += 1

            for row in char_rows:
                if row["id"] == target_id:
                    continue
                conn.execute("DELETE FROM stage_executions WHERE id = ?", (row["id"],))
                self.stats.character_rows_deleted += 1

    def _migrate_filesystem_assets(self) -> None:
        project_rows = []
        if self.db_path.exists():
            with sqlite3.connect(self.db_path) as conn:
                project_rows = conn.execute(
                    "SELECT id, output_dir FROM projects ORDER BY id"
                ).fetchall()

        for project_id, output_dir in project_rows:
            resolved = self._resolve_output_dir(output_dir)
            if resolved is None:
                continue

            old_dir = resolved / "characters"
            if not old_dir.exists() or not old_dir.is_dir():
                continue

            new_dir = resolved / "references"
            new_dir.mkdir(parents=True, exist_ok=True)
            self.stats.filesystem_dirs_migrated += 1

            for file_path in sorted(old_dir.iterdir()):
                if not file_path.is_file():
                    continue
                new_name = re.sub(r"^char_(\d+)", r"ref_\1", file_path.name)
                target_path = new_dir / new_name
                if target_path.exists():
                    continue
                if self.dry_run:
                    continue
                shutil.copy2(file_path, target_path)
                self.stats.filesystem_files_copied += 1

    def print_summary(self, backup_path: Path) -> None:
        print("=" * 80)
        print("Character -> Reference migration finished")
        print(f"Database: {self.db_path}")
        print(f"Backup:   {backup_path}")
        print(f"Dry run:  {self.dry_run}")
        print("-" * 80)
        print(f"JSON rows updated: {self.stats.json_rows_updated}")
        print(f"Project config updated: {self.stats.project_config_updated}")
        print(f"Projects migrated: {self.stats.project_ids_migrated}")
        print(f"CHARACTER rows promoted: {self.stats.promoted_character_rows}")
        print(f"REFERENCE rows merged: {self.stats.reference_rows_merged}")
        print(f"Duplicate REFERENCE rows deleted: {self.stats.duplicate_reference_rows_deleted}")
        print(f"CHARACTER rows deleted: {self.stats.character_rows_deleted}")
        print(f"Filesystem dirs migrated: {self.stats.filesystem_dirs_migrated}")
        print(f"Filesystem files copied: {self.stats.filesystem_files_copied}")
        print("=" * 80)


def parse_args() -> argparse.Namespace:
    backend_dir = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Migrate legacy character data to reference data")
    parser.add_argument(
        "--db",
        type=Path,
        default=backend_dir / "app.db",
        help="Path to sqlite database file",
    )
    parser.add_argument(
        "--storage",
        type=Path,
        default=backend_dir / "storage",
        help="Path to storage directory",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not persist DB/filesystem changes",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    db_path = args.db.resolve()
    storage_path = args.storage.resolve()

    if not db_path.exists():
        print(f"Database not found: {db_path}", file=sys.stderr)
        return 1

    migrator = Migrator(db_path=db_path, storage_path=storage_path, dry_run=args.dry_run)

    try:
        backup_path = migrator.backup_database()
        migrator.migrate()
        migrator.print_summary(backup_path)
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"Migration failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
