#!/usr/bin/env bash
# Create or update the demo-customer network stack, then print its outputs.
# Usage: ./up.sh            (defaults: profile autoaws-customer, region ap-southeast-1)
#        AWS_PROFILE=x AWS_REGION=y ./up.sh
set -euo pipefail

PROFILE="${AWS_PROFILE:-autoaws-customer}"
REGION="${AWS_REGION:-ap-southeast-1}"
STACK="autoaws-demo-network"
DIR="$(cd "$(dirname "$0")" && pwd)"

aws cloudformation deploy \
  --stack-name "$STACK" \
  --template-file "$DIR/network.yaml" \
  --tags Project=autoaws-demo \
  --no-fail-on-empty-changeset \
  --profile "$PROFILE" --region "$REGION"

aws cloudformation describe-stacks \
  --stack-name "$STACK" \
  --query "Stacks[0].Outputs[].[OutputKey,OutputValue]" \
  --output table \
  --profile "$PROFILE" --region "$REGION"
