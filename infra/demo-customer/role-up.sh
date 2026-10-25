#!/usr/bin/env bash
# Deploy the AutoAWSReadOnly role (task 12) into the customer account, then print its ARN.
# Usage: PLATFORM_ACCOUNT_ID=111122223333 EXTERNAL_ID=autoaws-xxxx ./role-up.sh
# readonly-role.yaml is generated from backend/app/aws/cloudformation.py — regenerate it
# when tools change instead of editing it by hand.
set -euo pipefail

: "${PLATFORM_ACCOUNT_ID:?set PLATFORM_ACCOUNT_ID (12-digit id of the platform account)}"
: "${EXTERNAL_ID:?set EXTERNAL_ID (e.g. autoaws-<random hex>)}"
PROFILE="${AWS_PROFILE:-autoaws-customer}"
REGION="${AWS_REGION:-ap-southeast-1}"
STACK="AutoAWSReadOnlyRole"
DIR="$(cd "$(dirname "$0")" && pwd)"

aws cloudformation deploy \
  --stack-name "$STACK" \
  --template-file "$DIR/readonly-role.yaml" \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides "PlatformAccountId=$PLATFORM_ACCOUNT_ID" "ExternalId=$EXTERNAL_ID" \
  --tags Project=autoaws-demo \
  --no-fail-on-empty-changeset \
  --profile "$PROFILE" --region "$REGION"

aws cloudformation describe-stacks \
  --stack-name "$STACK" \
  --query "Stacks[0].Outputs[?OutputKey=='RoleArn'].OutputValue" \
  --output text \
  --profile "$PROFILE" --region "$REGION"
