#!/usr/bin/env python3
"""asobann-staging スタックと ImageBucket を削除する（#180 フェーズ3）。

staging専用。本番スタックを削除する用途は無い。

ImageBucket には DeletionPolicy: Retain が付いているため、delete-stack は
バケットを残したまま完了する。往復するたびに孤児バケットが増えないよう、
ここでバケット名を（スタック削除前に、Outputsから）取得しておき、
スタック削除後に明示的に空にして削除する。

stagingのアップロード画像は捨ててよいデータという前提（#180）。

破壊的操作のため、既定はdry-run（何を消すかを表示するだけで、何も消さない）。
実際に削除するには --execute を付けること。

使い方:
    uv run python tools/teardown.py            # dry-run。何も削除しない
    uv run python tools/teardown.py --execute  # 実際に削除する
"""

import argparse
import subprocess
import sys

import environments

ENV = 'staging'


def get_image_bucket_name(stack_name):
    result = subprocess.run(
        ['aws', 'cloudformation', 'describe-stacks',
         '--stack-name', stack_name, '--region', environments.REGION,
         '--query', "Stacks[0].Outputs[?OutputKey=='ImageBucketName'].OutputValue",
         '--output', 'text'],
        capture_output=True, text=True, check=True)
    name = result.stdout.strip()
    if not name:
        raise SystemExit(f'{stack_name} から ImageBucketName が取れない。'
                          f'スタックが存在しないか、Output名が変わっていないか確認すること。')
    return name


def run(cmd, **kwargs):
    print(f'$ {" ".join(cmd)}')
    return subprocess.run(cmd, check=True, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--execute', action='store_true',
                         help='実際に削除する。指定しなければdry-run（何も削除しない）')
    args = parser.parse_args()

    stack_name = environments.get(ENV)['stack_name']

    print(f'=== {stack_name} を削除する ===')

    # スタックを消すとOutputsごと引けなくなるため、バケット名は先に取っておく。
    bucket = get_image_bucket_name(stack_name)
    print(f'ImageBucket: {bucket}（スタック削除後にこれも消す）')

    if not args.execute:
        print()
        print('dry-run: 何も削除していない。実際に削除するには --execute を付けること。')
        return 0

    run(['aws', 'cloudformation', 'delete-stack',
         '--stack-name', stack_name, '--region', environments.REGION])

    print('スタック削除の完了を待つ...')
    run(['aws', 'cloudformation', 'wait', 'stack-delete-complete',
         '--stack-name', stack_name, '--region', environments.REGION])
    print(f'{stack_name} を削除した')

    run(['aws', 's3', 'rm', f's3://{bucket}', '--recursive'])
    run(['aws', 's3', 'rb', f's3://{bucket}'])
    print(f'{bucket} を削除した')

    return 0


if __name__ == '__main__':
    sys.exit(main())
