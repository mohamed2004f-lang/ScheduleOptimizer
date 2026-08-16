"""محوّل اتصال PostgreSQL ليطابق واجهة sqlite3 المستخدمة في الخدمات."""
from __future__ import annotations

def _adapt_pg_execute_sql(sql: str) -> str:
    # Runtime is now PostgreSQL-native; keep only placeholder adaptation.
    return sql.replace("?", "%s")


class _PgRowAdapter:
    """
    يجمع بين وصول psycopg dict_row بالاسم وبين فهرسة رقمية مثل sqlite3.Row (row[0]).
    """

    __slots__ = ("_d", "_seq")

    def __init__(self, mapping: dict, column_order: tuple[str, ...]):
        self._d = mapping
        self._seq = tuple(mapping.get(c) for c in column_order)

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._seq[key]
        return self._d[key]

    def __iter__(self):
        return iter(self._seq)

    def __len__(self):
        return len(self._seq)

    def keys(self):
        return self._d.keys()

    def get(self, key, default=None):
        return self._d.get(key, default)


def _wrap_pg_row(row, description) -> object:
    """يحوّل صف dict_row إلى _PgRowAdapter عند الحاجة."""
    if row is None or description is None:
        return row
    if not isinstance(row, dict):
        return row
    colnames = tuple(d[0] for d in description)
    return _PgRowAdapter(row, colnames)


class _PgCursorWrapper:
    """محوّل ? إلى %s و lastrowid لـ psycopg."""

    def __init__(self, raw, parent: "_PgConnectionWrapper"):
        self._c = raw
        self._parent = parent
        self._lastrowid = None
        self.description = None

    @property
    def connection(self):
        """توافق مع sqlite3.Cursor.connection."""
        return self._parent

    def execute(self, sql, params=None):
        self._lastrowid = None
        q = _adapt_pg_execute_sql(sql)
        if params is None:
            self._c.execute(q)
        else:
            self._c.execute(q, params)
        self.description = self._c.description
        uq = q.lstrip().upper()
        if uq.startswith("INSERT"):
            # PostgreSQL: لا نستدعي lastval() هنا لأن جداول كثيرة لا تستخدم sequence
            # (مثل users بمفتاح نصي)، واستدعاؤه يفشل ويُفسد المعاملة الحالية.
            self._lastrowid = None
        return self

    def executemany(self, sql, seq_of_params):
        self._lastrowid = None
        q = _adapt_pg_execute_sql(sql)
        self._c.executemany(q, seq_of_params)
        self.description = self._c.description
        return self

    def fetchone(self):
        return _wrap_pg_row(self._c.fetchone(), self._c.description)

    def fetchall(self):
        desc = self._c.description
        return [_wrap_pg_row(r, desc) for r in self._c.fetchall()]

    def __iter__(self):
        """مثل sqlite3.Cursor: for row in cur.execute(...)."""
        while True:
            row = self.fetchone()
            if row is None:
                break
            yield row

    @property
    def lastrowid(self):
        return self._lastrowid

    @property
    def rowcount(self):
        """متوافق مع sqlite3: عدد الصفوف المتأثرة بآخر execute / executemany."""
        return getattr(self._c, "rowcount", -1)


class _PgConnectionWrapper:
    """
    Wrapper لاتصال PostgreSQL يوفر توافق مع واجهة sqlite3.Connection.
    يدعم العمل مع connection pool: عند الإغلاق يعيد الاتصال للـ pool بدلاً من إغلاقه فعلياً.
    """
    def __init__(self, raw_conn, pool=None):
        self._conn = raw_conn
        self._pool = pool

    def cursor(self):
        return _PgCursorWrapper(self._conn.cursor(), self)

    def commit(self):
        return self._conn.commit()

    def rollback(self):
        return self._conn.rollback()

    def close(self):
        if self._pool is not None:
            # إعادة الاتصال للـ pool بدلاً من إغلاقه
            self._pool.putconn(self._conn)
        else:
            self._conn.close()

    def execute(self, sql, params=None):
        cur = self.cursor()
        cur.execute(sql, params)
        return cur

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self._conn.commit()
        else:
            self._conn.rollback()
        self.close()
        return False
