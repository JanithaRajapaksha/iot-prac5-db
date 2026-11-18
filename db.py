import configparser
import os
import mysql.connector
from mysql.connector import pooling

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "db.ini")
_pools = {}


def get_connection(role, pooled=False):
    """Return a connection using the credentials of 'writer' or 'reader'."""
    cfg = configparser.ConfigParser(interpolation=None)
    if not cfg.read(CONFIG_PATH):
        raise FileNotFoundError(CONFIG_PATH)

    params = dict(cfg[role])
    if pooled:
        if role not in _pools:
            _pools[role] = pooling.MySQLConnectionPool(
                pool_name=f"{role}_pool",
                pool_size=10,
                connection_timeout=5,
                **params,
            )
        return _pools[role].get_connection()

    return mysql.connector.connect(connection_timeout=5, **params)
