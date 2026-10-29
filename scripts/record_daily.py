#!/usr/bin/env python3
"""Write an idempotent local practice-batch event in tracker-compatible JSON."""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXAM_IDS = {"GK", "ZJ_GWY", "JX_GWY", "ZJ_SY", "JX_SY"}
SOURCE_TYPES = {"official_question", "verified_compilation", "training_simulation", "ai_original", "unknown"}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
EVENT_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
DAILY_SCHEMA_VERSION = 1


class InputError(ValueError):
    pass


def normalize(payload: dict[str, Any]) -> dict[str, Any]:
    allowed = {"date", "event_id", "kind", "exam_type", "province", "year", "paper_type", "source", "source_type", "modules", "note"}
    extra = set(payload) - allowed
    if extra:
        raise InputError("未知字段: " + ", ".join(sorted(extra)))
    date = payload.get("date")
    if not isinstance(date, str) or not DATE_RE.fullmatch(date):
        raise InputError("date 必须为 YYYY-MM-DD")
    try:
        dt.date.fromisoformat(date)
    except ValueError as exc:
        raise InputError("date 不是有效日期") from exc

    exam = payload.get("exam_type")
    if exam is not None and (not isinstance(exam, str) or exam not in EXAM_IDS):
        raise InputError("exam_type 必须是 GK、ZJ_GWY、JX_GWY、ZJ_SY、JX_SY 或 null")
    year = payload.get("year")
    if year is not None and (not isinstance(year, int) or isinstance(year, bool) or not 1900 <= year <= 2200):
        raise InputError("year 必须是 1900–2200 的整数或 null")
    source_type = payload.get("source_type", "unknown")
    if not isinstance(source_type, str) or source_type not in SOURCE_TYPES:
        raise InputError("source_type 不在约定枚举内")

    raw_modules = payload.get("modules")
    if not isinstance(raw_modules, dict) or not raw_modules:
        raise InputError("modules 必须是非空 object")
    modules: dict[str, dict[str, int]] = {}
    for name, raw in raw_modules.items():
        if not isinstance(name, str) or not name.strip() or len(name) > 80:
            raise InputError("module 名称必须是 1–80 字符")
        if not isinstance(raw, dict) or set(raw) - {"wrong", "total", "duration_minutes"}:
            raise InputError(f"{name} 的统计字段只允许 wrong、total、duration_minutes")
        stats: dict[str, int] = {}
        for field, value in raw.items():
            if value is not None:
                if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                    raise InputError(f"{name}.{field} 必须是非负整数或 null")
                stats[field] = value
        if not ({"wrong", "total"} & stats.keys()):
            raise InputError(f"{name} 至少要提供 wrong 或 total")
        if stats.get("wrong", 0) > stats.get("total", stats.get("wrong", 0)):
            raise InputError(f"{name}.wrong 不能大于 total")
        clean_name = name.strip()
        if clean_name in modules:
            raise InputError(f"重复的 module 名称: {clean_name}")
        modules[clean_name] = stats

    normalized: dict[str, Any] = {
        "date": date,
        "kind": payload.get("kind", "practice_batch"),
        "exam_type": exam,
        "province": payload.get("province"),
        "year": year,
        "paper_type": payload.get("paper_type"),
        "source": payload.get("source"),
        "source_type": source_type,
        "modules": modules,
        "note": payload.get("note", ""),
    }
    for field in ("kind", "source", "province", "paper_type", "note"):
        value = normalized[field]
        if value is not None and (not isinstance(value, str) or len(value) > 2000):
            raise InputError(f"{field} 必须是长度不超过 2000 的文本或 null")
    event_id = payload.get("event_id")
    if event_id is None:
        canonical = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        event_id = "auto-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]
    elif not isinstance(event_id, str) or not EVENT_RE.fullmatch(event_id):
        raise InputError("event_id 只能包含字母、数字、点、下划线、冒号和连字符，且不超过 128 字符")
    normalized["event_id"] = event_id
    return normalized


