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
    uv run python tools/check_mongodb_uri.py --env prod
    uv run python tools/check_mongodb_uri.py --parameter-name /asobann/prod/mongodb_uri

環境とパラメータ名の対応は environments.py が唯一の正。

終了コード: 0 = 認証が通った / 1 = 通らなかった
"""

import argparse
import sys
from urllib.parse import unquote, urlsplit

import boto3
from pymongo import MongoClient

import environments

ALPHANUMERIC = set('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789')


def get_parameter(profile_name, region_name, name):
    """SecureStringを復号して取り出す。呼び出し側で表示しないこと。

    profile_name が None なら既定の認証情報チェーンを使う。CIやECSタスクのように
    ロール/環境変数で認証している環境ではプロファイルが存在しないため。
    手元での既定プロファイルは environments.py が AWS_PROFILE で与える。
    """
    session = boto3.Session(profile_name=profile_name or None,
                            region_name=region_name)
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
    """例外メッセージにパスワードが混ざっていても外に出さない。

    urlsplit(uri).password はパーセントデコードせず、URIに書かれたままの文字列を
    返す。一方 pymongo は接続時にデコードするので、例外メッセージにはデコード後の
    値が現れうる。両方を伏字にする。
    """
    password = urlsplit(uri).password
    if not password:
        return message
    for form in {password, unquote(password)}:
        message = message.replace(form, '***')
    return message


def check(parameter_name, profile=None, region=environments.REGION):
    """検証して結果を表示し、認証が通ったかを返す。"""
    uri = get_parameter(profile, region, parameter_name)
    info = describe_uri(uri)

    print(parameter_name)
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
    return ok


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument('--env', choices=sorted(environments.ENVIRONMENTS),
                        help='環境名。パラメータ名は environments.py から引く')
    target.add_argument('--parameter-name',
                        help='SSMパラメータ名。例: /asobann/prod/mongodb_uri')
    parser.add_argument('--profile',
                        help='AWSプロファイル。省略時は既定の認証情報チェーン'
                             '（手元では environments.py が AWS_PROFILE を与える）')
    parser.add_argument('--region', default=environments.REGION, help='AWSリージョン')
    args = parser.parse_args()

    name = (args.parameter_name if args.parameter_name
            else environments.get(args.env)['mongodb_uri_parameter_name'])
    return 0 if check(name, args.profile, args.region) else 1


if __name__ == '__main__':
    sys.exit(main())
