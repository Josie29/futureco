from collections.abc import Iterator
from contextlib import contextmanager

from neo4j import Driver, GraphDatabase, Session

from settings import settings


def open_driver() -> Driver:
    """Construct a driver and prove it can reach the database.

    Separate from `graph_session` because a long-lived process — the API —
    holds one driver for its lifetime and opens a session per request, while a
    CLI wants both scoped to a single `with`.

    Returns:
        A connected driver. The caller owns it and must close it.

    Raises:
        neo4j.exceptions.ServiceUnavailable: If the database is unreachable.
        neo4j.exceptions.AuthError: If the configured credentials are rejected.
    """
    driver: Driver = GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )
    try:
        driver.verify_connectivity()
    except Exception:
        driver.close()
        raise
    return driver


@contextmanager
def graph_session() -> Iterator[Session]:
    """Open a Neo4j session, verifying connectivity before yielding.

    Yields:
        An open session, closed on exit along with its driver.

    Raises:
        neo4j.exceptions.ServiceUnavailable: If the database is unreachable.
        neo4j.exceptions.AuthError: If the configured credentials are rejected.
    """
    driver = open_driver()
    try:
        with driver.session() as session:
            yield session
    finally:
        driver.close()
