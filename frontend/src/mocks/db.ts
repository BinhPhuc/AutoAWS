import type { Connection, Conversation, Job, Message, Proposal, ToolSpec } from '@/api/types'

let seq = 0
export const nextId = (prefix: string) => `${prefix}_${(++seq).toString(36).padStart(4, '0')}`
const now = () => new Date().toISOString()

export const db = {
  connections: [] as Connection[],
  conversations: [] as Conversation[],
  messages: new Map<string, Message[]>(),
  proposals: [] as Proposal[],
  jobs: [] as Job[],
}

export function seed() {
  const conn: Connection = {
    id: nextId('conn'),
    name: 'Lab account',
    type: 'access_key',
    region: 'ap-southeast-1',
    status: 'connected',
    account_id: '123456789012',
    role_arn: null,
    external_id: null,
    access_key_id_masked: 'AKIA****LAB1',
    remediation_role_arn: null,
    remediation_enabled: true,
    last_verified_at: now(),
    last_error: null,
    created_at: now(),
  }
  db.connections.push(conn)
}

export const tools: ToolSpec[] = [
  t(
    'get_caller_identity',
    'compute',
    'Caller identity',
    'Account and ARN of the current credentials',
    ['sts:GetCallerIdentity'],
  ),
  t(
    'describe_instances',
    'compute',
    'EC2 instances',
    'State, IPs, subnet and security groups of EC2 instances',
    ['ec2:DescribeInstances'],
  ),
  t(
    'describe_instance_status',
    'compute',
    'Instance status checks',
    'System and instance status checks',
    ['ec2:DescribeInstanceStatus'],
  ),
  t(
    'ssm_describe_instance_information',
    'compute',
    'SSM Agent status',
    'Whether SSM Agent is online on instances',
    ['ssm:DescribeInstanceInformation'],
  ),
  t(
    'describe_security_groups',
    'network',
    'Security groups',
    'Inbound/outbound rules of security groups',
    ['ec2:DescribeSecurityGroups'],
  ),
  t('describe_network_acls', 'network', 'Network ACLs', 'Subnet-level allow/deny rules', [
    'ec2:DescribeNetworkAcls',
  ]),
  t('describe_route_tables', 'network', 'Route tables', 'Routes and subnet associations', [
    'ec2:DescribeRouteTables',
  ]),
  t('describe_subnets', 'network', 'Subnets', 'Subnet CIDR, AZ and public IP mapping', [
    'ec2:DescribeSubnets',
  ]),
  t(
    'describe_internet_gateways',
    'network',
    'Internet gateways',
    'Internet gateways attached to VPCs',
    ['ec2:DescribeInternetGateways'],
  ),
  t('route53_list_records', 'dns', 'Route 53 records', 'DNS records in hosted zones', [
    'route53:ListHostedZones',
    'route53:ListResourceRecordSets',
  ]),
  t('resolve_dns_public', 'dns', 'Public DNS lookup', 'Resolve a hostname via public DNS', []),
  t('elbv2_describe_load_balancers', 'elb', 'Load balancers', 'Load balancers and listeners', [
    'elasticloadbalancing:DescribeLoadBalancers',
    'elasticloadbalancing:DescribeListeners',
  ]),
  t('elbv2_describe_target_health', 'elb', 'Target health', 'Health of targets in target groups', [
    'elasticloadbalancing:DescribeTargetGroups',
    'elasticloadbalancing:DescribeTargetHealth',
  ]),
  t('cloudwatch_get_metric_data', 'metrics', 'CloudWatch metrics', 'Metric time series', [
    'cloudwatch:GetMetricData',
  ]),
  t('logs_insights_query', 'logs', 'CloudWatch Logs query', 'Logs Insights query results', [
    'logs:StartQuery',
    'logs:GetQueryResults',
  ]),
  t('cloudtrail_lookup_events', 'cloudtrail', 'CloudTrail events', 'Recent change history', [
    'cloudtrail:LookupEvents',
  ]),
]

function t(
  name: string,
  group: ToolSpec['group'],
  label: string,
  description: string,
  aws_actions: string[],
): ToolSpec {
  return {
    name,
    group,
    label,
    description,
    input_schema: { type: 'object', properties: {} },
    aws_actions,
  }
}

export const toolByName = (name: string) => tools.find((x) => x.name === name)
