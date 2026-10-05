#!/usr/bin/env bash
# Run from repo root. Excludes docs/, .claude/ and node_modules.
set -u
G=(grep -rnE --exclude-dir=node_modules --exclude-dir=.git --exclude-dir=docs --exclude-dir=.claude)
echo "## Python imports of removed packages (import names)"
for m in flask_admin graphene graphene_sqlalchemy flask_graphql dask google segment analytics paramiko nacl pyasn1 cryptography fuzzywuzzy jellyfish editdistance Levenshtein fabric; do
  n=$("${G[@]}" --include='*.py' "^\s*(import|from)\s+$m(\.|\s|$)" . | wc -l)
  printf '%-20s %s\n' "$m" "$n"
  "${G[@]}" --include='*.py' "^\s*(import|from)\s+$m(\.|\s|$)" . | sed 's/^/    /'
done
echo "## Any textual mention outside requirements*.txt and mypy.ini"
"${G[@]}" -i "flask.admin|graphene|flask.graphql|\bdask\b|google.cloud|segment-analytics|\bparamiko\b|pynacl|pyasn1|fuzzywuzzy|jellyfish|editdistance|levenshtein" . \
  | grep -vE '^\./(requirements[^:]*\.txt|mypy\.ini):'
echo "## /graphql route module and web/server/graphql package"
"${G[@]}" "graphql_api|GraphqlPageRouter|web\.server\.graphql|ZenGraphQLView" .
echo "## /api/timeout callers"
"${G[@]}" "api/timeout|timeout_session|timeout_user_session" .
echo "## Hadoop task templates / on_prem.json / legacy builder"
"${G[@]}" "task_templates|on_prem\.json|legacy_task_builder|DruidIndexingTaskBuilder|scripts/run_indexing|scripts\.run_indexing|run_indexing\.py" . | grep -v '^\./db/druid/indexing/resources/'
echo "## zen_environment consumers"
"${G[@]}" "zen_environment|zenEnvironment" web/client
