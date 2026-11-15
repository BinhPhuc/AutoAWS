"""Build, break, repair and delete the KB1–KB7 test scenarios on a REAL AWS account.

DEV/TEST ONLY. This script CREATES and CHANGES resources (and costs a little money). It is not
part of the AutoAWS app, which stays read-only (AGENTS.md hard constraint #1); use a test
account, never production.

    PY=backend/.venv/bin/python
    $PY infra/aws-scenarios/scenario.py up kb1 --profile autoaws-test --region ap-southeast-1
    $PY infra/aws-scenarios/scenario.py fault kb1      # put the incident in place
    $PY infra/aws-scenarios/scenario.py status kb1
    $PY infra/aws-scenarios/scenario.py fix kb1        # undo the incident (optional)
    $PY infra/aws-scenarios/scenario.py down kb1       # fix + delete the stack
    $PY infra/aws-scenarios/scenario.py down all

CloudFormation builds a HEALTHY baseline; `fault` then makes the change through the API, so
CloudTrail records who changed what and when (the evidence the scenarios rely on). Each run
writes the expected root causes with the real resource ids to answers.aws.json, the format
infra/eval/run_eval.py reads (--answers infra/aws-scenarios/answers.aws.json).
"""

import argparse
import contextlib
import fcntl
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import boto3
from botocore.exceptions import ClientError, WaiterError

HERE = Path(__file__).resolve().parent
TEMPLATES = HERE / "templates"
ANSWERS = HERE / "answers.aws.json"
SCENARIOS = [f"kb{i}" for i in range(1, 8)]
LOCAL_HOSTS = {"localhost", "127.0.0.1"}
TAGS = [{"Key": "Project", "Value": "autoaws-demo"}]

ASK = {
    "kb1": "Tôi không SSH được vào instance web-server, Security Group đã mở port 22 rồi.",
    "kb2": "Tôi chạy ứng dụng Docker ở port 8080, đã trỏ {record} về EC2 nhưng không vào được.",
    "kb3": "Từ chiều nay CloudWatch liên tục cảnh báo UnHealthyHostCount, cả 2 target đều "
    "unhealthy dù website vẫn vào được. Chuyện gì đang xảy ra?",
    "kb4": "SSH vào api-server bị treo rồi timeout, Security Group đã cho phép port 22 từ mọi nơi.",
    "kb5": "Tôi vừa tạo instance worker-01 nhưng không SSH vào được.",
    "kb6": "Ở công ty tôi SSH vào bastion được, nhưng về nhà thì không vào được.",
    "kb7": "Từ sau khi deploy bản mới, orders-api trả lỗi 500 cho mọi request. Log ứng dụng "
    "đẩy lên CloudWatch Logs.",
}


class Ctx:
    def __init__(self, args: argparse.Namespace) -> None:
        self.session = boto3.Session(profile_name=args.profile, region_name=args.region)
        if not self.session.region_name:
            sys.exit("Set a region: --region ap-southeast-1 (or AWS_DEFAULT_REGION)")
        if args.endpoint_url and urlparse(args.endpoint_url).hostname not in LOCAL_HOSTS:
            sys.exit("--endpoint-url is only for a local emulator (LocalStack)")
        self.args = args
        kw = {"endpoint_url": args.endpoint_url} if args.endpoint_url else {}
        self.cfn = self.session.client("cloudformation", **kw)
        self.ec2 = self.session.client("ec2", **kw)
        self.ssm = self.session.client("ssm", **kw)
        self.sts = self.session.client("sts", **kw)

    def stack(self, kb: str) -> str:
        return f"autoaws-{kb}"

    def outputs(self, kb: str) -> dict:
        stack = self.cfn.describe_stacks(StackName=self.stack(kb))["Stacks"][0]
        return {o["OutputKey"]: o["OutputValue"] for o in stack.get("Outputs", [])}


# ---- answers -----------------------------------------------------------------------


def _expect(kb: str, out: dict, extra: dict) -> list:
    return {
        "kb1": [
            [
                [out.get("PrivateRouteTableId", ""), "route table"],
                ["0.0.0.0/0", "igw", "internet gateway"],
            ]
        ],
        "kb2": [
            [[extra.get("stale_ip", "?")]],
            [["8080"], [out.get("SecurityGroupId", ""), "security group"]],
        ],
        "kb3": [[["/health"], ["/api/health", "health check", "unhealthy"]]],
        "kb4": [
            [
                [out.get("FaultAclId", ""), "network acl", "nacl"],
                ["1024", "ephemeral", "cổng tạm", "outbound"],
            ]
        ],
        "kb5": [[["public ip", "ip public", "ip công khai", "elastic ip"]]],
        "kb6": [[[out.get("OldUserCidr", "203.0.113.10").split("/")[0]]]],
        "kb7": [[["5432", "orders-db", "operationalerror", "database", "cơ sở dữ liệu"]]],
    }[kb]


