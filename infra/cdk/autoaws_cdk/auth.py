"""AutoAws-Auth: who may use the platform (report §2.3.1, docs/API_CONTRACT.md §0.1).

Cognito user pool (Lite feature plan: the free tier covers a class project), its Hosted UI
domain and one public app client for the web app: OAuth2 authorization code + PKCE, no
client secret (a browser cannot keep one). The HTTP API checks the access tokens with a JWT
authorizer (AutoAws-Api); the backend reads the verified claims and keeps every user's data
apart.

The client's callback URLs are the site URL from the Frontend stack (deployed before this
one), so a single `cdk deploy` is enough.
"""

from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_cognito as cognito
from constructs import Construct

from .config import Config

LOCAL_WEB = "http://localhost:5173"


class AuthStack(Stack):
    def __init__(self, scope: Construct, cid: str, cfg: Config, site_url: str, **kwargs) -> None:
        super().__init__(scope, cid, **kwargs)
        self.user_pool = cognito.UserPool(
            self,
            "Users",
            user_pool_name=f"autoaws-{cfg.env_name}",
            feature_plan=cognito.FeaturePlan.LITE,
            self_sign_up_enabled=cfg.self_sign_up,
            sign_in_aliases=cognito.SignInAliases(email=True),
            auto_verify=cognito.AutoVerifiedAttrs(email=True),
            standard_attributes=cognito.StandardAttributes(
                email=cognito.StandardAttribute(required=True, mutable=True)
            ),
            password_policy=cognito.PasswordPolicy(
                min_length=12,
                require_lowercase=True,
                require_uppercase=True,
                require_digits=True,
                require_symbols=False,
            ),
            mfa=cognito.Mfa.OPTIONAL,
            mfa_second_factor=cognito.MfaSecondFactor(otp=True, sms=False),
            account_recovery=cognito.AccountRecovery.EMAIL_ONLY,
            deletion_protection=not cfg.destroy_data,
            removal_policy=RemovalPolicy.DESTROY if cfg.destroy_data else RemovalPolicy.RETAIN,
        )
        # Domain prefixes may not contain "aws", "amazon" or "cognito"
        prefix = cfg.auth_domain_prefix or f"autodiag-{cfg.env_name}-{self.account}"
        self.domain = self.user_pool.add_domain(
            "HostedUi",
            cognito_domain=cognito.CognitoDomainOptions(domain_prefix=prefix),
        )

        origins = [site_url]
        if cfg.env_name == "dev":
            origins.append(LOCAL_WEB)  # `pnpm dev` against the deployed API
        self.client = self.user_pool.add_client(
            "WebClient",
            user_pool_client_name=f"autoaws-{cfg.env_name}-web",
            generate_secret=False,
            o_auth=cognito.OAuthSettings(
                flows=cognito.OAuthFlows(authorization_code_grant=True),
                scopes=[
                    cognito.OAuthScope.OPENID,
                    cognito.OAuthScope.EMAIL,
                    cognito.OAuthScope.PROFILE,
                ],
                callback_urls=[f"{o}/auth/callback" for o in origins],
                logout_urls=[f"{o}/" for o in origins],
            ),
            supported_identity_providers=[cognito.UserPoolClientIdentityProvider.COGNITO],
            prevent_user_existence_errors=True,
            enable_token_revocation=True,
            access_token_validity=Duration.hours(1),
            id_token_validity=Duration.hours(1),
            refresh_token_validity=Duration.days(7),
        )
        self.domain_url = self.domain.base_url()
        CfnOutput(self, "UserPoolId", value=self.user_pool.user_pool_id)
        CfnOutput(self, "WebClientId", value=self.client.user_pool_client_id)
        CfnOutput(self, "HostedUiUrl", value=self.domain_url)
