
import os
from typing import Any, Mapping, Sequence

import psycopg2
from dotenv import load_dotenv
from psycopg2 import sql
from psycopg2.extras import RealDictCursor


class PostgresDriver:

    def __init__(
        self,
        *,
        host=None,
        port=None,
        dbname=None,
        user=None,
        password=None,
        env_file=None,
    ):
        load_dotenv(env_file)

        self._params = {
            "host": host or os.getenv("DB_HOST", "localhost"),
            "port": int(port or os.getenv("DB_PORT", "5432")),
            "dbname": dbname or os.getenv("DB_NAME"),
            "user": user or os.getenv("DB_USER"),
            "password": password if password is not None else os.getenv("DB_PASSWORD", ""),
            "options": "-c lc_messages=C",
        }

        self._conn = None

    def connect(self):
        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(**self._params)
        return self._conn

    def close(self):
        if self._conn is not None and not self._conn.closed:
            self._conn.close()
        self._conn = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._conn is None or self._conn.closed:
            return

        if exc_type is not None:
            self._conn.rollback()
        else:
            self._conn.commit()

        self.close()

    def execute(self, query, params=None):
        with self.connect().cursor() as cur:
            cur.execute(query, params)
            self._conn.commit()

    def fetch_one(self, query, params=None):
        with self.connect().cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, params)
            row = cur.fetchone()
            return dict(row) if row else None

    def fetch_all(self, query, params=None):
        with self.connect().cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, params)
            return [dict(row) for row in cur.fetchall()]

    def ping(self):
        return self.fetch_one(
            "SELECT current_database() AS dbname, version();"
        )

    def list_tables(self):
        rows = self.fetch_all("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
            ORDER BY table_name;
        """)
        return [row["table_name"] for row in rows]

    # ==================================
    # МЕТОДЫ ДЛЯ НАШЕГО ЗАДАНИЯ
    # ==================================

    def create_tables(self):
        self.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                age INT CHECK (age >= 0)
            );
        """)

        self.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id SERIAL PRIMARY KEY,
                user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                amount NUMERIC(10, 2) NOT NULL,
                created_at TIMESTAMP DEFAULT NOW()
            );
        """)

    def add_user(self, name, age):
        try:
            with self.connect().cursor() as cur:
                cur.execute(
                    "INSERT INTO users (name, age) VALUES (%s,%s)",
                    (name, age)
                )
                self._conn.commit()
        except psycopg2.Error:
            self._conn.rollback()
            raise

    def add_order(self, user_id, amount):
        try:
            with self.connect().cursor() as cur:
                cur.execute(
                    "INSERT INTO orders (user_id, amount) VALUES (%s,%s)",
                    (user_id, amount)
                )
                self._conn.commit()
        except psycopg2.Error:
            self._conn.rollback()
            raise

    def get_user_totals(self):
        return self.fetch_all("""
            SELECT
                u.id,
                u.name,
                COALESCE(SUM(o.amount), 0) AS total_amount
            FROM users u
            LEFT JOIN orders o ON o.user_id = u.id
            GROUP BY u.id, u.name
            ORDER BY total_amount DESC;
        """)

    # ==================================
    # УНИВЕРСАЛЬНЫЕ CRUD-МЕТОДЫ
    # ==================================

    def create(self, table, data, *, returning="id"):
        if not data:
            raise ValueError("create() нужен непустой словарь data")

        columns = [sql.Identifier(key) for key in data]
        values = [sql.Placeholder() for _ in data]

        query = sql.SQL(
            "INSERT INTO {table} ({columns}) VALUES ({values}) RETURNING {returning}"
        ).format(
            table=sql.Identifier(table),
            columns=sql.SQL(", ").join(columns),
            values=sql.SQL(", ").join(values),
            returning=sql.SQL("*") if returning == "*" else sql.Identifier(returning),
        )

        with self.connect().cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, list(data.values()))
            row = cur.fetchone()
            self._conn.commit()
            return dict(row) if row else None

    def read(self, table, *, columns=None, where=None, order_by=None, limit=None):
        select_cols = (
            sql.SQL("*")
            if not columns
            else sql.SQL(", ").join(sql.Identifier(name) for name in columns)
        )

        query = sql.SQL("SELECT {columns} FROM {table}").format(
            columns=select_cols,
            table=sql.Identifier(table),
        )

        params = []
        query = self._append_where(query, where, params)

        if order_by:
            query = sql.SQL("{query} ORDER BY {order_by}").format(
                query=query,
                order_by=sql.Identifier(order_by),
            )

        if limit is not None:
            query = sql.SQL("{query} LIMIT {limit}").format(
                query=query,
                limit=sql.Literal(int(limit)),
            )

        with self.connect().cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, params)
            return [dict(row) for row in cur.fetchall()]

    def read_one(self, table, *, columns=None, where=None):
        rows = self.read(table, columns=columns, where=where, limit=1)
        return rows[0] if rows else None

    def update(self, table, data, where):
        if not data:
            raise ValueError("update() нужен непустой словарь data")

        self._require_where(where, "update")

        assignments = sql.SQL(", ").join(
            sql.SQL("{column} = {placeholder}").format(
                column=sql.Identifier(key),
                placeholder=sql.Placeholder(),
            )
            for key in data
        )

        query = sql.SQL("UPDATE {table} SET {assignments}").format(
            table=sql.Identifier(table),
            assignments=assignments,
        )

        params = list(data.values())
        query = self._append_where(query, where, params)

        with self.connect().cursor() as cur:
            cur.execute(query, params)
            updated = cur.rowcount
            self._conn.commit()
            return updated

    def delete(self, table, where):
        self._require_where(where, "delete")

        query = sql.SQL("DELETE FROM {table}").format(
            table=sql.Identifier(table)
        )

        params = []
        query = self._append_where(query, where, params)

        with self.connect().cursor() as cur:
            cur.execute(query, params)
            deleted = cur.rowcount
            self._conn.commit()
            return deleted

    @staticmethod
    def _require_where(where, method):
        if not where:
            raise ValueError(
                f"{method}() требует where, чтобы не затронуть всю таблицу"
            )

    @staticmethod
    def _append_where(query, where, params):
        if not where:
            return query

        conditions = sql.SQL(" AND ").join(
            sql.SQL("{column} = {placeholder}").format(
                column=sql.Identifier(key),
                placeholder=sql.Placeholder(),
            )
            for key in where
        )

        params.extend(where.values())

        return sql.SQL("{query} WHERE {conditions}").format(
            query=query,
            conditions=conditions,
        )
