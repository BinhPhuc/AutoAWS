"""Tools added for the full diagnosis: Elastic IPs, NAT, CloudWatch, Logs, CloudTrail,
the DNS guard and structured AccessDenied errors."""

import json
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import boto3
import pytest
from botocore.stub import Stubber

from app.agent.loop import MAX_RESULT_CHARS, _fit
from app.aws.registry import ToolContext, run_tool
from app.aws.tools._common import time_window


def _client(service: str):
    return boto3.client(
        service, region_name="ap-southeast-1", aws_access_key_id="x", aws_secret_access_key="x"
    )


def _session_for(client):
    return SimpleNamespace(client=lambda *_a, **_k: client)


def _subnet(aws):
    ec2 = aws.client("ec2")
    vpc = ec2.create_vpc(CidrBlock="10.0.0.0/16")["Vpc"]["VpcId"]
    subnet = ec2.create_subnet(VpcId=vpc, CidrBlock="10.0.1.0/24")["Subnet"]["SubnetId"]
    return ec2, vpc, subnet


# ---- network ---------------------------------------------------------------------


def test_describe_addresses(aws):
    ec2, _, subnet = _subnet(aws)
    inst = ec2.run_instances(ImageId="ami-12345678", MinCount=1, MaxCount=1, SubnetId=subnet)[
        "Instances"
    ][0]["InstanceId"]
    alloc = ec2.allocate_address(Domain="vpc")
    ec2.associate_address(AllocationId=alloc["AllocationId"], InstanceId=inst)
    ec2.allocate_address(Domain="vpc")  # a second, unattached EIP

    res = run_tool(aws, "describe_addresses", {"instance_ids": [inst]})
    assert res.status == "ok", res.error
    [eip] = res.output["elastic_ips"]
    assert eip["public_ip"] == alloc["PublicIp"]
    assert eip["instance_id"] == inst and eip["association_id"]
    assert len(run_tool(aws, "describe_addresses", {}).output["elastic_ips"]) == 2


def test_describe_nat_gateways(aws):
    ec2, vpc, subnet = _subnet(aws)
    alloc = ec2.allocate_address(Domain="vpc")["AllocationId"]
    nat = ec2.create_nat_gateway(SubnetId=subnet, AllocationId=alloc)["NatGateway"]["NatGatewayId"]
    res = run_tool(aws, "describe_nat_gateways", {"vpc_id": vpc})
    assert res.status == "ok", res.error
    [n] = res.output["nat_gateways"]
    assert n["nat_gateway_id"] == nat and n["subnet_id"] == subnet
    assert n["public_ips"]


# ---- CloudWatch --------------------------------------------------------------------


def test_metric_series_is_summarised(aws):
    cw = aws.client("cloudwatch")
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    values = [0, 0, 0, 2, 2, 2]  # UnHealthyHostCount rises 0 -> 2
    for i, v in enumerate(values):
        cw.put_metric_data(
            Namespace="AWS/ApplicationELB",
            MetricData=[
                {
                    "MetricName": "UnHealthyHostCount",
                    "Dimensions": [{"Name": "TargetGroup", "Value": "targetgroup/web/1"}],
                    "Timestamp": now - timedelta(minutes=5 * (len(values) - i)),
                    "Value": v,
                }
            ],
        )
    res = run_tool(
        aws,
        "cloudwatch_get_metric_data",
        {
            "namespace": "AWS/ApplicationELB",
            "metric_name": "UnHealthyHostCount",
            "dimensions": {"TargetGroup": "targetgroup/web/1"},
            "stat": "Maximum",
            "hours": 1,
        },
    )
    assert res.status == "ok", res.error
    out = res.output
    assert out["datapoints"] == 6 and out["min"] == 0 and out["max"] == 2
    assert out["latest"]["value"] == 2
    assert [p[1] for p in out["points"]] == values


def test_metric_without_data_lists_existing_dimensions(aws):
    cw = aws.client("cloudwatch")
    cw.put_metric_data(
        Namespace="AWS/EC2",
        MetricData=[
            {
                "MetricName": "CPUUtilization",
                "Dimensions": [{"Name": "InstanceId", "Value": "i-0real"}],
                "Value": 10,
            }
        ],
    )
    res = run_tool(
        aws,
        "cloudwatch_get_metric_data",
        {
            "namespace": "AWS/EC2",
            "metric_name": "CPUUtilization",
            "dimensions": {"InstanceId": "i-0typo"},
        },
    )
    assert res.status == "ok", res.error
    assert res.output["datapoints"] == 0
    assert {"InstanceId": "i-0real"} in res.output["available_dimensions"]


def test_long_window_raises_the_period():
    from app.aws.tools.metrics import MAX_POINTS

    cw = _client("cloudwatch")
    stub = Stubber(cw)
    stub.add_response(
        "get_metric_data",
        {
            "MetricDataResults": [
                {"Id": "m1", "Timestamps": [], "Values": [], "StatusCode": "Complete"}
            ]
        },
    )
    stub.add_response("list_metrics", {"Metrics": []})
    with stub:
        res = run_tool(
            _session_for(cw),
            "cloudwatch_get_metric_data",
            {
                "namespace": "AWS/EC2",
                "metric_name": "CPUUtilization",
                "hours": 336,
                "period_seconds": 60,
            },
        )
    assert res.status == "ok", res.error
    assert 336 * 3600 / res.output["period_seconds"] <= MAX_POINTS


