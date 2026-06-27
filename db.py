"""smbc_website 資料庫連線 helper（PyMySQL）。"""
import os

import pymysql
from dotenv import load_dotenv

load_dotenv()


def get_connection():
    """依 .env 建立 smbc_website 連線。

    伺服器（MariaDB 10.11）不支援 SSL，PyMySQL 預設即不啟用，故無需特別停用。
    """
    return pymysql.connect(
        host=os.environ["DB_URL"],
        port=int(os.environ.get("DB_PORT", 3306)),
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWD"],
        database=os.environ["DB_NAME"],
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
    )
