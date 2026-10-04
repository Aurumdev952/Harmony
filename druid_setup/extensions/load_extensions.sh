#!/bin/bash
# Installs the extensions Harmony loads on top of the stock Druid image.
# Every file is pinned to a commit or release and checked against its SHA-256
# before anything in the extensions volume is replaced.
#
# The Zenysis repositories have no tags or releases, so their URLs pin the
# master commit current on 2026-10-04; each jar is byte-identical to what
# `raw/master` served. The checksums are taken from those downloads (trust on
# first use). druid-datasketches matches the .sha1 the Apache repository
# publishes for it.
#
# Upgrading Druid (WP-8b) means a new set of jars: replace all of these lines.
set -euo pipefail

destination=/druid/extensions

# "<sha256>  <path under $destination>  <url>"
downloads=(
    "cfc5910193b63e87c6455a761eaf6513deb57d0ffc267244f41e9298dd21545a  druid-aggregatable-first-last/druid-aggregatable-first-last-0.23.0.jar  https://github.com/Zenysis/druid-aggregatable-first-last/raw/c69abb35cc911eb4adb0276787ff462bd6df81e2/dist/druid-aggregatable-first-last-0.23.0.jar"
    "a7bb1c6ced44de704dc0c741b4a76524e178e25eecdf9d89f0442dc6ac9af144  druid-arbitrary-granularity/druid-arbitrary-granularity-0.23.0.jar  https://github.com/Zenysis/druid-arbitrary-granularity/raw/55af5cf3166ba2610c33e94246ec46d36653cf39/dist/druid-arbitrary-granularity-0.23.0.jar"
    "84393742ac71c284bbdf4352843ca034a9b3402427f1268738ab2ff5a5ecb814  druid-nested-json-parser/druid-nested-json-parser-0.23.0.jar  https://github.com/Zenysis/druid-nested-json-parser/raw/10b4285478416acc570e5f4f5081a21b05809f4a/dist/druid-nested-json-parser-0.23.0.jar"
    "30ba7eec3974f0971af06ca8c99d34b09d23a0206d5b6a0a06c6dbfacd73a9b1  druid-tuple-sketch-expansion/druid-tuple-sketch-expansion-0.23.0.jar  https://github.com/Zenysis/druid-tuple-sketch-expansion/raw/9a3c17b98813e7ac2ca584b7f332bb5683f8fb5e/dist/druid-tuple-sketch-expansion-0.23.0.jar"
    # druid-tuple-sketch-expansion needs the datasketches jar next to it.
    "02af57bcf5009c61df9b1e01efa4d4255207571d93c8c27fb25654e08c9ed219  druid-tuple-sketch-expansion/druid-datasketches-0.23.0.jar  https://repository.apache.org/content/groups/public/org/apache/druid/extensions/druid-datasketches/0.23.0/druid-datasketches-0.23.0.jar"
)

staging=$(mktemp -d)
trap 'rm -rf "$staging"' EXIT

for entry in "${downloads[@]}"; do
    read -r sha256 path url <<<"$entry"
    echo "Downloading $path"
    mkdir -p "$staging/$(dirname "$path")"
    wget -q -O "$staging/$path" "$url"
    echo "$sha256  $staging/$path" | sha256sum -c -
done

mkdir -p "$destination"
rm -rf "${destination:?}"/*
cp -R "$staging"/. "$destination"/
