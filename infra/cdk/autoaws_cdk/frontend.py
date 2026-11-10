"""AutoAws-Frontend: private S3 bucket + CloudFront (OAC). /api/* is forwarded to the HTTP
API, so the web app and the API share one origin (no CORS, relative /api URLs)."""

from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_apigatewayv2 as apigw
from aws_cdk import aws_cloudfront as cf
from aws_cdk import aws_cloudfront_origins as origins
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_deployment as s3deploy
from constructs import Construct

from .config import ROOT, Config


class FrontendStack(Stack):
    def __init__(
        self, scope: Construct, cid: str, cfg: Config, http_api: apigw.IHttpApi, **kwargs
    ) -> None:
        super().__init__(scope, cid, **kwargs)
        bucket = s3.Bucket(
            self,
            "Site",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            encryption=s3.BucketEncryption.S3_MANAGED,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )
        api_domain = f"{http_api.api_id}.execute-api.{self.region}.amazonaws.com"
        self.distribution = cf.Distribution(
            self,
            "Distribution",
            default_root_object="index.html",
            default_behavior=cf.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(bucket),
                viewer_protocol_policy=cf.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
            ),
            additional_behaviors={
                "/api/*": cf.BehaviorOptions(
                    origin=origins.HttpOrigin(api_domain),
                    viewer_protocol_policy=cf.ViewerProtocolPolicy.HTTPS_ONLY,
                    allowed_methods=cf.AllowedMethods.ALLOW_ALL,
                    cache_policy=cf.CachePolicy.CACHING_DISABLED,
                    origin_request_policy=cf.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
                )
            },
            # Single-page app: every unknown path is the app
            error_responses=[
                cf.ErrorResponse(
                    http_status=code,
                    response_http_status=200,
                    response_page_path="/index.html",
                    ttl=Duration.seconds(0),
                )
                for code in (403, 404)
            ],
        )
        dist = ROOT / "frontend/dist"
        if (dist / "index.html").exists():  # `pnpm build` first; otherwise deploy the API only
            s3deploy.BucketDeployment(
                self,
                "Deploy",
                sources=[s3deploy.Source.asset(str(dist))],
                destination_bucket=bucket,
                distribution=self.distribution,
            )
        CfnOutput(self, "Url", value=f"https://{self.distribution.distribution_domain_name}")
