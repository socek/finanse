import os

import pytest

from finanse.db import connect, init_db
from finanse.storage import (
    DATABASE,
    OTHER_BACKUPS,
    OTHER_FILES,
    STARTUP_BACKUPS,
    data_files,
    database_path,
    format_size,
)


@pytest.mark.parametrize(
    ("size", "text"),
    [
        (0, "0 B"),
        (1023, "1023 B"),
        (1024, "1,0 KB"),
        (122880, "120,0 KB"),
        (1024**2, "1,0 MB"),
        (1536 * 1024, "1,5 MB"),
        (1024**3, "1,0 GB"),
        (5 * 1024**4, "5120,0 GB"),
    ],
)
def test_format_size(size, text):
    assert format_size(size) == text


def write(path, size, modified=None):
    path.write_bytes(b"x" * size)
    if modified:
        os.utime(path, (modified, modified))


def test_files_are_grouped_and_summed(tmp_path):
    database = tmp_path / "finanse.db"
    write(database, 100)
    write(tmp_path / "finanse.db-journal", 5)
    write(tmp_path / "finanse.db.backup-v2", 20, 1000)
    write(tmp_path / "finanse.db.backup-pre-x", 30, 2000)
    write(tmp_path / "elo.txt", 7)
    backups = tmp_path / "backups"
    backups.mkdir()
    write(backups / "finanse-20261106-120000.db", 50, 1000)
    write(backups / "finanse-20261107-120000.db", 60, 2000)
    write(backups / "cos.txt", 1)
    nested = tmp_path / "inny-katalog"
    nested.mkdir()
    write(nested / "pominiety.bin", 999)

    groups, count, size = data_files(database)
    by_name = {group["name"]: group for group in groups}
    assert [group["name"] for group in groups] == [
        DATABASE, STARTUP_BACKUPS, OTHER_BACKUPS, OTHER_FILES,
    ]  # fmt: skip
    assert by_name[DATABASE]["size"] == 105
    assert by_name[STARTUP_BACKUPS]["size"] == 110
    # Od najnowszych, a nazwy są względem katalogu bazy.
    assert [f["name"] for f in by_name[STARTUP_BACKUPS]["files"]] == [
        os.path.join("backups", "finanse-20261107-120000.db"),
        os.path.join("backups", "finanse-20261106-120000.db"),
    ]
    assert [f["name"] for f in by_name[OTHER_BACKUPS]["files"]] == [
        "finanse.db.backup-pre-x",
        "finanse.db.backup-v2",
    ]
    assert {f["name"] for f in by_name[OTHER_FILES]["files"]} == {
        "elo.txt",
        os.path.join("backups", "cos.txt"),
    }
    assert count == 8
    assert size == 100 + 5 + 20 + 30 + 7 + 50 + 60 + 1


def test_missing_backups_directory_and_empty_groups(tmp_path):
    database = tmp_path / "finanse.db"
    write(database, 10)
    groups, count, size = data_files(database)
    assert [group["name"] for group in groups] == [DATABASE]
    assert (count, size) == (1, 10)


def test_database_path_of_open_connection(tmp_path):
    path = tmp_path / "x.db"
    init_db(str(path))
    db = connect(str(path))
    assert database_path(db) == path
    db.close()
