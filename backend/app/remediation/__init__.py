"""Human-in-the-loop remediation flow (docs/API_CONTRACT.md §7). No boto3 here: AWS calls
go through app.aws.remediation (catalog + locked write session) and app.aws.credentials."""
