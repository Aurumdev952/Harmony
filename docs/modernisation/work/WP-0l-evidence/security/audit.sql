-- Read-only per-deployment audit for misplaced dashboard_admin ACLs (WP-0l security gate).
-- 1. Dashboards whose author holds no dashboard_admin on them (also lists legitimate removals; review each row)
SELECT d.id, d.slug, d.resource_id, d.author_id FROM dashboard d
WHERE NOT EXISTS (SELECT 1 FROM user_acl a JOIN resource_role rr ON rr.id = a.resource_role_id
  WHERE a.user_id = d.author_id AND a.resource_id = d.resource_id AND rr.name = 'dashboard_admin');
-- 2. dashboard_admin held on a dashboard whose name another dashboard's name matches with _ as a wildcard, by that other dashboard's author
SELECT a.id, a.user_id, v.id AS on_resource, v.name, o.id AS other_resource, o.name
FROM user_acl a
JOIN resource_role rr ON rr.id = a.resource_role_id AND rr.name = 'dashboard_admin'
JOIN resource v ON v.id = a.resource_id AND v.resource_type_id = 2
JOIN resource o ON o.resource_type_id = 2 AND o.id <> v.id AND v.name ILIKE o.name
JOIN dashboard od ON od.resource_id = o.id AND od.author_id = a.user_id
JOIN dashboard vd ON vd.resource_id = v.id AND vd.author_id <> a.user_id;
