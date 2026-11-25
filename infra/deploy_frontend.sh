#!/bin/bash
# Deploy the TazeRota panel (ui/server.py + ui/static + app/agent/engine) as a public Lambda Function URL.
# Idempotent: creates on first run, updates code/config on later runs.
# Usage (from the project root):  bash infra/deploy_frontend.sh
# Remove:                          bash infra/deploy_frontend.sh --delete
set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"
FN="tazerota-panel"
ROLE="tazerota-panel-role"
LAYER="arn:aws:lambda:${REGION}:753240598075:layer:LambdaAdapterLayerArm64:30"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUILD="${ROOT}/infra/.build"
CREDS="${ROOT}/infra/.panel-credentials"   # gitignored: PANEL_USER / PANEL_PASSWORD
ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"

if [[ "${1:-}" == "--delete" ]]; then
  aws lambda delete-function-url-config --function-name "$FN" --region "$REGION" 2>/dev/null || true
  aws lambda delete-function --function-name "$FN" --region "$REGION" 2>/dev/null || true
  aws iam delete-role-policy --role-name "$ROLE" --policy-name tazerota-panel-access 2>/dev/null || true
  aws iam detach-role-policy --role-name "$ROLE" \
    --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole 2>/dev/null || true
  aws iam delete-role --role-name "$ROLE" 2>/dev/null || true
  echo "deleted $FN"
  exit 0
fi

RUNTIME_ARN="${AGENT_RUNTIME_ARN:-$(cd "$ROOT" && agentcore status --json | python3 -c \
  'import json,sys; t=sys.stdin.read(); d=json.loads(t[t.index("{"):]); print(next(r["arn"] for r in d["resources"] if r["resourceType"]=="runtime"))')}"
echo "agent runtime: $RUNTIME_ARN"

# ---- credentials (generated once, reused on redeploy)
if [[ ! -f "$CREDS" ]]; then
  umask 077
  printf 'PANEL_USER=tazerota\nPANEL_PASSWORD=%s\n' "$(python3 -c 'import secrets; print(secrets.token_urlsafe(9))')" > "$CREDS"
fi
# shellcheck disable=SC1090
source "$CREDS"

# ---- package (arm64 wheels, Python 3.12)
rm -rf "$BUILD" && mkdir -p "$BUILD/pkg/app/agent" "$BUILD/pkg/ui"
uv pip install --quiet --target "$BUILD/pkg" --python-platform aarch64-manylinux2014 --python-version 3.12 \
  --only-binary=:all: "fastapi>=0.115" "uvicorn>=0.30" "boto3>=1.40"
cp -r "$ROOT/app/agent/engine" "$BUILD/pkg/app/agent/"
cp "$ROOT/ui/server.py" "$BUILD/pkg/ui/" && cp -r "$ROOT/ui/static" "$BUILD/pkg/ui/"
cp "$ROOT/infra/run.sh" "$BUILD/pkg/run.sh" && chmod +x "$BUILD/pkg/run.sh"
find "$BUILD/pkg" -name "__pycache__" -type d -prune -exec rm -rf {} +
(cd "$BUILD/pkg" && zip -qr9 "$BUILD/panel.zip" .)
echo "package: $(du -h "$BUILD/panel.zip" | cut -f1)"

# ---- IAM role (least privilege)
TRUST='{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]}'
if ! aws iam get-role --role-name "$ROLE" >/dev/null 2>&1; then
  aws iam create-role --role-name "$ROLE" --assume-role-policy-document "$TRUST" >/dev/null
  aws iam attach-role-policy --role-name "$ROLE" \
    --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
  NEW_ROLE=1
fi
T="arn:aws:dynamodb:${REGION}:${ACCOUNT}:table"
POLICY=$(cat <<EOF
{"Version":"2012-10-17","Statement":[
 {"Sid":"ReadData","Effect":"Allow","Action":["dynamodb:GetItem","dynamodb:Query","dynamodb:Scan","dynamodb:BatchGetItem"],
  "Resource":["$T/tazerota-lots","$T/tazerota-dealers","$T/tazerota-sales","$T/tazerota-approvals","$T/tazerota-orders"]},
 {"Sid":"WriteWorkflow","Effect":"Allow","Action":["dynamodb:PutItem","dynamodb:UpdateItem","dynamodb:DeleteItem","dynamodb:BatchWriteItem"],
  "Resource":["$T/tazerota-approvals","$T/tazerota-orders"]},
 {"Sid":"InvokeAgent","Effect":"Allow","Action":["bedrock-agentcore:InvokeAgentRuntime"],
  "Resource":["$RUNTIME_ARN","$RUNTIME_ARN/*"]}]}
EOF
)
aws iam put-role-policy --role-name "$ROLE" --policy-name tazerota-panel-access --policy-document "$POLICY"
ROLE_ARN="arn:aws:iam::${ACCOUNT}:role/${ROLE}"
[[ -n "${NEW_ROLE:-}" ]] && { echo "waiting for new IAM role to propagate"; sleep 12; }

ENV_JSON=$(python3 -c 'import json,sys; print(json.dumps({"Variables": dict(zip(sys.argv[1::2], sys.argv[2::2]))}))' \
  AWS_LAMBDA_EXEC_WRAPPER /opt/bootstrap AWS_LWA_INVOKE_MODE response_stream AWS_LWA_PORT 8080 \
  AWS_LWA_READINESS_CHECK_PATH /healthz UI_PORT 8080 CHAT_MODE runtime AGENT_RUNTIME_ARN "$RUNTIME_ARN" \
  PANEL_USER "$PANEL_USER" PANEL_PASSWORD "$PANEL_PASSWORD")

# ---- function
if aws lambda get-function --function-name "$FN" --region "$REGION" >/dev/null 2>&1; then
  aws lambda update-function-code --function-name "$FN" --zip-file "fileb://$BUILD/panel.zip" --region "$REGION" >/dev/null
  aws lambda wait function-updated --function-name "$FN" --region "$REGION"
  aws lambda update-function-configuration --function-name "$FN" --environment "$ENV_JSON" --layers "$LAYER" \
    --region "$REGION" >/dev/null
else
  for i in 1 2 3 4 5; do  # retry while the new role propagates
    aws lambda create-function --function-name "$FN" --runtime python3.12 --architectures arm64 \
      --handler run.sh --role "$ROLE_ARN" --zip-file "fileb://$BUILD/panel.zip" --layers "$LAYER" \
      --memory-size 1024 --timeout 300 --environment "$ENV_JSON" --region "$REGION" >/dev/null && break
    echo "create-function retry $i"; sleep 8
  done
fi
aws lambda wait function-updated --function-name "$FN" --region "$REGION"

# ---- public URL with response streaming (the app itself enforces Basic Auth)
if ! aws lambda get-function-url-config --function-name "$FN" --region "$REGION" >/dev/null 2>&1; then
  aws lambda create-function-url-config --function-name "$FN" --auth-type NONE --invoke-mode RESPONSE_STREAM \
    --region "$REGION" >/dev/null
  aws lambda add-permission --function-name "$FN" --statement-id public-url --action lambda:InvokeFunctionUrl \
    --principal "*" --function-url-auth-type NONE --region "$REGION" >/dev/null
  aws lambda add-permission --function-name "$FN" --statement-id public-url-invoke --action lambda:InvokeFunction \
    --principal "*" --invoked-via-function-url --region "$REGION" >/dev/null 2>&1 || true
fi
URL=$(aws lambda get-function-url-config --function-name "$FN" --region "$REGION" --query FunctionUrl --output text)
echo "PANEL_URL=$URL"
echo "credentials in $CREDS"
