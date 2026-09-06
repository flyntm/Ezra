#!/bin/bash

set -euo pipefail

project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source_unit="$project_dir/systemd/ezra.service"
user_unit_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
installed_unit="$user_unit_dir/ezra.service"
python_path="$project_dir/ezra311-env/bin/python"
respeaker_helper="$project_dir/tools/ezra-reset-respeaker"
respeaker_sudoers="$project_dir/systemd/ezra-respeaker-sudoers"

if [ ! -x "$python_path" ]; then
  echo "❌ Ezra's Python environment was not found at $python_path"
  exit 1
fi

if [ "$project_dir" != "$HOME/projects/ezra" ]; then
  echo "❌ The service expects Ezra at $HOME/projects/ezra, but this copy is at $project_dir"
  echo "   Update systemd/ezra.service if this Pi uses a different location."
  exit 1
fi

mkdir -p "$user_unit_dir"
install -m 0644 "$source_unit" "$installed_unit"
sudo install -o root -g root -m 0755 \
  "$respeaker_helper" /usr/local/sbin/ezra-reset-respeaker
sudo visudo -cf "$respeaker_sudoers"
sudo install -o root -g root -m 0440 \
  "$respeaker_sudoers" /etc/sudoers.d/ezra-respeaker

systemctl --user daemon-reload
systemctl --user enable ezra.service
systemctl --user restart ezra.service

echo "✅ Ezra is enabled and has been started."
echo "   Status: systemctl --user status ezra"
echo "   Logs:   journalctl --user-unit=ezra.service -f"
