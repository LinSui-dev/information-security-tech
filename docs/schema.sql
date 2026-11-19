-- 可选 SQLite schema；不是基础应用启动条件。
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS experiment (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('basic', 'noise', 'jpeg', 'crop', 'keyed')),
    algorithm_version TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    operator TEXT NOT NULL DEFAULT '',
    parameters_json TEXT NOT NULL DEFAULT '{}',
    metrics_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'success', 'failed')),
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS artifact (
    id INTEGER PRIMARY KEY,
    experiment_id TEXT NOT NULL REFERENCES experiment(id) ON DELETE RESTRICT,
    role TEXT NOT NULL CHECK (role IN ('source', 'stego', 'transformed', 'extracted', 'screenshot')),
    relative_path TEXT NOT NULL,
    sha256 TEXT NOT NULL CHECK (length(sha256) = 64),
    UNIQUE (experiment_id, role, relative_path)
);

CREATE INDEX IF NOT EXISTS idx_artifact_experiment ON artifact(experiment_id);
