"""Keep main's authentication and ownership checks working with deployed DynamoDB."""

import pytest

from tests.test_auth import cognito as cognito
from tests.test_auth import owned_by_a as owned_by_a
from tests.test_auth import (
    test_decisions_record_who_made_them as _check_decision_actor,
)
from tests.test_auth import (
    test_other_users_see_nothing_and_cannot_touch_it as _check_other_user,
)
from tests.test_auth import test_the_owner_sees_their_data as _check_owner
from tests.test_store import dynamo_api as dynamo_api


@pytest.fixture
def dynamodb_auth(dynamo_api, cognito):
    client, _ = dynamo_api
    return client


@pytest.mark.parametrize("check", [_check_owner, _check_other_user, _check_decision_actor])
def test_authenticated_api_on_dynamodb(dynamodb_auth, request, check):
    # Build the owner's data only after the real storage selector points at DynamoDB.
    owned = request.getfixturevalue("owned_by_a")
    check(dynamodb_auth, owned)
