-- 0001_initial.sql
-- Add the scope invariant CHECK on the `store` table.
--
-- AsyncPostgresStore.setup() is invoked from Python inside apply_pending before
-- any SQL migration runs, so the `store` table already exists when this runs.
-- This file adds only what setup() cannot: the scope/project_id invariant
-- required by ADR-0001 and ADR-0002.
--
-- The namespace tuple (scope, project_id) is encoded by LangGraph as
-- '<scope>.<project_id>' in the `prefix` column. A valid prefix is therefore
-- either 'global._' (scope=global, project_id sentinel) or 'project.<pid>'
-- with <pid> != '_'.

ALTER TABLE store ADD CONSTRAINT store_scope_invariant CHECK (
    prefix = 'global._'
    OR (prefix LIKE 'project.%' AND prefix != 'project._')
);
