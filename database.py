"""Small DB-API bridge for the existing SQLite queries and hosted PostgreSQL."""
import os


class PostgresConnection:
    def __init__(self, url: str):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError("DATABASE_URL 已设置，但缺少 psycopg 依赖") from exc
        self._conn = psycopg.connect(url, row_factory=dict_row)

    def execute(self, sql, params=()):
        if sql.strip().upper() == 'BEGIN IMMEDIATE':
            return None  # psycopg starts a transaction on the first statement.
        return self._conn.execute(sql.replace('?', '%s'), params)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()


def hosted_url():
    return os.getenv('DATABASE_URL', '').strip()
