#!/usr/bin/env python3
"""AutoAWS platform account — CDK app (report §2.8, Table 2.12).

    cd infra/cdk && ./build_lambda.sh            # backend code + deps for Lambda
    .venv/bin/python app.py                      # synth only (or: npx cdk synth / deploy)

Stacks (prefix AutoAws-<envName>-): Data, Agent, Workflow, Api, Frontend, Ops.
Auth (Cognito) is not part of this round.
"""

import os

import aws_cdk as cdk
from autoaws_cdk.agent import AgentStack
from autoaws_cdk.api import ApiStack
from autoaws_cdk.config import Config
from autoaws_cdk.data import DataStack
from autoaws_cdk.frontend import FrontendStack
from autoaws_cdk.ops import OpsStack
from autoaws_cdk.workflow import WorkflowStack


def build(app: cdk.App) -> dict[str, cdk.Stack]:
    cfg = Config.from_context(app.node)
    if not (cfg.lambda_asset / "app").is_dir():
        raise SystemExit(
            f"Lambda asset {cfg.lambda_asset} not found: run infra/cdk/build_lambda.sh first "
            "(or -c lambdaAsset=<dir>)"
        )
    region = os.environ.get("CDK_DEFAULT_REGION")
    if not region:  # the KMS-encrypted table and the role ARNs need a concrete region
        raise SystemExit("Set the target Region: AWS_REGION / CDK_DEFAULT_REGION (or a profile)")
    env = cdk.Environment(account=os.environ.get("CDK_DEFAULT_ACCOUNT"), region=region)
    p = f"AutoAws-{cfg.env_name}"
    data = DataStack(app, f"{p}-Data", cfg, env=env)
    agent = AgentStack(app, f"{p}-Agent", cfg, data.table, data.key, env=env)
    workflow = WorkflowStack(
        app, f"{p}-Workflow", cfg, agent.agent_worker, agent.action_executor, env=env
    )
    api = ApiStack(app, f"{p}-Api", cfg, data.table, data.key, agent.agent_worker, env=env)
    frontend = FrontendStack(app, f"{p}-Frontend", cfg, api.http_api, env=env)
    ops = OpsStack(
        app,
        f"{p}-Ops",
        cfg,
        [agent.agent_worker, agent.action_executor, api.handler],
        workflow.state_machine,
        env=env,
    )
    for stack in (data, agent, workflow, api, frontend, ops):
        cdk.Tags.of(stack).add("Project", "autoaws")
        cdk.Tags.of(stack).add("Environment", cfg.env_name)
    return {
        "data": data,
        "agent": agent,
        "workflow": workflow,
        "api": api,
        "frontend": frontend,
        "ops": ops,
    }


if __name__ == "__main__":
    # `cdk` CLI sets CDK_OUTDIR; a plain `python app.py` writes to cdk.out as well
    app = cdk.App(outdir=os.environ.get("CDK_OUTDIR", "cdk.out"))
    build(app)
    app.synth()
