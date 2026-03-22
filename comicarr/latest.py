# just updating the sqlite db to latest issue / newest pull

from comicarr import db


def latestcheck():

    myDB = db.DBConnection()
    myDB.select("SELECT * from comics WHERE LatestIssue = 'None'")