def test_alarms_in_alarm_come_first(aws):
    cw = aws.client("cloudwatch")
    for name in ("cpu-high", "unhealthy-hosts"):
        cw.put_metric_alarm(
            AlarmName=name,
            Namespace="AWS/ApplicationELB",
            MetricName="UnHealthyHostCount",
            Statistic="Maximum",
            Period=60,
            EvaluationPeriods=1,
            Threshold=0,
            ComparisonOperator="GreaterThanThreshold",
        )
    cw.set_alarm_state(AlarmName="unhealthy-hosts", StateValue="ALARM", StateReason="2 > 0")
    res = run_tool(aws, "cloudwatch_describe_alarms", {})
    assert res.status == "ok", res.error
    first = res.output["alarms"][0]
    assert first["name"] == "unhealthy-hosts" and first["state"] == "ALARM"
    assert first["state_reason"] == "2 > 0" and first["threshold"] == 0
    only = run_tool(aws, "cloudwatch_describe_alarms", {"state": "ALARM"}).output["alarms"]
    assert [a["name"] for a in only] == ["unhealthy-hosts"]


# ---- CloudWatch Logs ---------------------------------------------------------------


def test_log_groups_and_insights_query(aws):
    logs = aws.client("logs")
    logs.create_log_group(logGroupName="/demo/app")
    logs.create_log_stream(logGroupName="/demo/app", logStreamName="web-1")
    now_ms = int(time.time() * 1000)
    logs.put_log_events(
        logGroupName="/demo/app",
        logStreamName="web-1",
        logEvents=[
            {"timestamp": now_ms - 2000, "message": "GET /health 200"},
            {"timestamp": now_ms - 1000, "message": "ERROR could not connect to db:5432"},
        ],
    )
    res = run_tool(aws, "logs_describe_log_groups", {"prefix": "/demo/"})
    assert res.status == "ok", res.error
    assert [g["name"] for g in res.output["log_groups"]] == ["/demo/app"]

    res = run_tool(
        aws,
        "logs_insights_query",
        {
            "log_group_names": ["/demo/app"],
            "query": "fields @timestamp, @message | sort @timestamp desc",
            "limit": 5,
        },
    )
    assert res.status == "ok", res.error
    out = res.output
    assert out["status"] == "Complete"
    assert out["query"].endswith("| limit 5")  # a limit is always enforced
    assert any("could not connect" in r["@message"] for r in out["rows"])
    assert all("@ptr" not in r for r in out["rows"])
    assert all(r["@timestamp"].endswith("Z") for r in out["rows"])  # epoch ms -> ISO


def test_default_query_looks_for_errors():
    logs = _client("logs")
    stub = Stubber(logs)
    stub.add_response("start_query", {"queryId": "q1"})
    stub.add_response(
        "get_query_results",
        {
            "status": "Complete",
            "results": [
                [{"field": "@message", "value": "x" * 5000}, {"field": "@ptr", "value": "p"}]
            ],
            "statistics": {"recordsMatched": 1.0, "recordsScanned": 10.0, "bytesScanned": 100.0},
        },
    )
    with stub:
        res = run_tool(
            _session_for(logs), "logs_insights_query", {"log_group_names": ["/demo/app"]}
        )
    assert res.status == "ok", res.error
    assert "filter @message like" in res.output["query"] and "| limit 20" in res.output["query"]
    [row] = res.output["rows"]
    assert len(row["@message"]) == 1000 and "@ptr" not in row


# ---- CloudTrail (moto has no LookupEvents) -----------------------------------------


def _ct_event(name: str, read_only: bool, **detail) -> dict:
    return {
        "EventId": name,
        "EventName": name,
        "ReadOnly": "true" if read_only else "false",
        "EventTime": datetime(2026, 10, 9, 2, 14, tzinfo=UTC),
        "EventSource": "ec2.amazonaws.com",
        "Username": "dev-tuan",
        "Resources": [{"ResourceType": "AWS::EC2::Subnet", "ResourceName": "subnet-0a1b"}],
        "CloudTrailEvent": json.dumps(
            {
                "userIdentity": {"arn": "arn:aws:iam::111122223333:user/dev-tuan"},
                "sourceIPAddress": "203.0.113.7",
                "userAgent": "aws-cli/2.15",
                "requestParameters": {"associationId": "rtbassoc-1", "routeTableId": "rtb-07c9"},
                **detail,
            }
        ),
    }


