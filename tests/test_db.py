from db import run_sql_file


class _Cur:
    def __init__(self, log):
        self.log = log

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, stmt):
        self.log.append(stmt)


class _Conn:
    def __init__(self):
        self.log = []

    def cursor(self):
        return _Cur(self.log)

    def commit(self):
        pass


def test_run_sql_file_skips_comment_only_chunks(tmp_path):
    p = tmp_path / "x.sql"
    p.write_text("-- header; with a semicolon;\n\n"
                 "CREATE TABLE t (a INT);\n"
                 "-- middle comment;\n"
                 "-- another\n"
                 "INSERT INTO t VALUES (1);\n"
                 "-- trailing comment\n")
    conn = _Conn()
    run_sql_file(conn, p)
    assert len(conn.log) == 2
    assert "CREATE TABLE t" in conn.log[0]
    assert "INSERT INTO t" in conn.log[1]
