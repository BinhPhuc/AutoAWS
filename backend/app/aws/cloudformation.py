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

# Never granted to the remediation role, even by mistake in the catalogue: IAM, stopping
# instances, and deleting the user's resources (rules / routes / entries are configuration
# and stay removable, with an undo).
REMEDIATION_DENIED = [
    "iam:*",
    "organizations:*",
    "account:*",
    "ec2:TerminateInstances",
    "ec2:StopInstances",
    "ec2:DeleteVpc",
    "ec2:DeleteSubnet",
    "ec2:DeleteSecurityGroup",
    "ec2:DeleteRouteTable",
    "ec2:DeleteNetworkAcl",
    "ec2:DeleteInternetGateway",
    "ec2:DeleteNatGateway",
    "elasticloadbalancing:DeleteLoadBalancer",
    "elasticloadbalancing:DeleteTargetGroup",
    "route53:DeleteHostedZone",
]
# Route 53 record changes the catalogue makes: UPSERT, and DELETE only to undo a record
# AutoAWS created; only these record types.
ROUTE53_CHANGE_ACTIONS = ["UPSERT", "DELETE"]
ROUTE53_RECORD_TYPES = ["A", "AAAA", "CNAME", "TXT"]


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


def _principal(role_arns: list[str]) -> str:
    """Trust exactly these platform roles; none set (dev) = the whole platform account."""
    arns = [a for a in role_arns if a]
    if not arns:
        return "              AWS: !Sub 'arn:aws:iam::${PlatformAccountId}:root'"
    roles = [a.split(":role/", 1)[1] for a in arns]  # keep PlatformAccountId the source
    return "              AWS:\n" + "\n".join(
        f"                - !Sub 'arn:aws:iam::${{PlatformAccountId}}:role/{r}'" for r in roles
    )


def _remediation_yaml(executor_role_arn: str = "") -> str:
    groups = remediation_actions()
    region_yaml = "\n".join(f"                  - {a}" for a in groups["region"])
    r53_yaml = "\n".join(f"                  - {a}" for a in groups["route53"])
    denied_yaml = "\n".join(f"                  - {a}" for a in REMEDIATION_DENIED)
    principal = _principal([executor_role_arn])
    r53_change_actions = "[" + ", ".join(f"'{a}'" for a in ROUTE53_CHANGE_ACTIONS) + "]"
    r53_record_types = "[" + ", ".join(f"'{t}'" for t in ROUTE53_RECORD_TYPES) + "]"
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
{principal}
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
              - Sid: AllowCatalogueRecordChangesOnly
                Effect: Allow
                Resource: 'arn:aws:route53:::hostedzone/*'
                Action:
{r53_yaml}
                Condition:
                  ForAllValues:StringEquals:
                    route53:ChangeResourceRecordSetsActions: {r53_change_actions}
                    route53:ChangeResourceRecordSetsRecordTypes: {r53_record_types}
              - Sid: DenyDangerous
                Effect: Deny
                Resource: '*'
                Action:
{denied_yaml}
"""


def render_template(
    platform_account_id: str,
    external_id: str,
    agent_role_arn: str = "",
    executor_role_arn: str = "",
) -> str:
    """Customer template. With the platform role ARNs (CDK deployment), the read-only role
    trusts only agent-worker (+ action-executor, which re-reads before writing) and the
    remediation role only action-executor (report §2.6.1)."""
    read_principal = _principal([agent_role_arn, executor_role_arn])
    allow = policy_actions()
    actions_yaml = "\n".join(f"                  - {a}" for a in allow)
    denies_yaml = "\n".join(f"                  - {a}" for a in DENIED_ACTIONS)
    remediation_yaml = _remediation_yaml(executor_role_arn)
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
{read_principal}
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
