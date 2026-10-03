"""Compare restored synthetic audit evidence inside the ephemeral CI database."""

import subprocess


def rows(database):
    return (
        subprocess.check_output(
            [
                "docker",
                "compose",
                "-f",
                "docker-compose.ci.yml",
                "exec",
                "-T",
                "db",
                "psql",
                "-U",
                "ci",
                "-d",
                database,
                "-At",
                "-c",
                "SELECT id || ':' || sha256 FROM platform_events WHERE kind IN ('reported_placement','position_transition') ORDER BY id",
            ],
            text=True,
        )
        .strip()
        .splitlines()
    )


original, restored = rows("jabbazi_ci"), rows("jabbazi_restore")
assert len(original) == 2 and original == restored
print("Disposable PostgreSQL backup/restore retained both ledger evidence hashes")
