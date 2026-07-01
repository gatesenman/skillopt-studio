#!/usr/bin/env bash
# One-click build of the SkillOpt Studio desktop app.
set -euo pipefail
cd "$(dirname "$0")/.."

python -m pip install --upgrade pip
pip install -e ".[build]"

echo "Building SkillOpt Studio with PyInstaller..."
pyinstaller --noconfirm packaging/skillopt_studio.spec

echo
echo "Done. App bundle is in: dist/SkillOptStudio/"
echo "Run it:  ./dist/SkillOptStudio/SkillOptStudio"
