"""Render the CloudFormation template users deploy to grant AutoAWS read-only access.

The Allow statement is generated from the tool registry (plus the calls made by
``verify_session``) so the policy always matches what the code can call. The explicit
Deny protects business data even if a future tool accidentally asks for it.
"""

import json

from app.aws.credentials import VERIFY_AWS_ACTIONS
from app.aws.registry import DENIED_ACTIONS, all_aws_actions
from app.aws.remediation.catalog import EXTRA_READ_ACTIONS, all_write_actions

STACK_NAME = "AutoAWSReadOnlyRole"
ROLE_NAME = "AutoAWSReadOnly"
REMEDIATION_ROLE_NAME = "AutoAWSRemediation"

# Never granted to the remediation role, even by mistake in the catalogue.
REMEDIATION_DENIED = [
    "iam:*",
    "organizations:*",
    "account:*",
    "ec2:TerminateInstances",
    "ec2:StopInstances",
]


def policy_actions() -> list[str]:
    """Every read AutoAWS makes on the user's account: tools, connection verify, and the
    re-checks / verification of the remediation flow."""
    return sorted(set(all_aws_actions()) | set(VERIFY_AWS_ACTIONS) | set(EXTRA_READ_ACTIONS))


def remediation_actions() -> dict[str, list[str]]:
    """Write actions of the catalogue, grouped by the IAM statement that grants them."""
    groups: dict[str, list[str]] = {"region": [], "route53": []}
    for action in all_write_actions():
        groups["route53" if action.startswith("route53:") else "region"].append(action)
    return groups


def _remediation_yaml() -> str:
    groups = remediation_actions()
    region_yaml = "\n".join(f"                  - {a}" for a in groups["region"])
    r53_yaml = "\n".join(f"                  - {a}" for a in groups["route53"])
    denied_yaml = "\n".join(f"                  - {a}" for a in REMEDIATION_DENIED)
    return f"""  AutoAWSRemediationRole:
    Type: AWS::IAM::Role
    Condition: RemediationEnabled
    Properties:
      RoleName: {REMEDIATION_ROLE_NAME}
      Description: Applies fixes approved one by one in AutoAWS (fixed catalogue of actions)
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
        - PolicyName: AutoAWSRemediation
          PolicyDocument:
            Version: '2012-10-17'
            Statement:
              - Sid: AllowCatalogueChangesInThisRegion
                Effect: Allow
                Resource: '*'
                Action:
{region_yaml}
                Condition:
                  StringEquals:
                    aws:RequestedRegion: !Ref AWS::Region
              - Sid: AllowUpsertOfARecordsOnly
                Effect: Allow
                Resource: 'arn:aws:route53:::hostedzone/*'
                Action:
{r53_yaml}
                Condition:
                  ForAllValues:StringEquals:
                    route53:ChangeResourceRecordSetsActions: ['UPSERT']
                    route53:ChangeResourceRecordSetsRecordTypes: ['A']
              - Sid: DenyDangerous
                Effect: Deny
                Resource: '*'
                Action:
{denied_yaml}
"""


def render_template(platform_account_id: str, external_id: str) -> str:
    allow = policy_actions()
    actions_yaml = "\n".join(f"                  - {a}" for a in allow)
    denies_yaml = "\n".join(f"                  - {a}" for a in DENIED_ACTIONS)
    remediation_yaml = _remediation_yaml()
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
  EnableRemediation:
    Type: String
    Default: 'false'
    AllowedValues: ['true', 'false']
    Description: >-
      'true' also creates the AutoAWSRemediation role, used only to apply fixes you approve
      one by one in AutoAWS (fixed list of actions, this Region only)

Conditions:
  RemediationEnabled: !Equals [!Ref EnableRemediation, 'true']

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

{remediation_yaml}
Outputs:
  RoleArn:
    Description: Paste this ARN into AutoAWS
    Value: !GetAtt AutoAWSReadOnlyRole.Arn
  RemediationRoleArn:
    Condition: RemediationEnabled
    Description: Paste this ARN into AutoAWS to allow approved fixes
    Value: !GetAtt AutoAWSRemediationRole.Arn
"""


def render_policy_json() -> str:
    """Same permissions as JSON, handy for users who prefer creating the role by hand."""
    return json.dumps(
        {
            "Version": "2012-10-17",
            "Statement": [
                {"Effect": "Allow", "Action": policy_actions(), "Resource": "*"},
                {"Effect": "Deny", "Action": DENIED_ACTIONS, "Resource": "*"},
            ],
        },
        indent=2,
    )
