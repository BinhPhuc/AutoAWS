from fastapi import APIRouter

from app.api.schemas import ToolOut
from app.aws.registry import list_tools
from app.responses import ok

router = APIRouter(prefix="/tools", tags=["tools"])


@router.get("")
def get_tools():
    items = [
        ToolOut(
            name=t.name,
            group=t.group,
            label=t.label,
            description=t.description,
            input_schema=t.input_schema,
            aws_actions=t.aws_actions,
        )
        for t in list_tools()
    ]
    return ok(items)
