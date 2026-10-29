"""Persistencia local cifrada SQLCipher. No existe fallback a SQLite sin cifrar."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

try:
    from sqlcipher3 import dbapi2 as sqlcipher
except ImportError:
    try:
        from pysqlcipher3 import dbapi2 as sqlcipher  # type: ignore[no-redef]
    except ImportError:
        sqlcipher = None  # type: ignore[assignment]


class RepositorioFichas:
    def __init__(self, ruta: str | Path, clave: str | None = None):
        if sqlcipher is None:
            raise RuntimeError("SQLCipher no está instalado. Instale sqlcipher3-binary; no se usará SQLite sin cifrar.")
        self.ruta = Path(ruta)
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        self.clave = clave or os.environ.get("FICHACOSTO_DB_KEY")
        if not self.clave:
            raise ValueError("Defina FICHACOSTO_DB_KEY para cifrar la base de datos local")
        self.db = sqlcipher.connect(str(self.ruta))
        escaped = self.clave.replace("'", "''")
        self.db.execute(f"PRAGMA key = '{escaped}'")
        # Force key verification immediately; wrong keys fail before app data is exposed.
        self.db.execute("SELECT count(*) FROM sqlite_master").fetchone()
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.execute("""CREATE TABLE IF NOT EXISTS fichas (
            id TEXT PRIMARY KEY, nombre TEXT NOT NULL, estado TEXT NOT NULL,
            fecha_actualizacion TEXT NOT NULL, documento_json TEXT NOT NULL
        )""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS catalogos (
            id TEXT PRIMARY KEY, tipo TEXT NOT NULL, documento_json TEXT NOT NULL
        )""")
        # Licensing state and feature quotas live in the same SQLCipher database.
        self.db.execute("CREATE TABLE IF NOT EXISTS licensing_state (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        self.db.execute("""CREATE TABLE IF NOT EXISTS licensing_usage (
            license_id TEXT NOT NULL, feature TEXT NOT NULL, used_count INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (license_id, feature)
        )""")
        self.db.execute("CREATE TABLE IF NOT EXISTS preferences (key TEXT PRIMARY KEY, value_json TEXT NOT NULL)")
        self.db.commit()

    def guardar_ficha(self, documento: dict) -> None:
        ficha = documento["ficha"]
        self.db.execute("INSERT OR REPLACE INTO fichas VALUES (?, ?, ?, ?, ?)", (
            ficha["id"], ficha["nombre"], ficha["estado"], ficha["fechaActualizacion"],
            json.dumps(documento, ensure_ascii=False)))
        self.db.commit()

    def listar_fichas(self) -> list[dict]:
        filas = self.db.execute("SELECT documento_json FROM fichas ORDER BY fecha_actualizacion DESC").fetchall()
        return [json.loads(fila[0]) for fila in filas]

    def obtener_ficha(self, ficha_id: str) -> dict | None:
        fila = self.db.execute("SELECT documento_json FROM fichas WHERE id = ?", (ficha_id,)).fetchone()
        return json.loads(fila[0]) if fila else None

    def eliminar_ficha(self, ficha_id: str) -> None:
        self.db.execute("DELETE FROM fichas WHERE id = ?", (ficha_id,))
        self.db.commit()

    def guardar_catalogo(self, tipo: str, elemento: dict) -> None:
        self.db.execute("INSERT OR REPLACE INTO catalogos VALUES (?, ?, ?)", (
            elemento["id"], tipo, json.dumps(elemento, ensure_ascii=False)))
        self.db.commit()

    def listar_catalogo(self, tipo: str) -> list[dict]:
        return [json.loads(row[0]) for row in self.db.execute(
            "SELECT documento_json FROM catalogos WHERE tipo = ?", (tipo,)).fetchall()]

    def eliminar_catalogo(self, elemento_id: str) -> None:
        self.db.execute("DELETE FROM catalogos WHERE id = ?", (elemento_id,))
        self.db.commit()

    def snapshot_catalogos(self) -> dict:
        return {"insumos": self.listar_catalogo("insumo"), "tarifasSalario": self.listar_catalogo("tarifa")}

    def get_preference(self, key: str, default=None):
        row = self.db.execute("SELECT value_json FROM preferences WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_preference(self, key: str, value) -> None:
        self.db.execute("INSERT OR REPLACE INTO preferences (key, value_json) VALUES (?, ?)",
                        (key, json.dumps(value, ensure_ascii=False)))
        self.db.commit()

    def license_get_state(self, key: str) -> str | None:
        row = self.db.execute("SELECT value FROM licensing_state WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def license_set_state(self, key: str, value: str) -> None:
        self.db.execute("INSERT OR REPLACE INTO licensing_state (key, value) VALUES (?, ?)", (key, value))
        self.db.commit()

    def license_get_usage(self, license_id: str, feature: str) -> int:
        row = self.db.execute("SELECT used_count FROM licensing_usage WHERE license_id = ? AND feature = ?",
                              (license_id, feature)).fetchone()
        return int(row[0]) if row else 0

    def license_consume_quota(self, license_id: str, feature: str, limit: int) -> bool:
        # A write lock makes check-and-increment atomic across concurrent UI actions.
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute("SELECT used_count FROM licensing_usage WHERE license_id = ? AND feature = ?",
                                  (license_id, feature)).fetchone()
            used = int(row[0]) if row else 0
            if used >= limit:
                self.db.rollback()
                return False
            self.db.execute("INSERT OR REPLACE INTO licensing_usage (license_id, feature, used_count) VALUES (?, ?, ?)",
                            (license_id, feature, used + 1))
            used_at = datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
            self.db.execute("INSERT OR REPLACE INTO licensing_state (key, value) VALUES (?, ?)", ("usage_last_timestamp", used_at))
            self.db.commit()
            return True
        except Exception:
            self.db.rollback()
            raise

    def cerrar(self) -> None:
        self.db.close()
