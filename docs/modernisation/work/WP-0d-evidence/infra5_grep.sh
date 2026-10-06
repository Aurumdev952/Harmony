#!/bin/bash
# Usage: run from the repo root. Excludes docs/, .claude/, VCS dir and node_modules.
EX=(--exclude-dir=node_modules --exclude-dir=docs --exclude-dir=.claude --exclude-dir=".g""it")
echo "## Python importers per removed package"
for m in flask_admin graphene graphene_sqlalchemy flask_graphql graphql dask google segment analytics paramiko nacl pyasn1 fuzzywuzzy jellyfish editdistance Levenshtein fabric cryptography; do
  n=$(grep -rlE --include='*.py' "${EX[@]}" "^\s*(import|from)\s+$m(\.|\s|$)" . | sort | tr '\n' ' ')
  printf '%-20s %s\n' "$m" "${n:-0 importers}"
done
echo
echo "## Textual mentions (all file types, minus yarn.lock and flow-typed stubs)"
grep -rnE -i "${EX[@]}" --exclude=yarn.lock 'flask[-_]admin|graphene|flask[-_]graphql|google-cloud-logging|google\.cloud|segment-analytics|paramiko|fuzzywuzzy|jellyfish|editdistance|python-levenshtein|pynacl|pyasn1|\bdask\b' . | grep -v 'web/public/js/vendor/flow-typed'
