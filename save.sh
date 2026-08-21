#!/bin/bash

set -e

echo "📦 Saving Ezra project..."

# Ask for a milestone name and turn it into a Git-safe tag. The readable
# milestone name is retained in the annotated tag message.
read -r -p "Milestone name: " milestone

if [ -z "$milestone" ]; then
  echo "❌ A milestone name is required."
  exit 1
fi

milestone_tag=$(printf '%s' "$milestone" \
  | tr '[:space:]' '-' \
  | sed 's/[^A-Za-z0-9._-]/-/g; s/-\{2,\}/-/g; s/^[.-]*//; s/[.-]*$//')

if [ -z "$milestone_tag" ] || ! git check-ref-format "refs/tags/$milestone_tag"; then
  echo "❌ That milestone name cannot be converted into a valid Git tag."
  exit 1
fi

if git rev-parse -q --verify "refs/tags/$milestone_tag" >/dev/null; then
  echo "❌ Milestone '$milestone_tag' already exists. Choose another name."
  exit 1
fi

# Add all changes
python3 tools/build_command_reference.py
git add .

# Ask for commit message
read -r -p "Commit message [Milestone: $milestone]: " msg

# Default message if empty
if [ -z "$msg" ]; then
  msg="Milestone: $milestone"
fi

# Commit when there are staged changes. This also allows an existing commit to
# be marked as a milestone without forcing an empty commit.
if git diff --cached --quiet; then
  echo "ℹ️ No new changes to commit; tagging the current commit."
else
  git commit -m "$msg"
fi

# Mark this exact backup so it is easy to find or restore later.
git tag -a "$milestone_tag" -m "$milestone"

# Push the commit and its milestone tag.
git push
git push origin "$milestone_tag"

echo "✅ Saved to GitHub as milestone: $milestone_tag"
