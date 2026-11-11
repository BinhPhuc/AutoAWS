"""AutoAws-Frontend: private S3 bucket + CloudFront (OAC). /api/* is forwarded to the HTTP
API, so the web app and the API share one origin (no CORS, relative /api URLs).

The HTTP API itself is created here, empty (no stage, no routes): CloudFront needs its
domain, Cognito needs the CloudFront URL for its callbacks, and the API's authorizer needs
the Cognito client. Creating the bare API first makes that a straight line
(Frontend -> Auth -> Api, which adds the stage, routes and authorizer), so one
`cdk deploy` sets everything up."""

from aws_cdk import CfnOutput, RemovalPolicy, Stack
from aws_cdk import aws_apigatewayv2 as apigw
from aws_cdk import aws_cloudfront as cf
from aws_cdk import aws_cloudfront_origins as origins
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_deployment as s3deploy
from constructs import Construct

from .config import ROOT, Config


class FrontendStack(Stack):
    def __init__(
        self,
        scope: Construct,
        cid: str,
        cfg: Config,
        **kwargs,
    ) -> None:
        super().__init__(scope, cid, **kwargs)
        self.http_api = apigw.HttpApi(
            self, "HttpApi", api_name=f"autoaws-{cfg.env_name}", create_default_stage=False
        )
        http_api = self.http_api
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
        # Single-page app: a path without a file extension is a client-side route. Only on
        # the site behaviour: distribution-wide error responses would also turn the API's
        # 403 / 404 envelopes into index.html with status 200.
        spa_rewrite = cf.Function(
            self,
            "SpaRewrite",
            runtime=cf.FunctionRuntime.JS_2_0,
            code=cf.FunctionCode.from_inline(
                "function handler(event) {\n"
                "  var request = event.request;\n"
                "  var last = request.uri.split('/').pop();\n"
                "  if (last.indexOf('.') === -1) { request.uri = '/index.html'; }\n"
                "  return request;\n"
                "}\n"
            ),
        )
        self.distribution = cf.Distribution(
            self,
            "Distribution",
            default_root_object="index.html",
            default_behavior=cf.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(bucket),
                viewer_protocol_policy=cf.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                function_associations=[
                    cf.FunctionAssociation(
                        function=spa_rewrite,
                        event_type=cf.FunctionEventType.VIEWER_REQUEST,
                    )
                ],
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
        # The site URL: a custom domain when configured, otherwise CloudFront's own
        self.site_url = (
            cfg.frontend_url.rstrip("/") or f"https://{self.distribution.distribution_domain_name}"
        )
        CfnOutput(self, "Url", value=self.site_url)
        CfnOutput(self, "ApiUrl", value=self.http_api.api_endpoint)
