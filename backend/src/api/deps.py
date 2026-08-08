from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from neo4j import Session


def get_session(request: Request) -> Iterator[Session]:
    """Yield a Neo4j session from the runtime the app built at startup.

    Reads the driver off `app.state` rather than importing the app, because
    the app imports this module's routers — taking the dependency the other
    way would close the import cycle.

    Args:
        request: The active request, carrying the runtime on app state.

    Yields:
        An open session, closed when the request ends.
    """
    driver = request.app.state.runtime.driver
    with driver.session() as session:
        yield session


GraphSession = Annotated[Session, Depends(get_session)]
