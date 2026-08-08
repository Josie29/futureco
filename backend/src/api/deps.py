from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from neo4j import Driver, GraphDatabase, Session

from settings import settings


def create_driver() -> Driver:
    """Open the long-lived driver the app holds for its lifetime.

    Connectivity is deliberately not verified here. The API should start
    whether or not the database is up, and report the outage per-request
    instead of refusing to boot.

    Returns:
        A configured driver. The caller owns closing it.
    """
    return GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )


def get_session(request: Request) -> Iterator[Session]:
    """Yield a session from the app's driver.

    Args:
        request: The active request, carrying the driver on app state.

    Yields:
        An open session, closed when the request ends.
    """
    driver: Driver = request.app.state.neo4j
    with driver.session() as session:
        yield session


GraphSession = Annotated[Session, Depends(get_session)]
