#!/usr/bin/env bash
# One command to finish the Recall deploy on the existing EC2 host ("mini"). Run from the repo root:
#   cp deploy/host.env.example deploy/host.env  # fill in, then:
#   bash deploy/go.sh
# Steps: AWS role+port -> server .env (fresh HMAC key + admin token; secrets never printed) -> service -> seed -> HTTPS tunnel.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f deploy/host.env ] || { echo "Create deploy/host.env from deploy/host.env.example first."; exit 1; }
source deploy/host.env
HOST=$RECALL_HOST; KEY=$RECALL_KEY
SSH="ssh -i $KEY -o IdentitiesOnly=yes ubuntu@$HOST"

echo "== 1/5 AWS: Bedrock role + port 8300"; python3 deploy/aws_setup.py

echo "== 2/5 server .env"
if $SSH '[ -f ~/recall/.env ]'; then echo "kept existing ~/recall/.env"; else
  ADMIN=$(openssl rand -hex 16); HMAC=$(openssl rand -hex 24)
  {
    grep -E '^(OPENROUTER_API_KEY|JEV_MODEL|VISION_MODEL|DECISION_MODEL|NARRATOR_MODEL|NTFY_TOPIC)=' .env
    echo "AWS_REGION=us-east-1"; echo "SERVER_URL=http://127.0.0.1:8300"
    echo "RING_HMAC_KEY=$HMAC"; echo "ADMIN_TOKEN=$ADMIN"; echo "RECALL_WORKERS=2"
  } | $SSH 'umask 077; cat > ~/recall/.env'
  echo "ADMIN_TOKEN (needed only to re-seed): $ADMIN"
fi

echo "== 3/5 service"; deploy/deploy.sh $HOST $KEY

echo "== 4/5 seed on the server (real pipeline, Bedrock via the instance role)"
$SSH 'set -e; cd ~/recall; T=$(grep ^ADMIN_TOKEN= .env | cut -d= -f2)
  curl -sf -X POST -H "X-Admin-Token: $T" -H "content-type: application/json" -d "{\"reset\":true}" http://127.0.0.1:8300/api/demo/seed >/dev/null
  for i in $(seq 1 90); do sleep 4; curl -s "http://127.0.0.1:8300/api/feed?after=0" | grep -q "Seed complete" && break; done
  curl -s "http://127.0.0.1:8300/api/feed?after=0" | python3 -c "
import sys,json; f=json.load(sys.stdin)
print([x[\"message\"] for x in f if x[\"type\"]==\"info\"][-1:]); print(\"errors:\", [x[\"message\"][:120] for x in f if x[\"type\"]==\"error\"][:3])"'

echo "== 5/5 HTTPS tunnel (Cloudflare quick tunnel as a service)"
$SSH 'set -e
  command -v cloudflared >/dev/null || { curl -sL -o /tmp/cf.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb && sudo dpkg -i /tmp/cf.deb >/dev/null; }
  printf "[Unit]\nDescription=Recall HTTPS tunnel\nAfter=recall.service\n[Service]\nUser=ubuntu\nExecStart=/usr/bin/cloudflared tunnel --no-autoupdate --url http://127.0.0.1:8300\nRestart=always\nRestartSec=5\n[Install]\nWantedBy=multi-user.target\n" | sudo tee /etc/systemd/system/recall-tunnel.service >/dev/null
  sudo systemctl daemon-reload && sudo systemctl enable --now recall-tunnel >/dev/null 2>&1; sleep 12
  echo "HTTPS: $(sudo journalctl -u recall-tunnel --no-pager | grep -o "https://[a-z0-9-]*\.trycloudflare\.com" | tail -1)"'
echo "HTTP (stable while the instance keeps its IP): http://$HOST:8300"
