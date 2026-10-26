"""Seed LocalStack with the incident scenarios AutoAWS should diagnose (dev/test only).

This script CREATES resources, so it refuses to run against anything but LocalStack.
The AutoAWS app itself stays read-only (AGENTS.md hard constraint #1).

    backend/.venv/bin/python infra/localstack/seed.py            # http://localhost:4566
    AWS_ENDPOINT_URL=http://localstack:4566 .../python seed.py   # other LocalStack host

Scenarios (docs/SYSTEM_OVERVIEW.md §4):
  KB1  "web-server" cannot be reached on SSH although its security group allows 22: the
       subnet was re-associated to a route table without a 0.0.0.0/0 route to the IGW.
  KB2  app.autoaws-demo.com does not reach "app-server" (Docker on 8080): the Route 53 A
       record still points to an old IP, and the security group does not allow 8080.
  KB3  needs ELBv2 + CloudWatch Logs/CloudTrail; ELBv2 is not in LocalStack Community, so
       it is skipped (covered by moto unit tests).

Re-running is safe: a scenario whose VPC already exists is skipped.
"""

import json
import os
import sys
import urllib.request
from urllib.parse import urlparse

import boto3
from botocore.exceptions import ClientError

ENDPOINT = os.environ.get("AWS_ENDPOINT_URL", "http://localhost:4566")
REGION = os.environ.get("AWS_DEFAULT_REGION", "ap-southeast-1")
# LocalStack maps this access key to account 000000000000; use the same key in the app.
ACCESS_KEY = os.environ.get("LOCALSTACK_ACCESS_KEY_ID", "AKIAIOSFODNN7EXAMPLE")
SECRET_KEY = os.environ.get("LOCALSTACK_SECRET_ACCESS_KEY", "localstack-secret-key")
DOMAIN = "autoaws-demo.com"
STALE_IP = "13.212.10.20"
TAG = "autoaws:scenario"


def _require_localstack() -> None:
    host = urlparse(ENDPOINT).hostname or ""
    if host not in {"localhost", "127.0.0.1", "localstack", "host.docker.internal"}:
        sys.exit(f"Refusing to seed {ENDPOINT}: this script only targets a local LocalStack.")
    try:
        with urllib.request.urlopen(f"{ENDPOINT}/_localstack/health", timeout=5) as resp:
            health = json.load(resp)
    except OSError as e:
        sys.exit(f"LocalStack is not reachable at {ENDPOINT}: {e}")
    print(f"LocalStack {health.get('version')} ({health.get('edition')}) at {ENDPOINT}")


def _client(service: str):
    return boto3.client(
        service,
        endpoint_url=ENDPOINT,
        region_name=REGION,
        aws_access_key_id=ACCESS_KEY,
        aws_secret_access_key=SECRET_KEY,
    )


def _tags(name: str, scenario: str, resource_type: str) -> list[dict]:
    return [
        {
            "ResourceType": resource_type,
            "Tags": [{"Key": "Name", "Value": name}, {"Key": TAG, "Value": scenario}],
        }
    ]


def _existing_vpc(ec2, scenario: str) -> str | None:
    vpcs = ec2.describe_vpcs(Filters=[{"Name": f"tag:{TAG}", "Values": [scenario]}])["Vpcs"]
    return vpcs[0]["VpcId"] if vpcs else None


def _ami(ec2) -> str:
    images = ec2.describe_images(Owners=["amazon"])["Images"]
    linux = [i for i in images if "amzn" in (i.get("Name") or "").lower()]
    return (linux or images)[0]["ImageId"]


def _public_vpc(ec2, scenario: str, cidr: str, subnet_cidr: str) -> dict:
    """VPC + IGW + public route table + subnet associated with it."""
    vpc = ec2.create_vpc(
        CidrBlock=cidr, TagSpecifications=_tags(f"autoaws-{scenario}-vpc", scenario, "vpc")
    )["Vpc"]["VpcId"]
    igw = ec2.create_internet_gateway(
        TagSpecifications=_tags(f"autoaws-{scenario}-igw", scenario, "internet-gateway")
    )["InternetGateway"]["InternetGatewayId"]
    ec2.attach_internet_gateway(InternetGatewayId=igw, VpcId=vpc)
    rt_public = ec2.create_route_table(
        VpcId=vpc,
        TagSpecifications=_tags(f"autoaws-{scenario}-rt-public", scenario, "route-table"),
    )["RouteTable"]["RouteTableId"]
    ec2.create_route(RouteTableId=rt_public, DestinationCidrBlock="0.0.0.0/0", GatewayId=igw)
    subnet = ec2.create_subnet(
        VpcId=vpc,
        CidrBlock=subnet_cidr,
        AvailabilityZone=f"{REGION}a",
        TagSpecifications=_tags(f"autoaws-{scenario}-subnet", scenario, "subnet"),
    )["Subnet"]["SubnetId"]
    ec2.modify_subnet_attribute(SubnetId=subnet, MapPublicIpOnLaunch={"Value": True})
    assoc = ec2.associate_route_table(RouteTableId=rt_public, SubnetId=subnet)["AssociationId"]
    return {"vpc": vpc, "igw": igw, "rt_public": rt_public, "subnet": subnet, "assoc": assoc}


