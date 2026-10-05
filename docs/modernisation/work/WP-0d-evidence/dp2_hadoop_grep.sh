#!/usr/bin/env bash
# Grep report: references to the Hadoop indexing path outside the files being deleted.
cd "$1" || exit 1
P='legacy_task_builder|run_indexing\b|task_templates|index_hadoop|on_prem\.json|tuning_configs|DruidIndexingTaskBuilder|index_hadoop_nested_json'
SELF='^(\./)?db/druid/indexing/(legacy_task_builder\.py|scripts/run_indexing\.py|resources/task_templates/)'
for a in pipeline prod docker Makefile scripts .github .gitlab-ci.yml .circleci druid_setup config web data db util models log; do
  if [ ! -e "$a" ]; then echo "$a: absent"; continue; fi
  hits=$(grep -rnE "$P" "$a" --exclude-dir=node_modules 2>/dev/null | grep -vE "$SELF")
  echo "$a: $(printf '%s' "$hits" | grep -c .)"
  [ -n "$hits" ] && printf '%s\n' "$hits"
done
echo '--- whole repo (excluding docs, .claude, .git, node_modules, the deleted files) ---'
grep -rnE "$P" . --exclude-dir=node_modules --exclude-dir=.git --exclude-dir=docs --exclude-dir=.claude 2>/dev/null | grep -vE "$SELF" || echo "0 hits"
echo '--- symbols defined in legacy_task_builder used elsewhere ---'
grep -rnE "BadIndexingPathException|build_input_spec|_validate_file_path|STATIC_FILE_SPEC|MULTI_INPUT_SPEC" --include='*.py' . --exclude-dir=node_modules --exclude-dir=.claude | grep -v 'legacy_task_builder.py'
echo '--- docs mentions (informational, excluded from the check) ---'
grep -rnE "$P" docs | cut -c1-200
