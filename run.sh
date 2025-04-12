#! /usr/bin/env nix-shell
#! nix-shell -I nixpkgs=https://github.com/NixOS/nixpkgs/archive/e44462d6021bfe23dfb24b775cc7c390844f773d.tar.gz -i bash -p bash mitmproxy mitmproxy2swagger openapi-generator-cli python310Packages.pyyaml python310Packages.requests python310Packages.beautifulsoup4 python310Packages.stringcase

if [ -z "$APP_TOKEN" ]; then
    >&2 echo "ERROR: Application authorization token undefined"
    exit 1
fi

if [ -z "$USER_TOKEN" ]; then
    >&2 echo "WARNING: User authorization token undefined, some endpoints will not be used"
fi

[ -z "$BASE_URI" ] && BASE_URI="https://uexcorp.space/api"

if [ -n "$NO_CAPTURE" ]; then
    echo "Skipping capture..."

else
  echo "Starting MITM web proxy..."
  mitmweb --no-web-open-browser -w flows &
  MITMWEB_PID=$!

  function cleanup() {
      kill $MITMWEB_PID
  }
  trap cleanup EXIT

  sleep 3

  export HTTP_PROXY="http://127.0.0.1:8080"
  export HTTPS_PROXY="http://127.0.0.1:8080"

  function get() {
      curl --silent --insecure \
          -x "http://127.0.0.1:8080" \
          -H "Authorization: Bearer $APP_TOKEN" \
          -H "secret_token: $USER_TOKEN" $@
  }

  function post() {
      get -X POST $@
  }

  echo "Running the API requests..."
  python generator.py collect --no-api-cache

  echo "Finished processing API requests..."
  sleep 1

fi

rm openapi.yaml

echo "Generating OpenAPI specification..."
mitmproxy2swagger -i flows --format flow -o openapi.yaml -p "$BASE_URI"
sleep 1
python generator.py apply-path-templates
sleep 1
mitmproxy2swagger -i flows --format flow -o openapi.yaml -p "$BASE_URI" --examples
sleep 1
python generator.py fixup
sleep 1
python generator.py merge
sleep 1
