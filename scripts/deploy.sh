#!/usr/bin/env bash
# Packages and deploys the Liviana stack. Same five steps as deploy.ps1, for
# CI and for anyone not on Windows.
#
#   CONTENT_BUCKET=kettenki-liviana-content ALERT_EMAIL=info@example.com \
#   ALLOWED_ORIGIN=https://example.com ./scripts/deploy.sh
set -euo pipefail

: "${CONTENT_BUCKET:?set CONTENT_BUCKET to a globally unique bucket name}"
: "${ALERT_EMAIL:?set ALERT_EMAIL to the address that receives budget alarms}"
: "${ALLOWED_ORIGIN:?set ALLOWED_ORIGIN to the site origin, e.g. https://example.com}"

STACK_NAME="${STACK_NAME:-liviana}"
PROJECT_NAME="${PROJECT_NAME:-liviana}"
REGION="${REGION:-eu-central-1}"
MODEL_ID="${MODEL_ID:-eu.anthropic.claude-haiku-4-5-20251001-v1:0}"
CONTENT_FILE="${CONTENT_FILE:-content/content.json}"
CONTENT_KEY="${CONTENT_KEY:-content.json}"
RATE_LIMIT_PER_MINUTE="${RATE_LIMIT_PER_MINUTE:-20}"
DAILY_INVOCATION_LIMIT="${DAILY_INVOCATION_LIMIT:-500}"
RESERVED_CONCURRENCY="${RESERVED_CONCURRENCY:-5}"
MONTHLY_BUDGET_USD="${MONTHLY_BUDGET_USD:-10}"

cd "$(dirname "$0")/.."

echo "==> Identity"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text --region "$REGION")
echo "    account $ACCOUNT_ID, region $REGION"

ARTIFACT_BUCKET="${PROJECT_NAME}-artifacts-${ACCOUNT_ID}-${REGION}"
echo "==> Artifact bucket $ARTIFACT_BUCKET"
if ! aws s3api head-bucket --bucket "$ARTIFACT_BUCKET" --region "$REGION" >/dev/null 2>&1; then
  echo "    creating"
  if [ "$REGION" = "us-east-1" ]; then
    aws s3api create-bucket --bucket "$ARTIFACT_BUCKET" --region "$REGION" >/dev/null
  else
    aws s3api create-bucket --bucket "$ARTIFACT_BUCKET" --region "$REGION" \
      --create-bucket-configuration "LocationConstraint=$REGION" >/dev/null
  fi
  aws s3api put-public-access-block --bucket "$ARTIFACT_BUCKET" --region "$REGION" \
    --public-access-block-configuration \
    "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true" >/dev/null
fi

echo "==> Packaging"
rm -rf build/stage build/liviana.zip
mkdir -p build/stage
cp -r src/liviana build/stage/liviana
find build/stage -name '__pycache__' -type d -prune -exec rm -rf {} +
(cd build/stage && zip -qr ../liviana.zip liviana)
HASH=$(python -c "import hashlib,sys;print(hashlib.sha256(open('build/liviana.zip','rb').read()).hexdigest()[:12])")
CODE_KEY="lambda/liviana-${HASH}.zip"
echo "    build/liviana.zip -> s3://$ARTIFACT_BUCKET/$CODE_KEY"
aws s3 cp build/liviana.zip "s3://$ARTIFACT_BUCKET/$CODE_KEY" --region "$REGION" >/dev/null

echo "==> Deploying stack $STACK_NAME"
aws cloudformation deploy \
  --template-file infra/template.yaml \
  --stack-name "$STACK_NAME" \
  --region "$REGION" \
  --capabilities CAPABILITY_IAM \
  --no-fail-on-empty-changeset \
  --parameter-overrides \
  "ProjectName=$PROJECT_NAME" \
  "ContentBucketName=$CONTENT_BUCKET" \
  "ContentKey=$CONTENT_KEY" \
  "AllowedOrigin=$ALLOWED_ORIGIN" \
  "ModelId=$MODEL_ID" \
  "LambdaCodeBucket=$ARTIFACT_BUCKET" \
  "LambdaCodeKey=$CODE_KEY" \
  "RateLimitPerMinute=$RATE_LIMIT_PER_MINUTE" \
  "DailyInvocationLimit=$DAILY_INVOCATION_LIMIT" \
  "ReservedConcurrency=$RESERVED_CONCURRENCY" \
  "MonthlyBudgetUsd=$MONTHLY_BUDGET_USD" \
  "AlertEmail=$ALERT_EMAIL"

echo "==> Uploading content document"
python -c "import json,sys;json.load(open(sys.argv[1],encoding='utf-8'))" "$CONTENT_FILE"
aws s3 cp "$CONTENT_FILE" "s3://$CONTENT_BUCKET/$CONTENT_KEY" \
  --content-type application/json --region "$REGION" >/dev/null

echo "==> Outputs"
aws cloudformation describe-stacks --stack-name "$STACK_NAME" --region "$REGION" \
  --query "Stacks[0].Outputs[].[OutputKey,OutputValue]" --output text

echo
echo "Done. On a first deploy, confirm the SNS subscription email and make sure"
echo "Bedrock model access is enabled for $MODEL_ID."
