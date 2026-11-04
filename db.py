import configparser
import os
import mysql.connector

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "db.ini")


def get_connection(role):
    """Return a connection using the credentials of 'writer' or 'reader'."""
    cfg = configparser.ConfigParser(interpolation=None)
    if not cfg.read(CONFIG_PATH):
        raise FileNotFoundError(CONFIG_PATH)
    return mysql.connector.connect(connection_timeout=5, **dict(cfg[role]))

