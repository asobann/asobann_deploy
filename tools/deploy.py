#!/usr/bin/env python3
"""CloudFormationスタックを更新して、指定したイメージをデプロイする（ADR 0009 手順④）。

パラメータは environments.py に固定してあり、都度手打ちしない。変更はそこを
コミットして行う。ECRに対象タグが無いと失敗するので、先に
asobann_app/scripts/build_image.sh でビルドし tools/push_image.py で上げておくこと。

デプロイ前にMongoDBの接続文字列を必ず検証する。壊れた値のままタスクを入れ替えると、
MinimumHealthyPercent: 0 のため復帰先が無くなり本番が停止する
（2026-08-09に13分停止した）。

使い方:
    uv run python tools/deploy.py --env staging --image-tag 31ed4ac
    uv run python tools/deploy.py --env prod --image-tag 31ed4ac
    uv run python tools/deploy.py --env staging --image-tag 31ed4ac --no-execute-changeset
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

import check_mongodb_uri
import environments

TEMPLATE = Path(__file__).resolve().parent.parent / 'aws' / 'fargate.yaml'


def build_command(env, image_tag, no_execute_changeset=False):
    p = environments.get(env)
    overrides = [
        f'PublicHostname={p["public_hostname"]}',
        f'TaskCpu={p["task_cpu"]}',
        f'TaskMemory={p["task_memory"]}',
        f'MongoDbUriParameterName={p["mongodb_uri_parameter_name"]}',
        f'AppImage={environments.image_uri(image_tag)}',
        f'AppTaskCount={p["app_task_count"]}',
        f'CertificateArn={environments.certificate_arn(env)}',
        f'GoogleAnalyticsId={p["google_analytics_id"]}',
        # 既定は0（ADR 0004: 1タスクならRedis不要）。R5(水平スケーリング実測)でのみ
        # environments.pyのenv dictにredis_task_*キーを足して1にする
        f'RedisTaskCount={p.get("redis_task_count", 0)}',
        f'RedisTaskCpu={p.get("redis_task_cpu", 256)}',
        f'RedisTaskMemory={p.get("redis_task_memory", 512)}',
    ]
    cmd = [
        'aws', 'cloudformation', 'deploy',
        # リージョンは明示する。呼び出し元の既定設定に任せると、プロファイルの
        # region 設定次第で意図しないリージョンのスタックを触りうる。
        '--region', environments.REGION,
        '--template-file', str(TEMPLATE),
        '--stack-name', p['stack_name'],
        '--parameter-overrides', *overrides,
        '--capabilities', 'CAPABILITY_IAM',
    ]
    if no_execute_changeset:
        # 実行せずchangesetを作るだけ。パラメータとテンプレートの妥当性を、
        # 環境を変えずに確かめられる。
        cmd.append('--no-execute-changeset')
    return cmd


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--env', required=True, choices=sorted(environments.ENVIRONMENTS))
    parser.add_argument('--image-tag', required=True,
                        help='デプロイするイメージのタグ。'
                             'asobann_app/scripts/build_image.sh --print-tag で得られる')
    parser.add_argument('--skip-mongodb-check', action='store_true',
                        help='MongoDB接続チェックを飛ばす（通常は使わない）')
    parser.add_argument('--no-execute-changeset', action='store_true',
                        help='changesetを作るだけで実行しない（動作確認用）')
    args = parser.parse_args()

    p = environments.get(args.env)

    # デプロイ前にECRにイメージがあることを確かめる。CloudFormationの更新は
    # イメージが無くても成功し、タスクがpullする段で初めて落ちる。そのとき
    # MinimumHealthyPercent: 0 のため古いタスクは既に止まっており、復帰先が無い。
    #
    # アカウントIDを実行時に取るようにした結果、プロファイルの取り違えは
    # 「別アカウントのレジストリを見る」形で現れる。そのアカウントには
    # このタグが無いので、このチェックがそこでも効く。
    if not environments.image_exists_in_ecr(args.image_tag):
        print(f'ECRに {environments.image_uri(args.image_tag)} が無い。', file=sys.stderr)
        print(f'先に asobann_deploy で '
              f'`uv run python tools/push_image.py '
              f'{environments.REPO}:{args.image_tag}` を実行すること。'
              f'（アカウントは {environments.account_id()} / '
              f'AWS_PROFILE={os.environ.get("AWS_PROFILE", "(未設定)")}）', file=sys.stderr)
        return 1

    if not args.skip_mongodb_check:
        if not check_mongodb_uri.check(p['mongodb_uri_parameter_name']):
            return 1

    uri = environments.image_uri(args.image_tag)
    print(f'=== {args.env} へデプロイ: {uri} ===')
    cmd = build_command(args.env, args.image_tag, args.no_execute_changeset)
    print(f'$ {" ".join(cmd)}')
    result = subprocess.run(cmd)
    if result.returncode != 0:
        return result.returncode

    print(f'デプロイ完了: {p["stack_name"]} / {uri}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
