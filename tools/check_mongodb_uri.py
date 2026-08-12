#!/usr/bin/env python3
"""SSMに置いたMongoDB接続文字列を検証する。値は表示せず、構造と認証可否だけ出す。

デプロイの前に必ず通すこと。壊れた値のままタスクを入れ替えると、
MinimumHealthyPercent: 0 のため復帰先が無くなり本番が停止する
（2026-08-09に13分停止した）。

接続文字列そのものは標準出力にも例外メッセージにも出さない。出力するのは
scheme / ユーザ名 / ホスト / DB名 / クエリと、パスワードの長さ・記号の有無だけ。
両端の文字を出すのは、コピペで混入した空白や改行が目に見えないまま認証を
落とすため。

使い方:
    uv run python tools/check_mongodb_uri.py --parameter-name /asobann/prod/mongodb_uri

パラメータ名を引数で受け取るのは、環境ごとの定義を持たないため。環境と
パラメータ名の対応は呼び出し側（devenv の invoke_tasks/deploy.py の
ENVIRONMENTS）が唯一の正で、ここに書くと二重管理になる。

終了コード: 0 = 認証が通った / 1 = 通らなかった
"""

import argparse
import sys
from urllib.parse import urlsplit

import boto3
from pymongo import MongoClient

ALPHANUMERIC = set('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789')


def get_parameter(profile_name, region_name, name):
    """SecureStringを復号して取り出す。呼び出し側で表示しないこと。"""
    session = boto3.Session(profile_name=profile_name, region_name=region_name)
    ssm = session.client('ssm')
    return ssm.get_parameter(Name=name, WithDecryption=True)['Parameter']['Value']


def describe_uri(uri):
    """接続文字列の構造を返す。パスワードそのものは含めない。

    urlsplitで分解した要素だけを返すので、戻り値にパスワードが混入しない。
    """
    parts = urlsplit(uri)
    password = parts.password or ''
    return {
        'scheme': parts.scheme,
        'username': parts.username,
        'host': parts.hostname,
        'database': parts.path.lstrip('/'),
        'query': parts.query,
        'password_length': len(password),
        'password_has_symbols': bool(set(password) - ALPHANUMERIC),
        'first_char': uri[:1],
        'last_char': uri[-1:],
    }


def check_auth(uri, timeout_ms=10000):
    """実際にAtlasへ接続して認証が通るか確かめ、(ok, 説明) を返す。

    list_collection_names() はアプリが起動時に叩くものと同じ。ping では認証の
    不備を見逃すため、権限を要する操作で確かめる。
    """
    client = MongoClient(uri, serverSelectionTimeoutMS=timeout_ms)
    try:
        database = client.get_database()
        collections = database.list_collection_names()
        return True, (f'db={database.name} version={client.server_info()["version"]} '
                      f'collections={len(collections)}')
    except Exception as e:
        return False, f'{type(e).__name__}: {_redact(str(e), uri)}'
    finally:
        client.close()


def _redact(message, uri):
    """例外メッセージにパスワードが混ざっていても外に出さない。"""
    password = urlsplit(uri).password
    if password:
        message = message.replace(password, '***')
    return message


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--parameter-name', required=True,
                        help='SSMパラメータ名。例: /asobann/prod/mongodb_uri')
    parser.add_argument('--profile', default='asobann', help='AWSプロファイル')
    parser.add_argument('--region', default='us-east-1', help='AWSリージョン')
    args = parser.parse_args()

    uri = get_parameter(args.profile, args.region, args.parameter_name)
    info = describe_uri(uri)

    print(args.parameter_name)
    print(f'  scheme  : {info["scheme"]}')
    print(f'  user    : {info["username"]}')
    print(f'  host    : {info["host"]}')
    print(f'  db      : {info["database"]}')
    print(f'  query   : {info["query"]}')
    print(f'  password: {info["password_length"]}文字 / 記号あり: {info["password_has_symbols"]}')
    # 空白や改行の混入は目に見えないまま認証を落とすので、両端を出す
    print(f'  両端    : {info["first_char"]!r} ... {info["last_char"]!r}')

    ok, detail = check_auth(uri)
    print(f'  接続    : {"OK" if ok else "NG"} ({detail})')

    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
