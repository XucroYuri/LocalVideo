#!/usr/bin/env python3
"""Migrate legacy role-based ids to ref-based ids in stage payloads.

This script is intentionally idempotent.
It rewrites:
- content.roles[*].id
- content.dialogue_lines[*].speaker_id
- storyboard.shots[*].speaker_id
- audio_role_configs keys
- any legacy `reference_id` role field

Rule:
- Only `ref_XX` ids remain.
- Existing reference list order is the source of truth.
- `role_1 -> ref_01`, `role_2 -> ref_02`, `scene -> ref_03`
- legacy narrator ids are mapped to an existing narrator-like reference by name,
  otherwise a new `ref_XX` reference named `画外音` is appended.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REF_PREFIX = "ref_"
NARRATOR_NAMES = {"narrator", "旁白", "画外音", "vo", "voiceover", "voice_over"}
DUO_SCENE_NAME = "播客场景"


def is_ref_id(value: Any) -> bool:
    text = str(value or "").strip()
    if not text.startswith(REF_PREFIX):
        return False
    try:
        int(text.split("_", 1)[1])
    except (IndexError, ValueError):
        return False
    return True


def next_ref_id(existing_ids: list[str]) -> str:
    used: set[int] = set()
    for item in existing_ids:
        text = str(item or "").strip()
        if not text.startswith(REF_PREFIX):
            continue
        try:
            used.add(int(text.split("_", 1)[1]))
        except (IndexError, ValueError):
            continue
    next_num = 1
    while next_num in used:
        next_num += 1
    return f"ref_{next_num:02d}"


def parse_json_field(raw: Any) -> Any:
    if raw is None:
        return None
    if isinstance(raw, (dict, list)):
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


def to_json_text(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


@dataclass
class Stats:
    stage_rows_updated: int = 0
    project_configs_updated: int = 0
    references_created: int = 0


class ProjectContext:
    def __init__(self, project_id: int, references: list[dict[str, Any]], script_mode: str) -> None:
        self.project_id = project_id
        self.references = references
        self.script_mode = script_mode
        self.legacy_to_ref: dict[str, str] = {}

        if len(self.references) >= 1:
            self.legacy_to_ref["role_1"] = str(self.references[0].get("id") or "").strip()
        if len(self.references) >= 2:
            self.legacy_to_ref["role_2"] = str(self.references[1].get("id") or "").strip()
        if len(self.references) >= 3:
            self.legacy_to_ref["scene"] = str(self.references[2].get("id") or "").strip()

    def ensure_reference(
        self,
        *,
        name: str,
        can_speak: bool,
        preferred_id: str | None = None,
        setting: str = "",
    ) -> str:
        normalized_name = str(name or "").strip() or "未命名参考"
        for item in self.references:
            ref_name = str(item.get("name") or "").strip()
            if ref_name and ref_name.lower() == normalized_name.lower():
                ref_id = str(item.get("id") or "").strip()
                if ref_id:
                    return ref_id

        existing_ids = [str(item.get("id") or "").strip() for item in self.references]
        target_id = (
            preferred_id
            if preferred_id and is_ref_id(preferred_id) and preferred_id not in existing_ids
            else next_ref_id(existing_ids)
        )
        self.references.append(
            {
                "id": target_id,
                "name": normalized_name,
                "setting": str(setting or "").strip(),
                "appearance_description": "",
                "can_speak": bool(can_speak),
            }
        )
        return target_id

    def resolve_ref_id(
        self,
        *,
        raw_id: Any,
        raw_name: Any = "",
        allow_create: bool = True,
        can_speak: bool = True,
    ) -> str:
        role_id = str(raw_id or "").strip()
        role_name = str(raw_name or "").strip()

        if is_ref_id(role_id):
            return role_id
        if role_id in self.legacy_to_ref and self.legacy_to_ref[role_id]:
            return self.legacy_to_ref[role_id]

        lower_name = role_name.lower()
        if lower_name in NARRATOR_NAMES or role_id.lower() == "narrator":
            narrator_id = (
                self.ensure_reference(name="画外音", can_speak=True) if allow_create else ""
            )
            if narrator_id:
                self.legacy_to_ref["narrator"] = narrator_id
            return narrator_id

        if role_id.lower() == "scene" or "场景" in lower_name:
            scene_id = (
                self.ensure_reference(
                    name=role_name or DUO_SCENE_NAME,
                    can_speak=False,
                    preferred_id="ref_03" if self.script_mode == "duo_podcast" else None,
                )
                if allow_create
                else ""
            )
            if scene_id:
                self.legacy_to_ref["scene"] = scene_id
            return scene_id

        if role_name:
            for item in self.references:
                ref_name = str(item.get("name") or "").strip()
                ref_id = str(item.get("id") or "").strip()
                if ref_name and ref_id and ref_name.lower() == lower_name:
                    if role_id:
                        self.legacy_to_ref[role_id] = ref_id
                    return ref_id

        if allow_create:
            new_id = self.ensure_reference(
                name=role_name or role_id or "未命名角色", can_speak=can_speak
            )
            if role_id:
                self.legacy_to_ref[role_id] = new_id
            return new_id
        return ""


class Migrator:
    def __init__(self, db_path: Path, dry_run: bool = False):
        self.db_path = db_path
        self.dry_run = dry_run
        self.stats = Stats()

    def backup_database(self) -> Path:
        ts = time.strftime("%Y%m%d_%H%M%S")
        backup_path = self.db_path.with_name(f"app.db.backup_role_identity_to_ref_{ts}")
        with sqlite3.connect(self.db_path) as src, sqlite3.connect(backup_path) as dst:
            src.backup(dst)
        return backup_path

    @staticmethod
    def _normalize_references(payload: Any) -> list[dict[str, Any]]:
        if not isinstance(payload, dict):
            return []
        raw = payload.get("references")
        if not isinstance(raw, list):
            return []
        normalized: list[dict[str, Any]] = []
        for index, item in enumerate(raw):
            if not isinstance(item, dict):
                continue
            ref_id = str(item.get("id") or "").strip()
            if not is_ref_id(ref_id):
                ref_id = f"ref_{index + 1:02d}"
            normalized.append({**item, "id": ref_id})
        return normalized

    @staticmethod
    def _resolve_script_mode(project_row: sqlite3.Row, content_payload: Any) -> str:
        if isinstance(content_payload, dict):
            script_mode = str(content_payload.get("script_mode") or "").strip()
            if script_mode:
                return script_mode
        video_type = str(project_row["video_type"] or "").strip()
        if video_type in {"single", "custom", "duo_podcast", "dialogue_script"}:
            return video_type
        return "single"

    def _migrate_roles(self, roles: Any, ctx: ProjectContext) -> list[dict[str, Any]]:
        if not isinstance(roles, list):
            return []
        migrated: list[dict[str, Any]] = []
        for item in roles:
            if not isinstance(item, dict):
                continue
            ref_id = ctx.resolve_ref_id(
                raw_id=item.get("id"),
                raw_name=item.get("name"),
                allow_create=True,
                can_speak="场景" not in str(item.get("name") or ""),
            )
            next_item = dict(item)
            next_item["id"] = ref_id
            next_item.pop("reference_id", None)
            migrated.append(next_item)
        return migrated

    def _migrate_dialogue_lines(self, lines: Any, ctx: ProjectContext) -> list[dict[str, Any]]:
        if not isinstance(lines, list):
            return []
        migrated: list[dict[str, Any]] = []
        for item in lines:
            if not isinstance(item, dict):
                continue
            next_item = dict(item)
            ref_id = ctx.resolve_ref_id(
                raw_id=next_item.get("speaker_id"),
                raw_name=next_item.get("speaker_name"),
                allow_create=True,
                can_speak=True,
            )
            if ref_id:
                next_item["speaker_id"] = ref_id
            migrated.append(next_item)
        return migrated

    def _migrate_shots(self, shots: Any, ctx: ProjectContext) -> list[dict[str, Any]]:
        if not isinstance(shots, list):
            return []
        migrated: list[dict[str, Any]] = []
        for item in shots:
            if not isinstance(item, dict):
                continue
            next_item = dict(item)
            if "speaker_id" in next_item or "speaker_name" in next_item:
                ref_id = ctx.resolve_ref_id(
                    raw_id=next_item.get("speaker_id"),
                    raw_name=next_item.get("speaker_name"),
                    allow_create=True,
                    can_speak=True,
                )
                if ref_id:
                    next_item["speaker_id"] = ref_id
            migrated.append(next_item)
        return migrated

    def _migrate_role_config_dict(self, value: Any, ctx: ProjectContext) -> dict[str, Any]:
        if not isinstance(value, dict):
            return {}
        migrated: dict[str, Any] = {}
        for raw_key, raw_item in value.items():
            ref_id = ctx.resolve_ref_id(
                raw_id=raw_key, raw_name="", allow_create=False, can_speak=True
            )
            migrated[ref_id or str(raw_key)] = raw_item
        return migrated

    def _migrate_payload(self, payload: Any, ctx: ProjectContext) -> Any:
        if isinstance(payload, dict):
            migrated: dict[str, Any] = {}
            for key, value in payload.items():
                if key == "reference_id":
                    continue
                if key == "roles":
                    migrated[key] = self._migrate_roles(value, ctx)
                    continue
                if key == "dialogue_lines":
                    migrated[key] = self._migrate_dialogue_lines(value, ctx)
                    continue
                if key == "shots":
                    migrated[key] = self._migrate_shots(value, ctx)
                    continue
                if key in {"audio_role_configs", "audioRoleConfigs"}:
                    migrated[key] = self._migrate_role_config_dict(value, ctx)
                    continue
                migrated[key] = self._migrate_payload(value, ctx)
            return migrated
        if isinstance(payload, list):
            return [self._migrate_payload(item, ctx) for item in payload]
        return payload

    def migrate(self) -> None:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 5000")

        try:
            conn.execute("BEGIN IMMEDIATE")
            project_rows = conn.execute(
                "SELECT id, video_type, config FROM projects ORDER BY id"
            ).fetchall()

            for project_row in project_rows:
                project_id = int(project_row["id"])
                stage_rows = conn.execute(
                    """
                    SELECT id, stage_type, input_data, output_data
                    FROM stage_executions
                    WHERE project_id = ?
                    ORDER BY id
                    """,
                    (project_id,),
                ).fetchall()

                content_payload = next(
                    (
                        parse_json_field(row["output_data"])
                        for row in stage_rows
                        if row["stage_type"] == "CONTENT"
                    ),
                    {},
                )
                reference_stage_row = next(
                    (row for row in stage_rows if row["stage_type"] == "REFERENCE"),
                    None,
                )
                reference_payload = (
                    parse_json_field(reference_stage_row["output_data"])
                    if reference_stage_row
                    else {}
                )
                references = self._normalize_references(reference_payload)
                initial_reference_count = len(references)
                ctx = ProjectContext(
                    project_id=project_id,
                    references=references,
                    script_mode=self._resolve_script_mode(project_row, content_payload),
                )

                updates_by_stage_id: dict[int, dict[str, str | None]] = {}
                for row in stage_rows:
                    stage_updates: dict[str, str | None] = {}
                    for field in ("input_data", "output_data"):
                        parsed = parse_json_field(row[field])
                        if parsed is None:
                            continue
                        migrated = self._migrate_payload(parsed, ctx)
                        if (
                            row["stage_type"] == "REFERENCE"
                            and field == "output_data"
                            and isinstance(migrated, dict)
                        ):
                            migrated["references"] = ctx.references
                            migrated["reference_count"] = len(ctx.references)
                        if migrated != parsed:
                            stage_updates[field] = to_json_text(migrated)
                    if stage_updates:
                        updates_by_stage_id[int(row["id"])] = stage_updates

                for stage_id, updates in updates_by_stage_id.items():
                    set_parts: list[str] = []
                    values: list[Any] = []
                    for field, value in updates.items():
                        set_parts.append(f"{field} = ?")
                        values.append(value)
                    set_parts.append("updated_at = CURRENT_TIMESTAMP")
                    values.append(stage_id)
                    conn.execute(
                        f"UPDATE stage_executions SET {', '.join(set_parts)} WHERE id = ?",
                        values,
                    )
                    self.stats.stage_rows_updated += 1

                config_payload = parse_json_field(project_row["config"])
                if config_payload is not None:
                    migrated_config = self._migrate_payload(config_payload, ctx)
                    if migrated_config != config_payload:
                        conn.execute(
                            "UPDATE projects SET config = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                            (to_json_text(migrated_config), project_id),
                        )
                        self.stats.project_configs_updated += 1

                self.stats.references_created += max(
                    0, len(ctx.references) - initial_reference_count
                )

            if self.dry_run:
                conn.rollback()
            else:
                conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def print_summary(self, backup_path: Path) -> None:
        print("=" * 80)
        print("Role identity -> Ref identity migration finished")
        print(f"Database: {self.db_path}")
        print(f"Backup:   {backup_path}")
        print(f"Dry run:  {self.dry_run}")
        print("-" * 80)
        print(f"Stage rows updated: {self.stats.stage_rows_updated}")
        print(f"Project configs updated: {self.stats.project_configs_updated}")
        print(f"References created: {self.stats.references_created}")
        print("=" * 80)


def parse_args() -> argparse.Namespace:
    backend_dir = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Migrate legacy role ids to ref ids")
    parser.add_argument(
        "--db",
        type=Path,
        default=backend_dir / "app.db",
        help="Path to sqlite database file",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not persist database changes",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    db_path = args.db.resolve()
    if not db_path.exists():
        print(f"Database not found: {db_path}", file=sys.stderr)
        return 1

    migrator = Migrator(db_path=db_path, dry_run=args.dry_run)
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
