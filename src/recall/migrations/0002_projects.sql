-- 0002_projects.sql
-- Project registry table (ADR-0009).
--
-- The CHECK constraint enforces S3.8: the reserved name 'global' (in any
-- case) cannot be used as a project id.

CREATE TABLE IF NOT EXISTS projects (
    id           text PRIMARY KEY,
    display_name text NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    created_by   text NOT NULL,
    CONSTRAINT projects_no_global CHECK (lower(id) != 'global')
);
