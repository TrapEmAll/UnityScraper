"""Small migration registry for domain-owned schema work.

The legacy ``database_migrations.py`` module remains authoritative today. This
registry gives new or moved domains a common contract so schema ownership can
shift incrementally instead of through one large rewrite.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone

DomainMigration = Callable[[sqlite3.Connection], None]


@dataclass(frozen=True)
class RegisteredMigration:
    """One additive schema migration owned by a feature domain."""

    domain: str
    version: int
    name: str
    apply: DomainMigration

    @property
    def key(self) -> str:
        return f"{self.domain}:{self.version}"


@dataclass
class MigrationRegistry:
    """Collect domain migrations and apply the unapplied set once."""

    migrations: list[RegisteredMigration] = field(default_factory=list)

    def register(
        self,
        *,
        domain: str,
        version: int,
        name: str,
        apply: DomainMigration,
    ) -> None:
        migration = RegisteredMigration(domain=domain, version=version, name=name, apply=apply)
        if any(existing.key == migration.key for existing in self.migrations):
            raise ValueError(f"Duplicate migration key: {migration.key}")
        self.migrations.append(migration)

    def extend(self, migrations: Iterable[RegisteredMigration]) -> None:
        for migration in migrations:
            self.register(
                domain=migration.domain,
                version=migration.version,
                name=migration.name,
                apply=migration.apply,
            )

    def apply(self, connection: sqlite3.Connection) -> list[RegisteredMigration]:
        return apply_registered_migrations(connection, self.migrations)


def apply_registered_migrations(
    connection: sqlite3.Connection,
    migrations: Iterable[RegisteredMigration],
) -> list[RegisteredMigration]:
    """Apply migrations not yet present in ``app_domain_migrations``."""

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS app_domain_migrations (
            domain TEXT NOT NULL,
            version INTEGER NOT NULL,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL,
            PRIMARY KEY(domain, version)
        )
        """
    )
    applied = {
        (str(row[0]), int(row[1]))
        for row in connection.execute("SELECT domain, version FROM app_domain_migrations")
    }
    completed: list[RegisteredMigration] = []
    for migration in sorted(migrations, key=lambda item: (item.domain, item.version)):
        if (migration.domain, migration.version) in applied:
            continue
        migration.apply(connection)
        connection.execute(
            """
            INSERT INTO app_domain_migrations(domain, version, name, applied_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                migration.domain,
                migration.version,
                migration.name,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        completed.append(migration)
    return completed

