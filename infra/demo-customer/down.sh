#!/usr/bin/env bash
# Delete the demo-customer network stack and wait until it is gone.
# Delete EC2/ALB stacks from tasks 13-15 first, otherwise the VPC cannot be removed.
set -euo pipefail

PROFILE="${AWS_PROFILE:-autoaws-customer}"
REGION="${AWS_REGION:-ap-southeast-1}"
STACK="autoaws-demo-network"

aws cloudformation delete-stack --stack-name "$STACK" --profile "$PROFILE" --region "$REGION"
echo "Waiting for $STACK to be deleted..."
aws cloudformation wait stack-delete-complete --stack-name "$STACK" --profile "$PROFILE" --region "$REGION"
echo "Deleted."
