"""
================================================================================
 TESTS — HOSTED SQLITE ADAPTER (database._TursoConnection)
================================================================================
 The app can run against a hosted SQLite-compatible database (Turso/libSQL)
 when TURSO_URL is set. database._TursoConnection is a sqlite3-compatible
 shim over libsql-client so every query in models.py/main.py works unchanged.

 These tests validate the ADAPTER LOGIC with a deterministic fake libsql
 client backed by a single real sqlite3 connection (isolation_level=None),
 so explicit BEGIN/COMMIT/ROLLBACK statements persist exactly as they do on
 a Turso Hrana stream. The one thing not covered here is the WebSocket
 transport itself, which requires a live Turso database + token.

 Skipped automatically when libsql-client is not installed.
"""
import sqlite3

import pytest

pytest.importorskip("libsql_client")
import libsql_client  # noqa: E402

import database  # noqa: E402


class _FakeResult:
    """Mirrors libsql_client.ResultSet: columns, rows, rows_affected, last_insert_rowid."""

    def __init__(self, columns, rows, rows_affected, last_insert_rowid):
        self.columns = columns
        self.rows = rows
        self.rows_affected = rows_affected
        self.last_insert_rowid = last_insert_rowid


class _FakeTxn:
    """Mirrors libsql_client.TransactionSync: statements run on the shared
    connection until commit()/rollback() ends the transaction."""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, args=None):
        params = args if args is not None else ()
        cursor = self._conn.execute(sql, params)
        rows = cursor.fetchall()
        columns = tuple(d[0] for d in (cursor.description or ()))
        rows_affected = cursor.rowcount
        last_insert_rowid = cursor.lastrowid
        cursor.close()
        return _FakeResult(columns, rows, rows_affected, last_insert_rowid)

    def commit(self):
        self._conn.execute("COMMIT")

    def rollback(self):
        self._conn.execute("ROLLBACK")


class _FakeClient:
    """Stand-in for libsql_client.ClientSync. One persistent sqlite3
    connection (isolation_level=None = autocommit); transaction() opens a
    manual BEGIN on that same connection, so the adapter's BEGIN IMMEDIATE /
    COMMIT / ROLLBACK flows behave like a Hrana stream: later statements on
    the same connection see earlier ones."""

    def __init__(self, path):
        self._conn = sqlite3.connect(path, isolation_level=None)
        self._closed = False

    def execute(self, sql, args=None):
        params = args if args is not None else ()
        cursor = self._conn.execute(sql, params)
        rows = cursor.fetchall()
        columns = tuple(d[0] for d in (cursor.description or ()))
        rows_affected = cursor.rowcount
        last_insert_rowid = cursor.lastrowid
        cursor.close()
        return _FakeResult(columns, rows, rows_affected, last_insert_rowid)

    def transaction(self):
        self._conn.execute("BEGIN")
        return _FakeTxn(self._conn)

    def close(self):
        if not self._closed:
            self._closed = True
            self._conn.close()


@pytest.fixture
def turso_env(tmp_path, monkeypatch):
    """Route get_db() through the real adapter using a fake libsql client."""
    monkeypatch.setenv("TURSO_URL", "libsql://fairshare-demo.turso.io")
    monkeypatch.setenv("TURSO_AUTH_TOKEN", "test-token")
    db_path = str(tmp_path / "fake_turso.db")

    def fake_create_client_sync(url, auth_token=None, **kwargs):
        assert url == "libsql://fairshare-demo.turso.io"
        assert auth_token == "test-token"
        return _FakeClient(db_path)

    monkeypatch.setattr(libsql_client, "create_client_sync", fake_create_client_sync)
    return db_path


def test_libsql_client_installed():
    assert callable(libsql_client.create_client_sync)


def test_get_db_returns_adapter_when_turso_url_set(turso_env):
    conn = database.get_db()
    assert isinstance(conn, database._TursoConnection)
    conn.close()


def test_get_db_uses_local_sqlite_without_turso_url(monkeypatch, tmp_path):
    monkeypatch.delenv("TURSO_URL", raising=False)
    monkeypatch.setattr(database.Config, "DATABASE", str(tmp_path / "local.db"))
    conn = database.get_db()
    assert isinstance(conn, sqlite3.Connection)
    conn.close()


