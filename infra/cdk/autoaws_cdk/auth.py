"""Cognito public SPA client: managed sign-in, email verification, code + PKCE."""

from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_cognito as cognito
from constructs import Construct

from .config import Config


class AuthStack(Stack):
    def __init__(self, scope: Construct, cid: str, cfg: Config, **kwargs) -> None:
        super().__init__(scope, cid, **kwargs)
        self.pool = cognito.UserPool(
            self,
            "Users",
            self_sign_up_enabled=True,
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
                require_symbols=True,
            ),
            account_recovery=cognito.AccountRecovery.EMAIL_ONLY,
            removal_policy=RemovalPolicy.RETAIN,
        )
        domain = self.pool.add_domain(
            "Domain",
            cognito_domain=cognito.CognitoDomainOptions(
                domain_prefix=f"autoaws-{cfg.env_name}-{self.account}"
            ),
        )
        # Deploy once to get CloudFront.Url, then set frontendUrl and deploy again.
        origin = (cfg.frontend_url or "http://localhost:5173").rstrip("/")
        self.client = self.pool.add_client(
            "WebClient",
            generate_secret=False,
            prevent_user_existence_errors=True,
            supported_identity_providers=[cognito.UserPoolClientIdentityProvider.COGNITO],
            access_token_validity=Duration.minutes(15),
            id_token_validity=Duration.minutes(15),
            refresh_token_validity=Duration.days(1),
            enable_token_revocation=True,
            o_auth=cognito.OAuthSettings(
                flows=cognito.OAuthFlows(authorization_code_grant=True),
                scopes=[
                    cognito.OAuthScope.OPENID,
                    cognito.OAuthScope.EMAIL,
                    cognito.OAuthScope.PROFILE,
                ],
                callback_urls=[f"{origin}/auth/callback"],
                logout_urls=[origin],
            ),
        )
        self.issuer = self.pool.user_pool_provider_url
        self.domain = domain.base_url()
        CfnOutput(self, "Issuer", value=self.issuer)
        CfnOutput(self, "ClientId", value=self.client.user_pool_client_id)
        CfnOutput(self, "DomainUrl", value=self.domain)
