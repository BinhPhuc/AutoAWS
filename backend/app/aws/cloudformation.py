"""Render the CloudFormation template users deploy to grant AutoAWS read-only access.

The Allow statement is generated from the tool registry so the policy always matches
what the code can call. The explicit Deny protects business data even if a future tool
accidentally asks for it.
"""

import json

from app.aws.registry import all_aws_actions

STACK_NAME = "AutoAWSReadOnlyRole"
ROLE_NAME = "AutoAWSReadOnly"

DENIED_ACTIONS = [
    "s3:GetObject*",
    "secretsmanager:GetSecretValue",
    "ssm:GetParameter*",
    "kms:Decrypt",
    "dynamodb:GetItem",
    "dynamodb:Query",
    "dynamodb:Scan",
    "rds-data:*",
]


def render_template(platform_account_id: str, external_id: str) -> str:
    allow = [a for a in all_aws_actions() if a]
    actions_yaml = "\n".join(f"                  - {a}" for a in allow)
    denies_yaml = "\n".join(f"                  - {a}" for a in DENIED_ACTIONS)
    return f"""AWSTemplateFormatVersion: '2010-09-09'
Description: Read-only IAM role that lets AutoAWS diagnose incidents in this account.

Parameters:
  PlatformAccountId:
    Type: String
    Default: '{platform_account_id}'
    Description: AWS account id of the AutoAWS platform (the account that assumes this role)
  ExternalId:
    Type: String
    Default: '{external_id}'
    Description: Unique external id shown in the AutoAWS app for this connection

Resources:
  AutoAWSReadOnlyRole:
    Type: AWS::IAM::Role
    Properties:
      RoleName: {ROLE_NAME}
      Description: Read-only access for AutoAWS incident diagnosis
      MaxSessionDuration: 3600
      AssumeRolePolicyDocument:
        Version: '2012-10-17'
        Statement:
          - Effect: Allow
            Principal:
              AWS: !Sub 'arn:aws:iam::${{PlatformAccountId}}:root'
            Action: sts:AssumeRole
            Condition:
              StringEquals:
                sts:ExternalId: !Ref ExternalId
      Policies:
        - PolicyName: AutoAWSReadOnly
          PolicyDocument:
            Version: '2012-10-17'
            Statement:
              - Sid: AllowReadOnlyDiagnostics
                Effect: Allow
                Resource: '*'
                Action:
{actions_yaml}
              - Sid: DenyBusinessData
                Effect: Deny
                Resource: '*'
                Action:
{denies_yaml}

Outputs:
  RoleArn:
    Description: Paste this ARN into AutoAWS
    Value: !GetAtt AutoAWSReadOnlyRole.Arn
"""


def render_policy_json() -> str:
    """Same permissions as JSON, handy for users who prefer creating the role by hand."""
    return json.dumps(
        {
            "Version": "2012-10-17",
            "Statement": [
                {"Effect": "Allow", "Action": all_aws_actions(), "Resource": "*"},
                {"Effect": "Deny", "Action": DENIED_ACTIONS, "Resource": "*"},
            ],
        },
        indent=2,
    )
