# just updating the sqlite db to latest issue / newest pull

from sqlalchemy import select

from comicarr import db
from comicarr.tables import comics


def latestcheck():

    with db.get_engine().connect() as conn:
        stmt = select(comics).where(comics.c.LatestIssue == "None")
        conn.execute(stmt)
