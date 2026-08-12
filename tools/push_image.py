#!/usr/bin/env python3
"""ビルド済みのローカルイメージをECRへpushする。

ビルドは asobann_app/scripts/build_image.sh が行う。分けてあるのは、ビルドが
asobann_app の資産だけで完結し認証情報を要らないのに対し、pushはECR＝この
リポジトリが面倒を見る領域で認証情報が要るため。

レジストリURIの組み立ては environments.py が唯一の正。ここでは持たない。

使い方:
    uv run python tools/push_image.py asobann_aws:31ed4ac

出力の最後に image URI と digest を表示する。デプロイにはこのタグを渡す。
"""

import argparse
import subprocess
import sys

import environments


def run(cmd, **kwargs):
    print(f'$ {" ".join(cmd)}')
    return subprocess.run(cmd, check=True, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('image', help='ローカルのイメージ参照。例: asobann_aws:31ed4ac')
    args = parser.parse_args()

    if ':' not in args.image:
        raise SystemExit(f'タグを含めて指定すること: {args.image}')
    tag = args.image.rsplit(':', 1)[1]

    if tag.endswith('-dirty'):
        # 未コミットの変更を含むイメージは再現できない。手元での確認には使えるが、
        # ECRに上げると「本番で動いているのはどのコミットか」が辿れなくなる。
        raise SystemExit(f'-dirty のイメージはpushしない: {args.image}')

    uri = environments.image_uri(tag)
    print(f'==> {args.image} を {uri} としてpushする')

    password = subprocess.run(
        ['aws', 'ecr', 'get-login-password', '--region', environments.REGION],
        capture_output=True, text=True, check=True).stdout
    run(['docker', 'login', '--username', 'AWS', '--password-stdin',
         environments.registry()], input=password, text=True)

    run(['docker', 'tag', args.image, uri])
    run(['docker', 'push', uri])

    digest = subprocess.run(
        ['aws', 'ecr', 'describe-images', '--repository-name', environments.REPO,
         '--image-ids', f'imageTag={tag}', '--region', environments.REGION,
         '--query', 'imageDetails[0].imageDigest', '--output', 'text'],
        capture_output=True, text=True, check=True).stdout.strip()

    print()
    print('==> push完了')
    print(f'image : {uri}')
    print(f'digest: {digest}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