def summarize(events: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    totals: dict[str, dict[str, int]] = {}
    for event in events:
        for module, stats in event["modules"].items():
            dest = totals.setdefault(module, {"_wrong_complete": 1, "_total_complete": 1})
            if "wrong" not in stats:
                dest["_wrong_complete"] = 0
            if "total" not in stats:
                dest["_total_complete"] = 0
            for field in ("wrong", "total", "duration_minutes"):
                if field in stats:
                    dest[field] = dest.get(field, 0) + stats[field]
    summary: dict[str, dict[str, int]] = {}
    for name, values in sorted(totals.items()):
        summary[name] = {k: v for k, v in values.items() if not k.startswith("_")}
        summary[name]["accuracy_complete"] = int(bool(values["_wrong_complete"] and values["_total_complete"]))
    return summary


def atomic_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def write_event(data_dir: Path, event: dict[str, Any]) -> dict[str, Any]:
    data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    daily = data_dir / "daily"
    daily.mkdir(parents=True, exist_ok=True, mode=0o700)
    if daily.is_symlink():
        raise InputError("daily 目录不能是符号链接")
    target = daily / f"{event['date']}.json"
    if target.is_symlink():
        raise InputError("目标日报不能是符号链接")
    lock_path = daily / ".record_daily.lock"
    if lock_path.is_symlink():
        raise InputError("锁文件不能是符号链接")
    lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(lock_fd, "a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        day: dict[str, Any] = {"date": event["date"], "events": []}
        if target.exists():
            try:
                day = json.loads(target.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise InputError(f"现有日报无法安全读取，未覆盖：{target}") from exc
            if not isinstance(day, dict) or day.get("date") != event["date"] or not isinstance(day.get("events", []), list):
                raise InputError(f"现有日报结构错误，未覆盖：{target}")
            version = day.get("schema_version")
            if version is not None and version != DAILY_SCHEMA_VERSION:
                raise InputError(f"现有日报 schema_version={version}，本脚本只写 {DAILY_SCHEMA_VERSION}，未覆盖：{target}")

        for other in daily.glob("????-??-??.json"):
            if other == target:
                continue
            if other.is_symlink():
                raise InputError(f"发现符号链接日报，拒绝扫描：{other}")
            try:
                other_day = json.loads(other.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise InputError(f"其他日报无法读取，拒绝可能的重复写入：{other}") from exc
            if not isinstance(other_day, dict) or not isinstance(other_day.get("events", []), list):
                raise InputError(f"其他日报结构错误，拒绝可能的重复写入：{other}")
            if any(not isinstance(item, dict) for item in other_day.get("events", [])):
                raise InputError(f"其他日报 events 格式错误，拒绝可能的重复写入：{other}")
            if any(item.get("event_id") == event["event_id"] for item in other_day.get("events", [])):
                raise InputError("event_id 已用于其他日期；独立复练请使用不同 event_id")

        events = day.get("events", [])
        if any(not isinstance(item, dict) for item in events):
            raise InputError(f"现有日报 events 格式错误，未覆盖：{target}")
        event_ids = [item.get("event_id") for item in events]
        if any(not isinstance(value, str) for value in event_ids):
            raise InputError(f"现有日报 event_id 格式错误，未覆盖：{target}")
        if len(event_ids) != len(set(event_ids)):
            raise InputError(f"现有日报含重复 event_id，未覆盖：{target}")
        index = next((i for i, item in enumerate(events) if item.get("event_id") == event["event_id"]), None)
        now = dt.datetime.now().astimezone().isoformat(timespec="seconds")
        if index is not None:
            old = events[index]
            comparable = {k: v for k, v in old.items() if k not in {"recorded_at", "updated_at"}}
            if comparable == event:
                return {"status": "noop", "event_id": event["event_id"], "path": str(target)}
            events[index] = {**event, "recorded_at": old.get("recorded_at", now), "updated_at": now}
            status = "updated"
        else:
            events.append({**event, "recorded_at": now})
            status = "written"

        events.sort(key=lambda item: item["event_id"])
        day.update({"schema_version": DAILY_SCHEMA_VERSION, "date": event["date"], "events": events, "event_ids": [item["event_id"] for item in events], "modules": summarize(events), "updated_at": now})
        atomic_write(target, day)
        return {"status": status, "event_id": event["event_id"], "path": str(target), "event_count": len(events)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--payload", default="-", help="JSON payload file; default reads stdin")
    parser.add_argument("--data-dir", default=str(PROJECT_ROOT / "data" / "tracker"), help="local tracker data directory")
    args = parser.parse_args()
    try:
        raw = sys.stdin.read() if args.payload == "-" else Path(args.payload).read_text(encoding="utf-8")
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise InputError("payload 必须是 JSON object")
        result = write_event(Path(args.data_dir).resolve(), normalize(payload))
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (InputError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "blocked", "message": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