def _instance(ec2, scenario: str, name: str, subnet: str, sg: str) -> dict:
    inst = ec2.run_instances(
        ImageId=_ami(ec2),
        InstanceType="t3.micro",
        MinCount=1,
        MaxCount=1,
        SubnetId=subnet,
        SecurityGroupIds=[sg],
        TagSpecifications=_tags(name, scenario, "instance"),
    )["Instances"][0]
    desc = ec2.describe_instances(InstanceIds=[inst["InstanceId"]])["Reservations"][0]
    return desc["Instances"][0]


def seed_kb1(ec2) -> dict:
    if vpc := _existing_vpc(ec2, "kb1"):
        return {"skipped": f"exists ({vpc})"}
    net = _public_vpc(ec2, "kb1", "10.10.0.0/16", "10.10.1.0/24")
    sg = ec2.create_security_group(
        GroupName="autoaws-kb1-web-sg",
        Description="web-server: SSH and HTTP from anywhere",
        VpcId=net["vpc"],
        TagSpecifications=_tags("autoaws-kb1-web-sg", "kb1", "security-group"),
    )["GroupId"]
    ec2.authorize_security_group_ingress(
        GroupId=sg,
        IpPermissions=[
            {
                "IpProtocol": "tcp",
                "FromPort": p,
                "ToPort": p,
                "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
            }
            for p in (22, 80)
        ],
    )
    inst = _instance(ec2, "kb1", "web-server", net["subnet"], sg)
    # The incident: someone moved the subnet to a route table without an Internet route.
    rt_private = ec2.create_route_table(
        VpcId=net["vpc"], TagSpecifications=_tags("autoaws-kb1-rt-private", "kb1", "route-table")
    )["RouteTable"]["RouteTableId"]
    ec2.replace_route_table_association(AssociationId=net["assoc"], RouteTableId=rt_private)
    return {
        "instance": inst["InstanceId"],
        "public_ip": inst.get("PublicIpAddress"),
        "subnet": net["subnet"],
        "security_group": sg,
        "route_table_now": rt_private,
        "route_table_before": net["rt_public"],
        "ask": "Tôi không SSH được vào instance web-server, Security Group đã mở port 22 rồi.",
    }


def seed_kb2(ec2, r53) -> dict:
    if vpc := _existing_vpc(ec2, "kb2"):
        return {"skipped": f"exists ({vpc})"}
    net = _public_vpc(ec2, "kb2", "10.20.0.0/16", "10.20.1.0/24")
    sg = ec2.create_security_group(
        GroupName="autoaws-kb2-app-sg",
        Description="app-server: SSH, HTTP, HTTPS (no 8080)",
        VpcId=net["vpc"],
        TagSpecifications=_tags("autoaws-kb2-app-sg", "kb2", "security-group"),
    )["GroupId"]
    ec2.authorize_security_group_ingress(
        GroupId=sg,
        IpPermissions=[
            {
                "IpProtocol": "tcp",
                "FromPort": p,
                "ToPort": p,
                "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
            }
            for p in (22, 80, 443)
        ],
    )
    inst = _instance(ec2, "kb2", "app-server", net["subnet"], sg)
    zone = r53.create_hosted_zone(Name=f"{DOMAIN}.", CallerReference="autoaws-kb2")["HostedZone"]
    # The incident: the A record still holds the IP the instance had before a stop/start.
    r53.change_resource_record_sets(
        HostedZoneId=zone["Id"],
        ChangeBatch={
            "Changes": [
                {
                    "Action": "UPSERT",
                    "ResourceRecordSet": {
                        "Name": f"app.{DOMAIN}.",
                        "Type": "A",
                        "TTL": 300,
                        "ResourceRecords": [{"Value": STALE_IP}],
                    },
                }
            ]
        },
    )
    return {
        "instance": inst["InstanceId"],
        "public_ip": inst.get("PublicIpAddress"),
        "security_group": sg,
        "hosted_zone": zone["Id"],
        "record": f"app.{DOMAIN} A {STALE_IP} (stale)",
        "ask": f"Tôi chạy ứng dụng Docker ở port 8080, đã trỏ app.{DOMAIN} về EC2 "
        "nhưng không vào được.",
    }


def main() -> None:
    _require_localstack()
    ec2, r53 = _client("ec2"), _client("route53")
    try:
        result = {"kb1": seed_kb1(ec2), "kb2": seed_kb2(ec2, r53)}
    except ClientError as e:
        sys.exit(f"Seeding failed: {e}")
    result["kb3"] = {"skipped": "ELBv2 is not available in LocalStack Community"}
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print(
        "\nConnect AutoAWS with an Access Key connection: "
        f"access key {ACCESS_KEY}, any secret (>=16 chars), region {REGION}."
    )


if __name__ == "__main__":
    main()
