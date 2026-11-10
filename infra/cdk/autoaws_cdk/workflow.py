"""AutoAws-Workflow: state machine remediation-flow + SNS topic (report §2.7, Figure 2.3).

One execution per proposal (started by agent-worker, name = proposal id):

  Notify -> WaitForApproval (.waitForTaskToken, 24 h) -> Recheck (agent-worker, read-only)
         -> Execute (action-executor, AutoAWSRemediation) -> Verify (agent-worker) -> NotifyResult

The user's decision arrives with SendTaskSuccess (approve) or SendTaskFailure (REJECTED /
SUPERSEDED / EXPIRED) from the api-handler. The steps are idempotent on the proposal's
stored status, so a retried state never writes twice.
"""

from aws_cdk import Duration, Stack
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk import aws_sns as sns
from aws_cdk import aws_sns_subscriptions as subs
from aws_cdk import aws_stepfunctions as sfn
from aws_cdk import aws_stepfunctions_tasks as tasks
from constructs import Construct

from .config import STATE_MACHINE_NAME, Config

DECIDED_ERRORS = ["REJECTED", "SUPERSEDED", "EXPIRED"]


class WorkflowStack(Stack):
    def __init__(
        self,
        scope: Construct,
        cid: str,
        cfg: Config,
        agent_worker: lambda_.IFunction,
        action_executor: lambda_.IFunction,
        **kwargs,
    ) -> None:
        super().__init__(scope, cid, **kwargs)
        self.topic = sns.Topic(self, "Notifications", display_name="AutoAWS")
        if cfg.notification_email:
            self.topic.add_subscription(subs.EmailSubscription(cfg.notification_email))

        def invoke(name: str, fn: lambda_.IFunction, mode: str, result: str) -> tasks.LambdaInvoke:
            return tasks.LambdaInvoke(
                self,
                name,
                lambda_function=fn,
                payload=sfn.TaskInput.from_object(
                    {"mode": mode, "proposal_id": sfn.JsonPath.string_at("$.proposal_id")}
                ),
                payload_response_only=True,
                result_path=result,
                retry_on_service_exceptions=True,
            )

        def notify(name: str, text: str) -> tasks.SnsPublish:
            # Summary and link only: no task token, no configuration details (report §2.3.1)
            return tasks.SnsPublish(
                self,
                name,
                topic=self.topic,
                subject="AutoAWS",
                message=sfn.TaskInput.from_json_path_at(
                    f"States.Format('{text}', $.proposal_id, $.summary, $.link)"
                ),
                result_path=sfn.JsonPath.DISCARD,
            )

        notify_pending = notify(
            "NotifyPending", "Proposal {} is waiting for your approval: {}. Review it at {}"
        )
        notify_result = notify(
            "NotifyResult", "Proposal {} ({}) has finished. See the result at {}"
        )

        wait = tasks.LambdaInvoke(
            self,
            "WaitForApproval",
            lambda_function=action_executor,
            integration_pattern=sfn.IntegrationPattern.WAIT_FOR_TASK_TOKEN,
            payload=sfn.TaskInput.from_object(
                {
                    "mode": "store_token",
                    "proposal_id": sfn.JsonPath.string_at("$.proposal_id"),
                    "task_token": sfn.JsonPath.task_token,
                }
            ),
            task_timeout=sfn.Timeout.duration(Duration.hours(24)),
            result_path="$.decision",
        )
        expire = invoke("Expire", agent_worker, "expire", "$.expired")
        decided = sfn.Succeed(self, "DecidedWithoutChange")
        wait.add_catch(expire, errors=["States.Timeout"], result_path="$.error")
        wait.add_catch(decided, errors=DECIDED_ERRORS, result_path="$.error")
        expire.next(decided)

        recheck = invoke("Recheck", agent_worker, "recheck", "$.recheck")
        execute = invoke("Execute", action_executor, "execute", "$.execute")
        verify = invoke("Verify", agent_worker, "verify_proposal", "$.verify")

        definition = (
            notify_pending.next(wait)
            .next(recheck)
            .next(
                sfn.Choice(self, "StillAsPreviewed")
                .when(
                    sfn.Condition.boolean_equals("$.recheck.ok", True),
                    execute.next(
                        sfn.Choice(self, "Applied")
                        .when(
                            sfn.Condition.boolean_equals("$.execute.ok", True),
                            verify.next(notify_result),
                        )
                        .otherwise(notify_result)
                    ),
                )
                .otherwise(notify_result)
            )
        )
        self.state_machine = sfn.StateMachine(
            self,
            "RemediationFlow",
            state_machine_name=STATE_MACHINE_NAME,
            state_machine_type=sfn.StateMachineType.STANDARD,  # waits up to 24 h for a person
            definition_body=sfn.DefinitionBody.from_chainable(definition),
            timeout=Duration.hours(25),
            tracing_enabled=True,
            logs=sfn.LogOptions(
                destination=logs.LogGroup(self, "FlowLogs", retention=logs.RetentionDays.ONE_MONTH),
                level=sfn.LogLevel.ERROR,
            ),
        )
