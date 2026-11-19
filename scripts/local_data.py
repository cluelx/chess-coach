"""Manage the personal edition's SQLite data while the app is stopped."""

import argparse
from contextlib import closing
from datetime import datetime
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import db


def backup(destination: Path) -> None:
    with destination.open("xb"):
        pass
    try:
        with closing(db.connect()) as source, closing(sqlite3.connect(destination)) as target:
            source.backup(target)
    except BaseException:
        destination.unlink()
        raise
    print(f"备份已保存到 {destination}")


def safety_backup() -> None:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup(Path(db.DB_PATH).with_name(f"chess_coach-backup-{stamp}.db"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list")
    commands.add_parser("adopt").add_argument("learner_id")
    commands.add_parser("backup").add_argument("file", type=Path)
    commands.add_parser("restore").add_argument("file", type=Path)
    args = parser.parse_args()
    db.init_db()

    if args.command == "list":
        current = db.local_learner_id()
        for row in db.query(
            "SELECT l.id, l.name, l.level, "
            "(SELECT count(*) FROM attempt a WHERE a.learner_id=l.id) AS attempts, "
            "(SELECT count(*) FROM review_log r WHERE r.learner_id=l.id) AS reviews "
            "FROM learner l ORDER BY l.created_at DESC"
        ):
            mark = "（当前）" if row["id"] == current else ""
            print(f'{row["id"]}  {row["name"]}  档位 {row["level"]}  '
                  f'练习 {row["attempts"]}  复盘 {row["reviews"]}{mark}')
    elif args.command == "adopt":
        if args.learner_id != "local" and not db.one(
            "SELECT 1 FROM learner WHERE id=?", (args.learner_id,),
        ):
            parser.error("没有此档案。请先执行 list。")
        safety_backup()
        db.execute(
            "INSERT INTO local_profile(singleton, learner_id) VALUES(1, ?) "
            "ON CONFLICT(singleton) DO UPDATE SET learner_id=excluded.learner_id",
            (args.learner_id,),
        )
        print(f"个人版档案已设为 {args.learner_id}")
    elif args.command == "backup":
        backup(args.file)
    elif args.command == "restore":
        source_path = args.file.resolve()
        if source_path == Path(db.DB_PATH).resolve() or not source_path.is_file():
            parser.error("请选择另一份已存在的备份。")
        with closing(sqlite3.connect(source_path.as_uri() + "?mode=ro", uri=True)) as source:
            if not source.execute("SELECT 1 FROM sqlite_master WHERE name='learner'").fetchone():
                parser.error("备份不是 chess-coach 数据库。")
            safety_backup()
            with closing(db.connect()) as target:
                source.backup(target)
        db.init_db()
        print(f"已从 {source_path} 恢复")


if __name__ == "__main__":
    main()
