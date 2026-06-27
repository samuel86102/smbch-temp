#!/usr/bin/env python3
"""建立 / 重設 smbc_website 後台管理員帳號。

用法：
    python create_admin.py                 # 互動式輸入帳號與密碼
    python create_admin.py <account>       # 指定帳號，密碼仍互動輸入

密碼以 Werkzeug 的 scrypt 雜湊存入 `user` 表（與站內既有慣例一致）。
若帳號已存在，會詢問是否重設其密碼。
"""
import os
import sys
import getpass

import pymysql
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash

load_dotenv()


def get_connection():
    """依 .env 連線 smbc_website（伺服器不支援 SSL，pymysql 預設即不啟用）。"""
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


def main():
    account = sys.argv[1] if len(sys.argv) > 1 else input("管理員帳號: ").strip()
    if not account:
        sys.exit("帳號不可為空。")

    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM `user` WHERE account = %s", (account,))
        existing = cur.fetchone()

        if existing:
            ans = input(f"帳號 '{account}' 已存在，要重設密碼嗎？[y/N] ").strip().lower()
            if ans != "y":
                sys.exit("已取消。")

        pwd = getpass.getpass("密碼: ")
        if not pwd:
            sys.exit("密碼不可為空。")
        if pwd != getpass.getpass("再次輸入密碼: "):
            sys.exit("兩次密碼不一致。")

        pwd_hash = generate_password_hash(pwd)  # 預設 scrypt

        if existing:
            cur.execute("UPDATE `user` SET pwd = %s WHERE id = %s", (pwd_hash, existing["id"]))
            print(f"✅ 已重設帳號 '{account}' 的密碼。")
        else:
            cur.execute(
                "INSERT INTO `user` (account, pwd) VALUES (%s, %s)", (account, pwd_hash)
            )
            print(f"✅ 已建立管理員帳號 '{account}' (id={cur.lastrowid})。")

    conn.close()


if __name__ == "__main__":
    main()