@contextlib.contextmanager
def _answers():
    """Read-modify-write of answers.aws.json under a lock: several scenarios may run
    `up` / `down` at the same time, and each must keep the others' entries."""
    with open(ANSWERS.with_suffix(".lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        answers = json.loads(ANSWERS.read_text()) if ANSWERS.exists() else {}
        yield answers
        ANSWERS.write_text(json.dumps(answers, indent=2, ensure_ascii=False))


def write_answer(ctx: Ctx, kb: str, **extra) -> None:
    out = ctx.outputs(kb)
    with _answers() as answers:
        previous = answers.get(kb, {})
        extra = {**{k: v for k, v in previous.items() if k == "stale_ip"}, **extra}
        answers[kb] = {
            **out,
            **extra,
            "ask": ASK[kb].format(record=out.get("RecordName", "app.example.com")),
            "expect": _expect(kb, out, extra),
        }


# ---- stack lifecycle ---------------------------------------------------------------------


_INCLUDE = re.compile(r"^( *)#@include (\S+)$", re.M)


def render(kb: str) -> str:
    """Template with `#@include <path>` lines replaced by that file, at the same indent.

    The mock apps live in infra/demo-apps/ so they can also run locally; their code goes
    into the instance's UserData here. `${` is escaped for Fn::Sub.
    """
    path = TEMPLATES / f"{kb}.yaml"

    def include(m: re.Match) -> str:
        source = (path.parent / m.group(2)).resolve()
        lines = source.read_text().replace("${", "${!").splitlines()
        return "\n".join(m.group(1) + line if line else "" for line in lines)

    return _INCLUDE.sub(include, path.read_text())


def up(ctx: Ctx, kb: str) -> None:
    params = dict(p.split("=", 1) for p in ctx.args.param)
    if kb == "kb2" and not {"HostedZoneId", "DomainName"} <= params.keys():
        sys.exit("kb2 needs a domain: --param HostedZoneId=Z123... --param DomainName=example.com")
    if ctx.args.key_name and kb not in ("kb3", "kb7"):
        params.setdefault("KeyName", ctx.args.key_name)
    print(f"Creating stack {ctx.stack(kb)}…")
    ctx.cfn.create_stack(
        StackName=ctx.stack(kb),
        TemplateBody=render(kb),
        Parameters=[{"ParameterKey": k, "ParameterValue": v} for k, v in params.items()],
        Capabilities=["CAPABILITY_IAM"],
        Tags=TAGS + [{"Key": "autoaws:scenario", "Value": kb}],
        OnFailure="DELETE",
    )
    ctx.cfn.get_waiter("stack_create_complete").wait(
        StackName=ctx.stack(kb), WaiterConfig={"Delay": 15, "MaxAttempts": 80}
    )
    write_answer(ctx, kb)
    print(json.dumps(ctx.outputs(kb), indent=2))
    if kb in ("kb1", "kb2", "kb3", "kb4", "kb7"):
        print(f"Next: wait 2-3 minutes for the instances to boot, then `fault {kb}`.")
    else:
        print(f"{kb}: the incident is built in, ready to diagnose.")


def _release_kb1_subnet(ctx: Ctx) -> None:
    """`fault`/`fix` replace the subnet's route table association, which gives it a new id
    that CloudFormation does not know: deleting the stack would then fail on the route table
    ("has dependencies"). Drop that association; the stack's own one is left to CloudFormation."""
    out = ctx.outputs("kb1")
    own = ctx.cfn.describe_stack_resource(StackName=ctx.stack("kb1"), LogicalResourceId="SubnetRt")
    assoc = _subnet_rt_association(ctx, out["SubnetId"])
    if assoc != own["StackResourceDetail"].get("PhysicalResourceId"):
        ctx.ec2.disassociate_route_table(AssociationId=assoc)
        print(f"kb1: removed association {assoc} (not the stack's)")


def down(ctx: Ctx, kb: str) -> None:
    try:
        if kb == "kb1":
            _release_kb1_subnet(ctx)
        else:
            fix(ctx, kb, quiet=True)  # e.g. a custom NACL cannot be deleted while associated
    except (ClientError, WaiterError, KeyError, IndexError, StopIteration) as e:
        print(f"{kb}: fix before delete skipped ({e})")
    print(f"Deleting stack {ctx.stack(kb)}…")
    ctx.cfn.delete_stack(StackName=ctx.stack(kb))
    ctx.cfn.get_waiter("stack_delete_complete").wait(
        StackName=ctx.stack(kb), WaiterConfig={"Delay": 15, "MaxAttempts": 80}
    )
    with _answers() as answers:
        answers.pop(kb, None)
    print(f"{kb}: deleted")


def status(ctx: Ctx, kb: str) -> None:
    try:
        stack = ctx.cfn.describe_stacks(StackName=ctx.stack(kb))["Stacks"][0]
    except ClientError:
        print(f"{kb}: no stack")
        return
    print(f"{kb}: {stack['StackStatus']}")
    print(json.dumps(ctx.outputs(kb), indent=2))


# ---- incidents ----------------------------------------------------------------------------


def _subnet_rt_association(ctx: Ctx, subnet: str) -> str:
    tables = ctx.ec2.describe_route_tables(
        Filters=[{"Name": "association.subnet-id", "Values": [subnet]}]
    )["RouteTables"]
    return next(
        a["RouteTableAssociationId"]
        for t in tables
        for a in t["Associations"]
        if a.get("SubnetId") == subnet
    )


def _subnet_acl_association(ctx: Ctx, subnet: str) -> tuple[str, str]:
    acls = ctx.ec2.describe_network_acls(
        Filters=[{"Name": "association.subnet-id", "Values": [subnet]}]
    )["NetworkAcls"]
    for acl in acls:
        for a in acl["Associations"]:
            if a["SubnetId"] == subnet:
                return a["NetworkAclAssociationId"], acl["NetworkAclId"]
    raise KeyError(f"no network ACL association for {subnet}")


def _default_acl(ctx: Ctx, vpc: str) -> str:
    return ctx.ec2.describe_network_acls(
        Filters=[{"Name": "vpc-id", "Values": [vpc]}, {"Name": "default", "Values": ["true"]}]
    )["NetworkAcls"][0]["NetworkAclId"]


def _run_on(ctx: Ctx, instance_ids: list[str], commands: list[str], what: str) -> None:
    """SSM Run Command (a 'deploy' that CloudTrail records as SendCommand)."""
    deadline = time.time() + 600
    while True:
        online = {
            i["InstanceId"]
            for i in ctx.ssm.describe_instance_information(
                Filters=[{"Key": "InstanceIds", "Values": instance_ids}]
            )["InstanceInformationList"]
            if i["PingStatus"] == "Online"
        }
        if online >= set(instance_ids):
            break
        if time.time() > deadline:
            sys.exit(f"SSM Agent not online on {set(instance_ids) - online} after 10 minutes")
        print("Waiting for SSM Agent…")
        time.sleep(15)
    cmd = ctx.ssm.send_command(
        InstanceIds=instance_ids,
        DocumentName="AWS-RunShellScript",
        Comment=what,
        Parameters={"commands": commands},
    )["Command"]["CommandId"]
    for iid in instance_ids:
        ctx.ssm.get_waiter("command_executed").wait(CommandId=cmd, InstanceId=iid)
    print(f"{what}: done on {', '.join(instance_ids)}")


def fault(ctx: Ctx, kb: str) -> None:
    out = ctx.outputs(kb)
    if kb == "kb1":
        assoc = _subnet_rt_association(ctx, out["SubnetId"])
        ctx.ec2.replace_route_table_association(
            AssociationId=assoc, RouteTableId=out["PrivateRouteTableId"]
        )
        print(f"kb1: {out['SubnetId']} now uses {out['PrivateRouteTableId']} (no Internet route)")
    elif kb == "kb2":
        iid = out["InstanceId"]
        old = ctx.ec2.describe_instances(InstanceIds=[iid])["Reservations"][0]["Instances"][0]
        stale_ip = old.get("PublicIpAddress")
        ctx.ec2.stop_instances(InstanceIds=[iid])
        ctx.ec2.get_waiter("instance_stopped").wait(InstanceIds=[iid])
        ctx.ec2.start_instances(InstanceIds=[iid])
        ctx.ec2.get_waiter("instance_running").wait(InstanceIds=[iid])
        new = ctx.ec2.describe_instances(InstanceIds=[iid])["Reservations"][0]["Instances"][0]
        write_answer(ctx, kb, stale_ip=stale_ip)
        print(
            f"kb2: public IP {stale_ip} -> {new.get('PublicIpAddress')}; {out['RecordName']} "
            f"still points to {stale_ip}"
        )
    elif kb == "kb3":
        ids = out["InstanceIds"].split(",")
        _run_on(
            ctx,
            ids,
            ["echo 2.0.0 > /opt/app/VERSION", "systemctl restart app"],
            "deploy web v2.0.0",
        )
        print("kb3: targets turn unhealthy within ~30 s; the alarm fires within ~2 minutes")
    elif kb == "kb4":
        assoc, _ = _subnet_acl_association(ctx, out["SubnetId"])
        ctx.ec2.replace_network_acl_association(AssociationId=assoc, NetworkAclId=out["FaultAclId"])
        print(f"kb4: {out['SubnetId']} now uses {out['FaultAclId']} (outbound 1024-65535 denied)")
    elif kb == "kb7":
        _run_on(
            ctx,
            [out["InstanceId"]],
            [
                "echo 2.5.0 > /opt/app/VERSION",
                "systemctl restart app",
                "sleep 2",
                # some traffic so the log has failing requests
                "for i in 1 2 3 4 5; do curl -s -o /dev/null localhost/api/orders; done",
            ],
            "deploy orders-api v2.5.0",
        )
        print("kb7: log lines reach CloudWatch Logs within ~1 minute")
    else:
        print(f"{kb}: the incident is built into the stack, nothing to do")


def fix(ctx: Ctx, kb: str, quiet: bool = False) -> None:
    out = ctx.outputs(kb)
    if kb == "kb1":
        assoc = _subnet_rt_association(ctx, out["SubnetId"])
        ctx.ec2.replace_route_table_association(
            AssociationId=assoc, RouteTableId=out["PublicRouteTableId"]
        )
        print("kb1: subnet back on the public route table")
    elif kb == "kb3":
        _run_on(
            ctx,
            out["InstanceIds"].split(","),
            ["echo 1.4.2 > /opt/app/VERSION", "systemctl restart app"],
            "roll back web v1.4.2",
        )
    elif kb == "kb4":
        assoc, current = _subnet_acl_association(ctx, out["SubnetId"])
        default = _default_acl(ctx, out["VpcId"])
        if current != default:
            ctx.ec2.replace_network_acl_association(AssociationId=assoc, NetworkAclId=default)
        print("kb4: subnet back on the default network ACL")
    elif kb == "kb7":
        _run_on(
            ctx,
            [out["InstanceId"]],
            ["echo 2.4.3 > /opt/app/VERSION", "systemctl restart app"],
            "roll back orders-api v2.4.3",
        )
    elif not quiet:
        print(f"{kb}: nothing to undo (the stack itself is the incident; `down` removes it)")


# ---------------------------------------------------------------------------------------


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("action", choices=["up", "fault", "fix", "down", "status", "render"])
    p.add_argument("scenario", help="kb1..kb7, or all")
    p.add_argument("--profile", default=None, help="AWS profile of the TEST account")
    p.add_argument("--region", default=None)
    p.add_argument("--key-name", default="", help="EC2 key pair, only to try SSH yourself")
    p.add_argument("--param", action="append", default=[], help="template Key=Value")
    p.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    p.add_argument(
        "--endpoint-url", default="", help="dev only: smoke-test against LocalStack (localhost)"
    )
    args = p.parse_args()

    kbs = SCENARIOS if args.scenario == "all" else [args.scenario.lower()]
    if any(kb not in SCENARIOS for kb in kbs):
        sys.exit(f"Unknown scenario {args.scenario}; use kb1..kb7 or all")
    if args.action == "up" and args.scenario == "all":
        sys.exit("Create scenarios one at a time (kb2 needs a domain, kb3 has an ALB)")
    if args.action == "render":  # offline: the template as deployed, for cfn-lint / the console
        for kb in kbs:
            print(render(kb))
        return
    ctx = Ctx(args)

    if args.action in ("up", "fault", "fix", "down") and not args.yes:
        account = ctx.sts.get_caller_identity()["Account"]
        answer = input(
            f"{args.action} {', '.join(kbs)} in account {account}, region "
            f"{ctx.session.region_name}. This changes real resources. Continue? [y/N] "
        )
        if answer.strip().lower() != "y":
            sys.exit("Cancelled")

    action = {"up": up, "fault": fault, "fix": fix, "down": down, "status": status}[args.action]
    for kb in kbs:
        if args.scenario == "all" and args.action in ("down", "status"):
            try:
                ctx.cfn.describe_stacks(StackName=ctx.stack(kb))
            except ClientError:
                continue
        action(ctx, kb)


if __name__ == "__main__":
    main()