def test_init_db_builds_full_schema_and_seeds(turso_env):
    database.init_db()
    conn = database.get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'")
    assert cursor.fetchone()[0] == 1
    cursor.execute("SELECT COUNT(*) FROM members")
    assert cursor.fetchone()[0] == 4
    cursor.execute("SELECT COUNT(*) FROM coupons")
    assert cursor.fetchone()[0] == 8
    conn.close()


def test_dirty_flag_triggers_fire(turso_env):
    database.init_db()
    conn = database.get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT pending FROM rewards_recompute WHERE id = 1")
    assert cursor.fetchone()['pending'] == 0
    cursor.execute("INSERT INTO members (user_id, full_name, email, member_code) "
                   "VALUES (99999, 'T', 't@t.com', 'MBR-TEST1')")
    cursor.execute("SELECT pending FROM rewards_recompute WHERE id = 1")
    assert cursor.fetchone()['pending'] == 1
    conn.close()


def test_row_access_patterns(turso_env):
    database.init_db()
    conn = database.get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM members ORDER BY id LIMIT 1")
    row = cursor.fetchone()
    assert row['full_name']
    assert row[1] is not None
    d = dict(row)
    assert d['full_name'] == row['full_name']
    assert len(row) == len(d)
    cursor.execute("SELECT * FROM members")
    rows = cursor.fetchall()
    assert len(rows) == 4
    assert cursor.fetchone() is None
    cursor.execute("SELECT * FROM members WHERE id = -1")
    assert cursor.fetchone() is None
    conn.close()


def test_lastrowid_and_rowcount(turso_env):
    database.init_db()
    conn = database.get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO reward_settings (visit_weight) VALUES (1.0)")
    assert cursor.lastrowid > 0
    cursor.execute("UPDATE reward_settings SET visit_weight = 2.0")
    assert cursor.rowcount >= 1
    cursor.execute("UPDATE members SET full_name = full_name WHERE id = -1")
    assert cursor.rowcount == 0
    conn.close()


def test_begin_commit_rollback_transactions(turso_env):
    database.init_db()
    conn = database.get_db()
    # rolled-back write must not persist
    conn.execute("BEGIN IMMEDIATE")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO guest_ids (guest_code, guest_name, host_member_id) "
                   "VALUES ('GST-ROLLBACK', 'R', 1)")
    conn.rollback()
    cursor.execute("SELECT COUNT(*) FROM guest_ids WHERE guest_code = 'GST-ROLLBACK'")
    assert cursor.fetchone()[0] == 0
    # committed write must persist across connections
    conn.execute("BEGIN IMMEDIATE")
    cursor.execute("INSERT INTO guest_ids (guest_code, guest_name, host_member_id) "
                   "VALUES ('GST-COMMIT', 'C', 1)")
    conn.commit()
    conn.close()
    conn2 = database.get_db()
    cursor2 = conn2.cursor()
    cursor2.execute("SELECT COUNT(*) FROM guest_ids WHERE guest_code = 'GST-COMMIT'")
    assert cursor2.fetchone()[0] == 1
    conn2.close()


def test_executescript_runs_multiple_statements(turso_env):
    conn = database.get_db()
    cursor = conn.cursor()
    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS adapter_probe (id INTEGER PRIMARY KEY AUTOINCREMENT, v TEXT);
        INSERT INTO adapter_probe (v) VALUES ('a');
        INSERT INTO adapter_probe (v) VALUES ('b');
    """)
    cursor.execute("SELECT COUNT(*) FROM adapter_probe")
    assert cursor.fetchone()[0] == 2
    conn.close()


def test_app_flow_through_adapter(turso_env):
    """A realistic business flow (guest pass creation, spending, revocation
    report) driven entirely through the adapter via the model layer."""
    database.init_db()
    from models import GuestManager

    guest = GuestManager.create_guest_id(1, "Adapter Guest")
    assert guest['guest_code'].startswith('GST-')
    assert GuestManager.get_guest_by_code(guest['guest_code'])['guest_name'] == "Adapter Guest"
    GuestManager.record_spending(guest['id'], "Bistro & Lounge", 42.50)

    result = GuestManager.revoke_guest_pass(1, guest['id'])
    assert result['ok'] is True
    report = GuestManager.get_guest_report(1, guest['id'])
    assert report is not None
    assert report['activity_count'] >= 1
    assert report['total_spending'] == 42.50
