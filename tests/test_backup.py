from finanse.__main__ import default_database
from finanse.db import backup_on_startup, connect, init_db
from finanse.wallets import create_wallet


def test_backup_on_startup_copies_database_and_prunes_only_its_files(tmp_path):
    path = tmp_path / "finanse.db"
    assert backup_on_startup(path) is None  # bazy jeszcze nie ma
    assert not (tmp_path / "backups").exists()

    init_db(str(path))
    db = connect(str(path))
    create_wallet(db, "A")
    db.close()

    directory = tmp_path / "backups"
    directory.mkdir()
    for day in range(1, 5):
        (directory / f"finanse-2026010{day}-120000.db").write_text("stara")
    foreign = directory / "moja-kopia.db"
    foreign.write_text("nie ruszać")

    target = backup_on_startup(path, keep=2)
    copy = connect(str(target))
    assert copy.execute("SELECT name FROM wallets").fetchone()[0] == "A"
    copy.close()
    names = sorted(file.name for file in directory.iterdir())
    assert names == sorted(["finanse-20260104-120000.db", target.name, "moja-kopia.db"])
    assert foreign.read_text() == "nie ruszać"
    assert not list(directory.glob("*.tmp"))


def test_default_database_is_in_home_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert default_database() == tmp_path / ".finanse" / "finanse.db"
