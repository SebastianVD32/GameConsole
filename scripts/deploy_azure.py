"""Transfer a verified CI bundle using a short-lived download URL, never a GitHub token."""
import base64
import json
import os
import subprocess
import urllib.error
import urllib.request

sha = os.environ['RELEASE_SHA']
assert len(sha) == 40 and all(c in '0123456789abcdef' for c in sha)
repo = os.environ['GITHUB_REPOSITORY']
headers = {'Authorization': 'Bearer ' + os.environ['GH_TOKEN'], 'Accept': 'application/vnd.github+json'}
url = f"https://api.github.com/repos/{repo}/actions/runs/{int(os.environ['SOURCE_RUN'])}/artifacts"
with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as response:
    artifacts = json.load(response)['artifacts']
artifact = next(a for a in artifacts if a['name'] == 'gameconsole-deploy-' + sha and not a['expired'])
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None
try:
    urllib.request.build_opener(NoRedirect).open(urllib.request.Request(artifact['archive_download_url'], headers=headers), timeout=30)
    raise RuntimeError('Expected a signed artifact redirect')
except urllib.error.HTTPError as error:
    if error.code != 302:
        raise
    download = error.headers['Location']
assert download.startswith('https://')
# Mask the temporary URL; no registry credential is sent to or stored on Azure.
print('::add-mask::' + download)
script = r'''set -Eeuo pipefail
exec 9>/opt/gameconsole/deploy.lock
flock -w 600 9
base=/opt/gameconsole
stage=$(mktemp -d "$base/release.XXXXXX")
trap 'rm -rf "$stage"' EXIT
'''
script += 'curl --fail --silent --show-error --location ' + "'" + download.replace("'", "'\\''") + "' -o \"$stage/bundle.zip\"\n"
script += r'''python3 -m zipfile -e "$stage/bundle.zip" "$stage/files"
docker load -i "$stage/files/images.tar"
cp -a "$base/deploy" "$stage/previous"
rollback() {
  trap - ERR
  cp -a "$stage/previous/." "$base/deploy/"
  cd "$base/deploy"
  docker compose -f compose.yaml -f azure/compose.yaml up --pull never --wait --wait-timeout 180 -d
  echo ROLLBACK_COMPLETED
  exit 1
}
trap rollback ERR
cp "$stage/files/compose.yaml" "$base/deploy/compose.yaml"
cp -a "$stage/files/azure/." "$base/deploy/azure/"
'''
script += f"sed -i 's/^GAMECONSOLE_TAG=.*/GAMECONSOLE_TAG=sha-{sha}/' \"$base/deploy/.env\"\n"
script += r'''cd "$base/deploy"
docker compose -f compose.yaml -f azure/compose.yaml up --pull never --wait --wait-timeout 180 -d
curl --fail --silent --retry 6 --retry-delay 5 https://gameconsole-nkx6wjmnfl4di.eastus.cloudapp.azure.com/api/salud
trap - ERR
echo DEPLOYMENT_OK
'''
encoded = base64.b64encode(script.encode()).decode()
result = subprocess.run(['az', 'vm', 'run-command', 'invoke', '-g', 'rg-gameconsole', '-n', 'gameconsole', '--command-id', 'RunShellScript', '--scripts', f"echo '{encoded}' | base64 -d | bash", '-o', 'json'], capture_output=True, text=True)
if result.returncode:
    raise SystemExit('Azure Run Command failed; inspect the Azure operation.')
messages = '\n'.join(x.get('message', '') for x in json.loads(result.stdout).get('value', []))
if 'DEPLOYMENT_OK' not in messages:
    raise SystemExit('Deployment failed; inspect VM services and rollback status.')
print('Production deployment verified:', sha)
