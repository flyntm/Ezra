#!/bin/bash

echo "📦 Saving Ezra project..."

# Add all changes
git add .

# Ask for commit message
read -p "Commit message: " msg

# Default message if empty
if [ -z "$msg" ]; then
  msg="update"
fi

# Commit
git commit -m "$msg"

# Push
git push

echo "✅ Saved to GitHub"
