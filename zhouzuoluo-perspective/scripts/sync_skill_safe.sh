#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  sync_skill_safe.sh [--apply] [--with-sources] [source_dir] [target_dir]

Defaults:
  source_dir = the skill directory that contains this script
  target_dir = ~/.codex/skills/<skill-name>

Behavior:
  - Runs in dry-run mode by default.
  - Uses rsync --delete for normal skill files.
  - Protects source corpora from accidental deletion unless --with-sources is provided:
    - references/sources/books/
    - references/sources/articles/
    - references/sources/transcripts/

Examples:
  ./scripts/sync_skill_safe.sh
  ./scripts/sync_skill_safe.sh --apply
  ./scripts/sync_skill_safe.sh --apply ./ ./.mirror/zhouzuoluo-perspective
  ./scripts/sync_skill_safe.sh --apply --with-sources
USAGE
}

script_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
source_default="$(cd -- "$script_dir/.." && pwd)"
skill_name="$(basename -- "$source_default")"
target_default="$HOME/.codex/skills/$skill_name"

apply=0
with_sources=0
positional=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply)
      apply=1
      shift
      ;;
    --with-sources)
      with_sources=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      positional+=("$@")
      break
      ;;
    -* )
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
    *)
      positional+=("$1")
      shift
      ;;
  esac
done

source_dir="${positional[0]:-$source_default}"
target_dir="${positional[1]:-$target_default}"

if [[ ! -d "$source_dir" ]]; then
  echo "Source dir not found: $source_dir" >&2
  exit 1
fi

mkdir -p "$target_dir"
mkdir -p "$target_dir/references/sources/books"
mkdir -p "$target_dir/references/sources/articles"
mkdir -p "$target_dir/references/sources/transcripts"

rsync_args=( -av --delete )
if [[ $apply -eq 0 ]]; then
  rsync_args+=( --dry-run )
fi

if [[ $with_sources -eq 0 ]]; then
  rsync_args+=(
    --exclude 'references/sources/books/***'
    --exclude 'references/sources/articles/***'
    --exclude 'references/sources/transcripts/***'
  )
fi

printf 'Mode: %s\n' "$([[ $apply -eq 1 ]] && echo APPLY || echo DRY-RUN)"
printf 'Source: %s\n' "$source_dir"
printf 'Target: %s\n' "$target_dir"
printf 'Protect source corpora: %s\n' "$([[ $with_sources -eq 1 ]] && echo no || echo yes)"
printf '\nSource corpus counts:\n'
find "$source_dir/references/sources/books" -maxdepth 1 -type f | wc -l | awk '{print "  books: " $1}'
find "$source_dir/references/sources/articles" -maxdepth 1 -type f | wc -l | awk '{print "  articles: " $1}'
find "$source_dir/references/sources/transcripts" -maxdepth 1 -type f | wc -l | awk '{print "  transcripts: " $1}'
printf 'Target corpus counts before sync:\n'
find "$target_dir/references/sources/books" -maxdepth 1 -type f | wc -l | awk '{print "  books: " $1}'
find "$target_dir/references/sources/articles" -maxdepth 1 -type f | wc -l | awk '{print "  articles: " $1}'
find "$target_dir/references/sources/transcripts" -maxdepth 1 -type f | wc -l | awk '{print "  transcripts: " $1}'
printf '\n'

rsync "${rsync_args[@]}" "$source_dir/" "$target_dir/"

if [[ $apply -eq 1 ]]; then
  printf '\nTarget corpus counts after sync:\n'
  find "$target_dir/references/sources/books" -maxdepth 1 -type f | wc -l | awk '{print "  books: " $1}'
  find "$target_dir/references/sources/articles" -maxdepth 1 -type f | wc -l | awk '{print "  articles: " $1}'
  find "$target_dir/references/sources/transcripts" -maxdepth 1 -type f | wc -l | awk '{print "  transcripts: " $1}'
fi
