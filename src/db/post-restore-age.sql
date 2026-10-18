-- Run ONCE after pg_restore, as a superuser, in the restored database:
--   psql -U postgres -d <db> -v ON_ERROR_STOP=1 -f post-restore-age.sql
-- Why: AGE stores the graph schema OID (ag_graph.graphid, ag_label.graph) as a plain oid. A restore creates the
-- schema with a NEW oid, so cypher() fails with "graph with oid NNNNN does not exist" until the catalog is realigned.
BEGIN;
CREATE TEMP TABLE _old AS SELECT g.graphid AS old_oid, n.oid AS new_oid
  FROM ag_catalog.ag_graph g JOIN pg_namespace n ON n.nspname = g.name::text;
ALTER TABLE ag_catalog.ag_label DROP CONSTRAINT fk_graph_oid;
UPDATE ag_catalog.ag_label l SET graph = o.new_oid FROM _old o WHERE l.graph = o.old_oid;
UPDATE ag_catalog.ag_graph g SET graphid = o.new_oid FROM _old o WHERE g.graphid = o.old_oid;
ALTER TABLE ag_catalog.ag_label ADD CONSTRAINT fk_graph_oid FOREIGN KEY (graph) REFERENCES ag_catalog.ag_graph (graphid);
COMMIT;
