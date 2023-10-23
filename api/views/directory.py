from django.http import HttpRequest
from hatchway import api_view

from api import schemas


@api_view.get
def directory(
    request: HttpRequest,
    limit: int = 40,
    offset: int | None = None,
    order: str = "active",
    local: bool = True,
) -> list[schemas.Account]:
    # We don't implement this yet
    return []
