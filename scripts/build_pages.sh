#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
output_dir="${1:-$repo_root/.pages-site}"

if [[ -z "$output_dir" || "$output_dir" == "/" || "$output_dir" == "$repo_root" ]]; then
  echo "Refusing unsafe Pages output directory: $output_dir" >&2
  exit 2
fi

install -d "$output_dir/assets"

# The accepted review prototype is the v1 source of truth. The published page
# lives at the artifact root, so only its relative asset prefix changes here.
sed 's#\.\./assets/#assets/#g' \
  "$repo_root/docs/prototypes/castfabric-landing-v1.html" \
  > "$output_dir/index.html"

cp "$repo_root/docs/assets/castfabric-mark.svg" "$output_dir/assets/"
cp "$repo_root/docs/assets/console-overview.png" "$output_dir/assets/"
cp "$repo_root/docs/assets/console-mobile.png" "$output_dir/assets/"

printf '' > "$output_dir/.nojekyll"
printf '%s\n' 'User-agent: *' 'Allow: /' > "$output_dir/robots.txt"

if rg -n '\.\./assets/|file://' "$output_dir/index.html"; then
  echo "Published HTML still contains a local-only path" >&2
  exit 3
fi

for required in \
  "$output_dir/index.html" \
  "$output_dir/assets/castfabric-mark.svg" \
  "$output_dir/assets/console-overview.png" \
  "$output_dir/assets/console-mobile.png"; do
  test -s "$required"
done

echo "Built CastFabric Pages artifact at $output_dir"
