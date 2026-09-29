#!/usr/bin/env bash
# Deploy Recall to an existing Ubuntu host as a systemd service on 127.0.0.1:8300 (does not touch other services).
#   deploy/deploy.sh <host> <ssh-key> [user]
# Secrets are NOT synced: create /home/ubuntu/recall/.env on the host yourself (see .env.example).
set -euo pipefail
HOST=${1:?host}; KEY=${2:?ssh key}; USER_=${3:-ubuntu}
SSH="ssh -i $KEY -o IdentitiesOnly=yes $USER_@$HOST"
rsync -az --delete -e "ssh -i $KEY -o IdentitiesOnly=yes" \
  --exclude '.git' --exclude '.env' --exclude 'data' --exclude 'media' --exclude '__pycache__' --exclude '.venv' --exclude '.pytest_cache' \
  ./ "$USER_@$HOST:/home/$USER_/recall/"
$SSH 'set -e
  command -v ffmpeg >/dev/null || sudo apt-get install -y ffmpeg
  python3 -c "import venv, ensurepip" 2>/dev/null || sudo apt-get install -y python3-venv
  cd ~/recall && [ -d .venv ] || python3 -m venv .venv
  .venv/bin/pip install -q -r requirements.txt
  [ -f .env ] || { echo "MISSING ~/recall/.env — create it, then re-run"; exit 2; }
  sudo cp deploy/recall.service /etc/systemd/system/recall.service
  sudo systemctl daemon-reload && sudo systemctl enable --now recall && sleep 3
  curl -sf http://127.0.0.1:8300/health && echo " recall healthy"'
