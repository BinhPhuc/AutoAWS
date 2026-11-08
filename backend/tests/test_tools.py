"""AWS read tools against moto. Each test builds the minimal resources it needs."""

from app.aws.registry import ToolContext, all_aws_actions, get_tool, list_tools, run_tool


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


def test_unknown_tool_and_no_stubs_left(aws):
    assert run_tool(aws, "nope", {}).status == "error"
    assert not [t.name for t in list_tools() if t.stub]
    assert get_tool("cloudtrail_lookup_events").aws_actions == ["cloudtrail:LookupEvents"]


def test_tools_endpoint(client):
    data = client.get("/api/tools").json()["data"]
    names = [t["name"] for t in data]
    assert names[0] == "describe_instance_status"  # compute group first, sorted by name
    first = data[0]
    assert set(first) == {"name", "group", "label", "description", "input_schema", "aws_actions"}


# ---- coverage for the remaining tools ----------------------------------------


def test_route_tables_mixed_explicit_and_implicit_subnets(aws):
    """Each subnet gets its effective table, even when only some are explicitly associated."""
    ec2, vpc, public_subnet = _vpc_with_subnet(aws, public=True)
    implicit_subnet = ec2.create_subnet(VpcId=vpc, CidrBlock="10.0.2.0/24")["Subnet"]["SubnetId"]

    res = run_tool(aws, "describe_route_tables", {"subnet_ids": [public_subnet, implicit_subnet]})
    assert res.status == "ok", res.error
    tables = res.output["route_tables"]
    explicit = next(t for t in tables if public_subnet in t["subnet_ids"])
    main = next(t for t in tables if t["main"])
    assert any(r["target"].startswith("igw-") for r in explicit["routes"])
    assert main["implicit_for_subnets"] == [implicit_subnet]
    assert not any(r["destination"] == "0.0.0.0/0" for r in main["routes"])


def test_describe_instance_status(aws):
    ec2, _, subnet = _vpc_with_subnet(aws, public=False)
    inst = ec2.run_instances(ImageId="ami-12345678", MinCount=1, MaxCount=1, SubnetId=subnet)[
        "Instances"
    ][0]["InstanceId"]
    res = run_tool(aws, "describe_instance_status", {"instance_ids": [inst]})
    assert res.status == "ok"
    [s] = res.output["statuses"]
    assert s["instance_id"] == inst
    assert s["instance_state"] == "running"
    assert s["system_status"] == "ok" and s["instance_status"] == "ok"


def test_ssm_describe_instance_information():
    # moto does not implement DescribeInstanceInformation: stub the SSM client instead.
    from types import SimpleNamespace

    import boto3
    from botocore.stub import Stubber

    ssm = boto3.client(
        "ssm", region_name="ap-southeast-1", aws_access_key_id="x", aws_secret_access_key="x"
    )
    stub = Stubber(ssm)
    stub.add_response(
        "describe_instance_information",
        {
            "InstanceInformationList": [
                {
                    "InstanceId": "i-0abc",
                    "PingStatus": "Online",
                    "AgentVersion": "3.3.0",
                    "PlatformName": "Amazon Linux",
                    "PlatformVersion": "2023",
                }
            ]
        },
        {"Filters": [{"Key": "InstanceIds", "Values": ["i-0abc"]}]},
    )
    with stub:
        res = run_tool(
            SimpleNamespace(client=lambda *_a, **_k: ssm),
            "ssm_describe_instance_information",
            {"instance_ids": ["i-0abc"]},
        )
    assert res.status == "ok", res.error
    [info] = res.output["managed_instances"]
    assert info == {
        "instance_id": "i-0abc",
        "ping_status": "Online",
        "agent_version": "3.3.0",
        "platform": "Amazon Linux 2023",
        "last_ping": None,
    }


def test_describe_network_acls(aws):
    ec2, vpc, subnet = _vpc_with_subnet(aws, public=False)
    acl = ec2.create_network_acl(VpcId=vpc)["NetworkAcl"]["NetworkAclId"]
    ec2.create_network_acl_entry(
        NetworkAclId=acl,
        RuleNumber=90,
        Protocol="6",
        RuleAction="deny",
        Egress=False,
        CidrBlock="0.0.0.0/0",
        PortRange={"From": 22, "To": 22},
    )
    res = run_tool(aws, "describe_network_acls", {"vpc_id": vpc})
    assert res.status == "ok"
    custom = next(a for a in res.output["network_acls"] if a["acl_id"] == acl)
    assert {
        "rule_number": 90,
        "direction": "ingress",
        "action": "deny",
        "protocol": "tcp",
        "ports": "22-22",
        "cidr": "0.0.0.0/0",
    } in custom["entries"]
    default = next(a for a in res.output["network_acls"] if a["is_default"])
    assert subnet in default["subnet_ids"]


