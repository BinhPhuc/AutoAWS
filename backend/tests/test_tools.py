"""AWS read tools against moto. Each test builds the minimal resources it needs."""

from app.aws.registry import all_aws_actions, get_tool, list_tools, run_tool


def _vpc_with_subnet(aws, public: bool):
    ec2 = aws.client("ec2")
    vpc = ec2.create_vpc(CidrBlock="10.0.0.0/16")["Vpc"]["VpcId"]
    subnet = ec2.create_subnet(VpcId=vpc, CidrBlock="10.0.1.0/24")["Subnet"]["SubnetId"]
    if public:
        igw = ec2.create_internet_gateway()["InternetGateway"]["InternetGatewayId"]
        ec2.attach_internet_gateway(InternetGatewayId=igw, VpcId=vpc)
        rtb = ec2.create_route_table(VpcId=vpc)["RouteTable"]["RouteTableId"]
        ec2.create_route(RouteTableId=rtb, DestinationCidrBlock="0.0.0.0/0", GatewayId=igw)
        ec2.associate_route_table(RouteTableId=rtb, SubnetId=subnet)
    return ec2, vpc, subnet


def test_registry_is_read_only_and_complete():
    names = {t.name for t in list_tools()}
    assert {
        "get_caller_identity",
        "describe_instances",
        "describe_security_groups",
        "describe_route_tables",
        "route53_list_records",
        "resolve_dns_public",
        "elbv2_describe_target_health",
        "cloudtrail_lookup_events",
    } <= names
    for action in all_aws_actions():
        verb = action.split(":")[1]
        assert verb.startswith(("Describe", "List", "Get", "Lookup", "StartQuery")), action


def test_describe_instances_and_security_groups(aws):
    ec2, vpc, subnet = _vpc_with_subnet(aws, public=True)
    sg = ec2.create_security_group(GroupName="web", Description="web", VpcId=vpc)["GroupId"]
    ec2.authorize_security_group_ingress(
        GroupId=sg,
        IpPermissions=[
            {
                "IpProtocol": "tcp",
                "FromPort": 22,
                "ToPort": 22,
                "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
            }
        ],
    )
    inst = ec2.run_instances(
        ImageId="ami-12345678",
        MinCount=1,
        MaxCount=1,
        SubnetId=subnet,
        SecurityGroupIds=[sg],
        TagSpecifications=[
            {"ResourceType": "instance", "Tags": [{"Key": "Name", "Value": "web-server"}]}
        ],
    )["Instances"][0]["InstanceId"]

    res = run_tool(aws, "describe_instances", {"name_tag": "web"})
    assert res.status == "ok"
    [i] = res.output["instances"]
    assert i["instance_id"] == inst
    assert i["name"] == "web-server"
    assert i["state"] == "running"
    assert i["security_group_ids"] == [sg]

    res = run_tool(aws, "describe_security_groups", {"group_ids": [sg]})
    [g] = res.output["security_groups"]
    assert g["inbound"] == [{"ports": "22/tcp", "sources": ["0.0.0.0/0"]}]


def test_route_tables_public_vs_private(aws):
    ec2, vpc, subnet = _vpc_with_subnet(aws, public=True)
    res = run_tool(aws, "describe_route_tables", {"subnet_ids": [subnet]})
    [rt] = res.output["route_tables"]
    assert any(
        r["destination"] == "0.0.0.0/0" and r["target"].startswith("igw-") for r in rt["routes"]
    )

    ec2, vpc, private_subnet = _vpc_with_subnet(aws, public=False)
    res = run_tool(aws, "describe_route_tables", {"subnet_ids": [private_subnet]})
    [rt] = res.output["route_tables"]  # falls back to the VPC main table
    assert rt["main"] is True
    assert rt["implicit_for_subnets"] == [private_subnet]
    assert not any(r["destination"] == "0.0.0.0/0" for r in rt["routes"])


def test_target_health_and_health_check_path(aws):
    ec2, vpc, subnet = _vpc_with_subnet(aws, public=True)
    subnet2 = ec2.create_subnet(
        VpcId=vpc, CidrBlock="10.0.2.0/24", AvailabilityZone="ap-southeast-1b"
    )["Subnet"]["SubnetId"]
    elb = aws.client("elbv2")
    lb = elb.create_load_balancer(Name="web-alb", Subnets=[subnet, subnet2])["LoadBalancers"][0]
    tg = elb.create_target_group(
        Name="web-tg", Protocol="HTTP", Port=80, VpcId=vpc, HealthCheckPath="/health"
    )["TargetGroups"][0]
    elb.create_listener(
        LoadBalancerArn=lb["LoadBalancerArn"],
        Protocol="HTTP",
        Port=80,
        DefaultActions=[{"Type": "forward", "TargetGroupArn": tg["TargetGroupArn"]}],
    )

    res = run_tool(aws, "elbv2_describe_load_balancers", {})
    [out] = res.output["load_balancers"]
    assert out["name"] == "web-alb"
    assert out["listeners"][0]["port"] == 80

    res = run_tool(
        aws, "elbv2_describe_target_health", {"load_balancer_arn": lb["LoadBalancerArn"]}
    )
    [g] = res.output["target_groups"]
    assert g["health_check"]["path"] == "/health"
    assert g["healthy_count"] == 0


def test_route53_records(aws):
    r53 = aws.client("route53")
    zone = r53.create_hosted_zone(Name="example.com.", CallerReference="x")["HostedZone"]["Id"]
    r53.change_resource_record_sets(
        HostedZoneId=zone,
        ChangeBatch={
            "Changes": [
                {
                    "Action": "CREATE",
                    "ResourceRecordSet": {
                        "Name": "app.example.com.",
                        "Type": "A",
                        "TTL": 60,
                        "ResourceRecords": [{"Value": "13.212.1.1"}],
                    },
                }
            ]
        },
    )
    res = run_tool(aws, "route53_list_records", {"domain": "app.example.com"})
    assert res.output["zones"] == ["example.com"]
    [rec] = res.output["records"]
    assert rec["values"] == ["13.212.1.1"]


def test_unknown_tool_and_stub(aws):
    assert run_tool(aws, "nope", {}).status == "error"
    res = run_tool(aws, "cloudtrail_lookup_events", {})
    assert res.status == "error" and "NOT_IMPLEMENTED" in res.error
    assert get_tool("cloudtrail_lookup_events").stub is True


def test_tools_endpoint(client):
    data = client.get("/api/tools").json()["data"]
    names = [t["name"] for t in data]
    assert names[0] == "describe_instance_status"  # compute group first, sorted by name
    first = data[0]
    assert set(first) == {"name", "group", "label", "description", "input_schema", "aws_actions"}
