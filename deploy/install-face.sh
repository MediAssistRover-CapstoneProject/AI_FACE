#!/usr/bin/env bash
# Stage a verified release on the existing media instance; never opens firewall ports.
set -Eeuo pipefail
[[ $EUID == 0 ]] || { echo 'Run as root.' >&2; exit 2; }
release=${1:?usage: deploy/install-face.sh RELEASE_SHA}
[[ $release =~ ^[a-f0-9]{40}$ ]] || { echo 'Expected a 40-character release SHA.' >&2; exit 2; }
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
environment=/etc/mediassistrover/face-ai.env
[[ -s $environment && $(stat -c '%u:%a' "$environment") == 0:600 ]] || {
    echo 'Provision the root-owned face-ai.env (mode 600) before deploying.' >&2
    exit 2
}
# Parse only supported values, never source a secret file as executable shell code.
host=$(python3 - "$environment" <<'PY'
import ipaddress, sys
values = {}
for line in open(sys.argv[1], encoding='utf-8'):
    if line.strip() and not line.lstrip().startswith('#') and '=' in line:
        key, value = line.rstrip('\n').split('=', 1)
        values[key] = value
if len(values.get('FACE_SERVICE_KEY', '')) < 32:
    raise SystemExit('FACE_SERVICE_KEY must contain at least 32 characters.')
host = values.get('FACE_BIND_HOST', '127.0.0.1')
try:
    address = ipaddress.IPv4Address(host)
except ValueError:
    raise SystemExit('FACE_BIND_HOST must be an IPv4 address.')
allowed = ('127.0.0.0/8', '10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16')
if not any(address in ipaddress.ip_network(network) for network in allowed):
    raise SystemExit('Face service must bind loopback or a private VPC address.')
if values.get('FACE_NATIVE_THREADS', '1') != '1':
    raise SystemExit('This shared-media deployment requires FACE_NATIVE_THREADS=1.')
print(host)
PY
)
python3 - <<'PY'
import hashlib, json
from pathlib import Path
root = Path('models')
for item in json.loads((root / 'manifest.json').read_text()).values():
    path = root / item['file']
    if path.name != item['file'] or hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
        raise SystemExit('MODEL_CHECKSUM_MISMATCH')
PY

umask 022
root=/opt/mar-face
unit=/etc/systemd/system/face-ai.service
exec 9>/run/lock/mar-face-deploy.lock
flock -n 9 || { echo 'Another face deploy is running.' >&2; exit 1; }
getent passwd marface >/dev/null || useradd --system --user-group --no-create-home --shell /usr/sbin/nologin marface
install -d -m 0755 "$root/releases" "$root/venvs"
previous=$(readlink "$root/current" 2>/dev/null || true)
if [[ -n $previous && ( $previous != "$root/releases/"* || ! -d $previous ) ]]; then
    echo 'Unexpected current release path.' >&2
    exit 2
fi
target=$root/releases/$release
stage=$(mktemp -d "$root/.face-stage.XXXXXX")
switched=false
if [[ -f $unit ]]; then cp -p "$unit" "$stage/previous.service"; fi
cleanup() {
    status=$?
    if (( status != 0 )) && $switched; then
        systemctl stop face-ai || true
        if [[ -f $stage/previous.service ]]; then
            install -m 0644 "$stage/previous.service" "$unit"
        else
            rm -f -- "$unit"
        fi
        if [[ -n $previous ]]; then
            ln -s "$previous" "$stage/restore"
            mv -Tf "$stage/restore" "$root/current"
            systemctl daemon-reload
            systemctl restart face-ai || true
        else
            rm -f -- "$root/current"
            systemctl daemon-reload
        fi
    fi
    rm -rf -- "$stage"
    return "$status"
}
trap cleanup EXIT

if [[ ! -d $target ]]; then
    python3 -c 'import ensurepip' || { echo 'Install python3-venv before deploying.' >&2; exit 2; }
    venv_hash=$( { sha256sum requirements.lock.txt; python3 -V; } | sha256sum | cut -c1-40 )
    venv=$root/venvs/$venv_hash
    if [[ ! -f $venv/.ready ]]; then
        python3 -m venv "$venv"
        nice -n 10 "$venv/bin/python" -m pip install --only-binary=:all: --disable-pip-version-check -r requirements.lock.txt
        touch "$venv/.ready"
    fi
    install -d -m 0755 "$stage/release/models"
    install -m 0644 app.py requirements.lock.txt "$stage/release/"
    install -m 0644 models/manifest.json models/*.onnx "$stage/release/models/"
    ln -s "$venv" "$stage/release/.venv"
    mv -T "$stage/release" "$target"
fi
ln -s "$target" "$stage/current"
switched=true
install -m 0644 deploy/face-ai.service "$unit"
mv -Tf "$stage/current" "$root/current"
systemctl daemon-reload
systemctl restart face-ai
for attempt in $(seq 1 30); do
    if curl -fsS --max-time 2 "http://$host:8095/health/ready" 2>/dev/null |
       python3 -c 'import json,sys; d=json.load(sys.stdin); assert d.get("ready") is True and len(d.get("modelVersion","")) == 64' 2>/dev/null; then
        systemctl enable face-ai >/dev/null
        echo "FACE_READY release=$release"
        exit 0
    fi
    sleep 1
done
echo 'Face release failed readiness. Restoring the previous release.' >&2
exit 1