def test_describe_subnets(aws):
    ec2, vpc, subnet = _vpc_with_subnet(aws, public=False)
    ec2.create_tags(Resources=[subnet], Tags=[{"Key": "Name", "Value": "web-subnet"}])
    res = run_tool(aws, "describe_subnets", {"vpc_id": vpc})
    [s] = res.output["subnets"]
    assert s["subnet_id"] == subnet
    assert s["name"] == "web-subnet"
    assert s["cidr"] == "10.0.1.0/24"
    assert s["map_public_ip_on_launch"] is False


def test_describe_internet_gateways(aws):
    ec2, vpc, _ = _vpc_with_subnet(aws, public=True)
    res = run_tool(aws, "describe_internet_gateways", {"vpc_id": vpc})
    [igw] = res.output["internet_gateways"]
    assert igw["igw_id"].startswith("igw-")
    assert igw["attached_vpcs"] == [{"vpc_id": vpc, "state": "available"}]


def test_get_caller_identity(aws):
    res = run_tool(aws, "get_caller_identity", {})
    assert res.status == "ok"
    assert res.output["account_id"] == "123456789012"
    assert res.output["arn"].startswith("arn:aws:")


def test_route53_zone_match_needs_a_dot_boundary(aws):
    r53 = aws.client("route53")
    r53.create_hosted_zone(Name="example.com.", CallerReference="z1")
    res = run_tool(aws, "route53_list_records", {"domain": "notexample.com"})
    assert res.status == "ok"
    assert res.output["zones"] == []
    assert res.output["records"] == []
    res = run_tool(aws, "route53_list_records", {"domain": "example.com"})
    assert res.output["zones"] == ["example.com"]


class _FakeAnswer:
    """Minimal stand-in for dns.resolver.Answer."""

    def __init__(self, values, ttl=60, cname=None):
        import dns.name

        self._values = values
        self.canonical_name = dns.name.from_text(cname or "app.example.com")
        self.rrset = type("RRset", (), {"ttl": ttl})()

    def __iter__(self):
        return iter(type("Rdata", (), {"to_text": lambda _s, v=v: v})() for v in self._values)


def _patch_resolve(monkeypatch, behaviour):
    import dns.resolver

    calls = {}

    def fake_resolve(self, hostname, rtype):
        calls["nameservers"] = list(self.nameservers)
        calls["query"] = (hostname, rtype)
        if isinstance(behaviour, Exception):
            raise behaviour
        return behaviour

    monkeypatch.setattr(dns.resolver.Resolver, "resolve", fake_resolve)
    return calls


def _asked(*names: str) -> ToolContext:
    """Conversation in which the user mentioned these names (DNS guard)."""
    return ToolContext(user_text="Tôi đã trỏ " + ", ".join(names))


def test_resolve_dns_public_answers(monkeypatch):
    calls = _patch_resolve(monkeypatch, _FakeAnswer(["13.212.1.1"]))
    res = run_tool(
        None, "resolve_dns_public", {"hostname": "app.example.com."}, _asked("app.example.com")
    )
    assert res.status == "ok"
    assert res.output == {
        "hostname": "app.example.com",
        "type": "A",
        "rcode": "NOERROR",
        "answers": ["13.212.1.1"],
        "canonical_name": None,
        "ttl": 60,
    }
    assert calls["nameservers"] == ["8.8.8.8", "1.1.1.1"]
    assert calls["query"] == ("app.example.com", "A")


def test_resolve_dns_public_nxdomain_is_a_finding_not_an_error(monkeypatch):
    import dns.resolver

    _patch_resolve(monkeypatch, dns.resolver.NXDOMAIN())
    res = run_tool(
        None,
        "resolve_dns_public",
        {"hostname": "missing.example.com"},
        _asked("missing.example.com"),
    )
    assert res.status == "ok"
    assert "error" not in res.output
    assert res.output["rcode"] == "NXDOMAIN" and res.output["answers"] == []

    _patch_resolve(monkeypatch, dns.resolver.NoAnswer())
    res = run_tool(
        None,
        "resolve_dns_public",
        {"hostname": "app.example.com", "record_type": "AAAA"},
        _asked("app.example.com"),
    )
    assert res.status == "ok"
    assert res.output["rcode"] == "NODATA"


def test_resolve_dns_public_resolver_failure_is_an_error(monkeypatch):
    import dns.exception

    _patch_resolve(monkeypatch, dns.exception.Timeout())
    res = run_tool(
        None, "resolve_dns_public", {"hostname": "app.example.com"}, _asked("app.example.com")
    )
    assert res.status == "error"
    assert res.output["error"].startswith("DNS error")
