#!/usr/bin/env bash
# Build the public tournament page (analysis/site/index.html).
#
#   ./analysis/deploy-site.sh            build only
#   ./analysis/deploy-site.sh commit     build + commit the page
#
# Deploying is deliberately left to you -- this script never pushes and makes
# no assumption about your remote or branch name. Two ways to publish:
#
#   a) Connect this repo to Netlify once (Add new site -> Import an existing
#      project). netlify.toml is picked up automatically: publish directory is
#      analysis/site, no build command, and the `ignore` rule means only a
#      changed page triggers a deploy. Then a normal `git push` publishes.
#
#   b) Without Git: `netlify deploy --dir=analysis/site --prod`
#      or drag the analysis/site folder onto https://app.netlify.com/drop
#
set -euo pipefail
cd "$(dirname "$0")/.."
MODE="${1:-build}"

echo "1/2  Refreshing fixtures (openfootball)..."
if PYTHONPATH=src python3 -m wm_tipps.cli refresh-fixtures >/dev/null 2>&1; then
  echo "     ok"
else
  echo "     (refresh failed -- using existing data/fixtures.json)"
fi

echo "2/2  Building the page..."
python3 analysis/wm_journey.py

if [ "$MODE" = "commit" ]; then
  git add analysis/site/index.html
  if git diff --cached --quiet; then
    echo "     No change -- nothing to commit."
  else
    git commit -q -m "site: refresh tournament page"
    echo "     Committed. Publish with your own deploy step (see header)."
  fi
else
  echo "     Built. Open analysis/site/index.html, or publish (see header)."
fi