def test_cloudtrail_lookup_events_skips_reads_and_parses_details():
    ct = _client("cloudtrail")
    stub = Stubber(ct)
    stub.add_response(
        "lookup_events",
        {
            "Events": [
                _ct_event("DescribeRouteTables", read_only=True),
                _ct_event("ReplaceRouteTableAssociation", read_only=False),
            ],
            "NextToken": "page2",
        },
    )
    stub.add_response(
        "lookup_events", {"Events": [_ct_event("CreateRoute", read_only=False, errorCode="Denied")]}
    )
    with stub:
        res = run_tool(
            _session_for(ct),
            "cloudtrail_lookup_events",
            {"resource_name": "subnet-0a1b", "hours": 72},
        )
    assert res.status == "ok", res.error
    out = res.output
    assert out["filter"] == {"resource_name": "subnet-0a1b"}
    assert [e["event_name"] for e in out["events"]] == [
        "ReplaceRouteTableAssociation",
        "CreateRoute",
    ]
    first = out["events"][0]
    assert first["time"] == "2026-10-09T02:14:00Z"
    assert first["username"] == "dev-tuan" and first["source_ip"] == "203.0.113.7"
    assert first["request_parameters"]["routeTableId"] == "rtb-07c9"
    assert out["events"][1]["error_code"] == "Denied"
    assert out["events_scanned"] == 3


def test_cloudtrail_takes_one_filter():
    res = run_tool(
        None, "cloudtrail_lookup_events", {"resource_name": "subnet-1", "event_name": "CreateRoute"}
    )
    assert res.status == "error" and "one attribute" in res.error


def test_time_window():
    start, end, err = time_window(
        {"start_time": "2026-10-09T09:00:00+07:00", "end_time": "2026-10-09T10:00:00Z"}, 1, 24
    )
    assert err is None and start == datetime(2026, 10, 9, 2, 0, tzinfo=UTC)
    assert end == datetime(2026, 10, 9, 10, 0, tzinfo=UTC)
    _, _, err = time_window({"start_time": "yesterday"}, 1, 24)
    assert err and err.startswith("INVALID_INPUT")
    _, _, err = time_window(
        {"start_time": "2026-10-09T10:00:00Z", "end_time": "2026-10-09T09:00:00Z"}, 1, 24
    )
    assert err
    start, end, err = time_window({"hours": 500}, 1, 24)
    assert err is None and end - start == timedelta(hours=24)  # clamped


# ---- DNS guard -------------------------------------------------------------------


@pytest.fixture
def fake_dns(monkeypatch):
    import dns.resolver

    asked = []

    def fake_resolve(self, hostname, rtype):
        asked.append(hostname)
        raise dns.resolver.NXDOMAIN()

    monkeypatch.setattr(dns.resolver.Resolver, "resolve", fake_resolve)
    return asked


def test_dns_guard_blocks_names_the_user_never_gave(aws, fake_dns):
    ctx = ToolContext(user_text="Tôi trỏ app.example.com về EC2 nhưng không vào được")
    leak = run_tool(aws, "resolve_dns_public", {"hostname": "c2VjcmV0.attacker.example"}, ctx)
    assert leak.status == "error" and leak.error.startswith("HOSTNAME_NOT_ALLOWED")
    assert fake_dns == []  # nothing left the machine

    for allowed in ("app.example.com", "example.com", "www.app.example.com"):
        assert run_tool(aws, "resolve_dns_public", {"hostname": allowed}, ctx).status == "ok"

    ctx.known_hostnames.add("web-alb-1.ap-southeast-1.elb.amazonaws.com")
    res = run_tool(
        aws, "resolve_dns_public", {"hostname": "web-alb-1.ap-southeast-1.elb.amazonaws.com"}, ctx
    )
    assert res.status == "ok"


def test_dns_guard_allows_names_in_the_accounts_hosted_zones(aws, fake_dns):
    aws.client("route53").create_hosted_zone(Name="shop.vn.", CallerReference="z")
    ctx = ToolContext(user_text="web bán hàng không vào được")
    assert run_tool(aws, "resolve_dns_public", {"hostname": "api.shop.vn"}, ctx).status == "ok"
    assert run_tool(aws, "resolve_dns_public", {"hostname": "evil.vn"}, ctx).status == "error"


# ---- errors and size ---------------------------------------------------------------


def test_access_denied_names_the_missing_permission():
    ec2 = _client("ec2")
    stub = Stubber(ec2)
    stub.add_client_error(
        "describe_network_acls",
        service_error_code="UnauthorizedOperation",
        service_message="You are not authorized to perform this operation.",
    )
    with stub:
        res = run_tool(_session_for(ec2), "describe_network_acls", {})
    assert res.status == "error"
    assert res.output["error"] == "AccessDenied"
    assert res.output["action"] == "ec2:DescribeNetworkAcls"
    assert res.error == "AccessDenied: ec2:DescribeNetworkAcls"


def test_huge_results_are_shortened_for_the_model():
    raw = {"items": [{"id": f"x-{i}", "blob": "y" * 1900} for i in range(25)]}
    fitted = _fit(raw)
    assert len(json.dumps(fitted)) <= MAX_RESULT_CHARS
    assert "narrow the query" in fitted["_note"]
