"""AutoAws-Ops: alarms (Lambda errors / throttles, failed flows) and the cost budget
(report §2.9)."""

from aws_cdk import Duration, Stack
from aws_cdk import aws_budgets as budgets
from aws_cdk import aws_cloudwatch as cw
from aws_cdk import aws_cloudwatch_actions as cw_actions
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_sns as sns
from aws_cdk import aws_sns_subscriptions as subs
from aws_cdk import aws_stepfunctions as sfn
from constructs import Construct

from .config import Config


class OpsStack(Stack):
    def __init__(
        self,
        scope: Construct,
        cid: str,
        cfg: Config,
        functions: list[lambda_.Function],
        state_machine: sfn.StateMachine,
        **kwargs,
    ) -> None:
        super().__init__(scope, cid, **kwargs)
        topic = sns.Topic(self, "Alarms", display_name="AutoAWS alarms")
        if cfg.alarm_email:
            topic.add_subscription(subs.EmailSubscription(cfg.alarm_email))
        action = cw_actions.SnsAction(topic)

        def alarm(name: str, metric: cw.Metric) -> None:
            cw.Alarm(
                self,
                name,
                metric=metric,
                threshold=1,
                evaluation_periods=1,
                comparison_operator=cw.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
                treat_missing_data=cw.TreatMissingData.NOT_BREACHING,
            ).add_alarm_action(action)

        for fn in functions:
            name = fn.node.id
            alarm(f"{name}Errors", fn.metric_errors(period=Duration.minutes(5)))
            alarm(f"{name}Throttles", fn.metric_throttles(period=Duration.minutes(5)))
        alarm("FlowFailed", state_machine.metric_failed(period=Duration.minutes(5)))

        if cfg.alarm_email:
            budgets.CfnBudget(
                self,
                "Budget",
                budget=budgets.CfnBudget.BudgetDataProperty(
                    budget_type="COST",
                    time_unit="MONTHLY",
                    budget_limit=budgets.CfnBudget.SpendProperty(amount=cfg.budget_usd, unit="USD"),
                ),
                notifications_with_subscribers=[
                    budgets.CfnBudget.NotificationWithSubscribersProperty(
                        notification=budgets.CfnBudget.NotificationProperty(
                            comparison_operator="GREATER_THAN",
                            notification_type=kind,
                            threshold=100,
                            threshold_type="PERCENTAGE",
                        ),
                        subscribers=[
                            budgets.CfnBudget.SubscriberProperty(
                                address=cfg.alarm_email, subscription_type="EMAIL"
                            )
                        ],
                    )
                    for kind in ("ACTUAL", "FORECASTED")
                ],
            )
