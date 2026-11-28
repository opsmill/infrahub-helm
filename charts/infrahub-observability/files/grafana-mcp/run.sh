#!/bin/sh
# Run create-service-account.sh in the hook Job of the Grafana MCP server.
#
# That script only reads and writes a file. This wrapper moves the token between
# the Kubernetes Secret and that file, with curl and the pod's own service
# account, because the Grafana image has no kubectl and no jq:
#   1. Read the Secret into the token file, when the Secret exists.
#   2. Run create-service-account.sh. It keeps a token that still works and
#      replaces one that Grafana refuses.
#   3. Write the Secret again, only when the token file changed.
# It never prints a token.
#
# Settings (environment variables):
#   GRAFANA_MCP_TOKEN_SECRET   Name of the Secret that holds the Grafana token
#   GRAFANA_MCP_TOKEN_FILE     File that receives the token (also read by the script)
set -eu

secret_name="${GRAFANA_MCP_TOKEN_SECRET}"
token_file="${GRAFANA_MCP_TOKEN_FILE}"
secret_key="token"
service_account_dir=/var/run/secrets/kubernetes.io/serviceaccount
namespace="$(cat "$service_account_dir/namespace")"
secrets_url="https://kubernetes.default.svc/api/v1/namespaces/$namespace/secrets"

# No file created here is readable by another user.
umask 077

work_dir="$(mktemp -d)"
trap 'rm -rf "$work_dir"' EXIT
body_file="$work_dir/body"

fail() {
    echo "$1" >&2
    exit 1
}

# curl reads the bearer token of the pod's service account from this file, so it is
# not in the process arguments.
printf 'header = "Authorization: Bearer %s"\n' "$(cat "$service_account_dir/token")" > "$work_dir/kube.curlrc"

# Call the Kubernetes API. Writes the answer to $body_file and prints the HTTP status.
# A request that gets no answer prints 000.
kube_request() {
    method="$1"
    url="$2"
    if [ "$#" -ge 3 ]; then
        set -- --header "Content-Type: application/json" --data-binary "@$3"
    else
        set --
    fi
    curl --silent --max-time 30 --cacert "$service_account_dir/ca.crt" --config "$work_dir/kube.curlrc" \
        --request "$method" --output "$body_file" --write-out '%{http_code}' "$@" "$url" 2>/dev/null || true
}

# 1. Read the Secret into the token file.
mkdir -p "$(dirname "$token_file")"
rm -f "$token_file"
secret_exists=no
status="$(kube_request GET "$secrets_url/$secret_name")"
case "$status" in
    200)
        secret_exists=yes
        sed -n "s/.*\"$secret_key\": *\"\\([^\"]*\\)\".*/\\1/p" "$body_file" | head -n 1 | base64 -d > "$token_file" 2>/dev/null || true
        if [ ! -s "$token_file" ]; then
            rm -f "$token_file"
        fi
        ;;
    404) ;;
    *) fail "The Kubernetes API answered HTTP $status when asked to read the Secret $secret_name" ;;
esac
original_token_file="$work_dir/original-token"
if [ -f "$token_file" ]; then
    cp "$token_file" "$original_token_file"
fi

# 2. Create the service account and its token, or keep the ones that work.
sh "$(dirname "$0")/create-service-account.sh"
[ -s "$token_file" ] || fail "No token file after create-service-account.sh"

# 3. Write the Secret when the token is new or changed.
if [ -f "$original_token_file" ] && cmp -s "$token_file" "$original_token_file"; then
    exit 0
fi
encoded="$(base64 < "$token_file" | tr -d '\n')"
printf '{"apiVersion":"v1","kind":"Secret","metadata":{"name":"%s","namespace":"%s"},"type":"Opaque","data":{"%s":"%s"}}' \
    "$secret_name" "$namespace" "$secret_key" "$encoded" > "$work_dir/secret.json"
unset encoded
if [ "$secret_exists" = yes ]; then
    status="$(kube_request PUT "$secrets_url/$secret_name" "$work_dir/secret.json")"
else
    status="$(kube_request POST "$secrets_url" "$work_dir/secret.json")"
fi
case "$status" in
    200 | 201) echo "Stored the token of the Grafana service account in the Secret $secret_name" ;;
    *) fail "The Kubernetes API answered HTTP $status when asked to write the Secret $secret_name" ;;
esac
