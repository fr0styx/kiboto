#!/bin/sh
# Prints the image this CI run built, as soon as its build job has handed over the digest:
#
#   sh scripts/ci_wait_build.sh <artifact> "<build job name>"
#   sh scripts/ci_wait_build.sh digest-full "Build multi-arch image (full)"
#
# Lets a job do its slow setup (the Kiboto OS check boots its virtual machine) while the image is
# still being built, instead of starting only after it. Fails as soon as that build job ends
# without the digest (failed, cancelled or skipped), and after KB_WAIT_MINUTES (default 40).
# Needs gh, GH_TOKEN with actions: read, GITHUB_REPOSITORY and GITHUB_RUN_ID (set in Actions).
# A second call in the same job answers at once from the digest already downloaded.
set -eu
NAME=${1:?artifact name}
JOB=${2:?build job name}
REPO=${KB_IMAGE_REPO:-ghcr.io/fr0styx/kiboto}
LIMIT=${KB_WAIT_MINUTES:-40}
API=repos/$GITHUB_REPOSITORY/actions/runs/$GITHUB_RUN_ID
OUT=${RUNNER_TEMP:-/tmp}/kb-wait-$NAME
END=$(( $(date +%s) + LIMIT * 60 ))
T0=$(date +%s)

while :; do
  if [ ! -s "$OUT/digest.txt" ]; then
    n=$(gh api "$API/artifacts?name=$NAME" --jq '.total_count' 2>/dev/null || echo 0)
    if [ "${n:-0}" -gt 0 ] 2>/dev/null; then
      rm -rf "$OUT"
      gh run download "$GITHUB_RUN_ID" -R "$GITHUB_REPOSITORY" -n "$NAME" -D "$OUT" >&2 || rm -rf "$OUT"
    fi
  fi
  if [ -s "$OUT/digest.txt" ]; then
    d=$(tr -d ' \n' < "$OUT/digest.txt")
    if ! printf '%s' "$d" | grep -Eq '^sha256:[0-9a-f]{64}$'; then
      echo "the build handed over no digest: $d" >&2
      exit 1
    fi
    echo "the build was ready after waiting $(( $(date +%s) - T0 )) s" >&2
    printf '%s@%s\n' "$REPO" "$d"
    exit 0
  fi
  state=$(gh api "$API/jobs?per_page=100" --paginate \
    --jq ".jobs[] | select(.name == \"$JOB\") | .status + \" \" + (.conclusion // \"\")" 2>/dev/null | head -1 || true)
  case "$state" in
    "completed success" | "" | queued* | in_progress* | waiting* | pending*) ;;
    completed*) echo "\"$JOB\" ended ($state) without handing over the image" >&2; exit 1 ;;
  esac
  if [ "$(date +%s)" -ge "$END" ]; then
    echo "no image from \"$JOB\" after $LIMIT minutes" >&2
    exit 1
  fi
  sleep 5
done
