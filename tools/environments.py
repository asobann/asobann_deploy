"""staging / 本番の定義。デプロイまわりのスクリプトはここを唯一の正とする。

AWSアカウントIDは書かない。実行時に sts get-caller-identity で取る。
理由が2つある。

1. このリポジトリはpublicなので、アカウント固有の識別子を置きたくない
2. **間違ったアカウントに向いていたら気づける。** 定数で持つと、プロファイルの
   設定ミスとアカウントIDの不整合が黙って通る。2026-08にアカウントを
   550251267268 から 744617283020 へ移した際、同じ値が複数箇所にあって
   片方を直し忘れる危険が実際にあった

証明書も同じ理由でARNではなくIDだけを持ち、ARNは実行時に組み立てる。
証明書ID単体ではアカウントを特定できない。
"""

import functools
import subprocess

REGION = 'us-east-1'
REPO = 'asobann_aws'

# AWS_PROFILE の既定値は入れない。手元では毎回 AWS_PROFILE を明示する
# （参照は asobann-readonly、デプロイなどの変更は asobann-admin）。
# 手元の設定には [default] を置いていないので、指定し忘れると認証情報が
# 見つからずに止まる。

# デプロイ毎に人間が思い出して打つのをやめ、環境ごとの固定値をコードに置く。
# 変更履歴はgit logで追える。2026-08-11、GoogleAnalyticsIdをうっかり空のまま
# デプロイし続けていたことに気づいたのがきっかけ。
ENVIRONMENTS = {
    'staging': {
        'stack_name': 'asobann-staging',
        'public_hostname': 'staging.asobann.yattom.jp',
        'mongodb_uri_parameter_name': '/asobann/staging/mongodb_uri',
        # 較正用のstagingにはGAタグを出さない(本番の計測を汚さない)。
        'google_analytics_id': '',
        'certificate_id': '0767b27e-9973-433c-8a75-11415fd6bc61',
        # 2026-08-20、負荷試験の結果CPU512を採用（ADR 0015）。24人程度までなら
        # p95 1.7秒・ロス率0.8%で安定し、$18/月。CPU1024は倍のコストで買える余裕が
        # 現状の利用実態に見合わないと判断した。メモリ1024はFargateの組み合わせ制約
        # （512 CPUには最低1024MBが必要）によるもので、メモリ不足が理由ではない。
        'task_cpu': '512',
        'task_memory': '1024',
        'app_task_count': '1',
    },
    'prod': {
        'stack_name': 'asobann-fargate',
        'public_hostname': 'asobann.yattom.jp',
        'mongodb_uri_parameter_name': '/asobann/prod/mongodb_uri',
        # GA4測定ID。旧EC2版が使っていたUA-176419428-1(Universal Analytics)は
        # 2023年にGoogleが計測を終了済み。Fargate移行で引き継がれず空になっていたのを
        # 2026-08-11に発見し、GA4プロパティ(analytics.google.com)から取得し直した。
        'google_analytics_id': 'G-GRZ5YJ1JCF',
        'certificate_id': '0767b27e-9973-433c-8a75-11415fd6bc61',
        # 2026-08-20、負荷試験の結果CPU512を採用（ADR 0015）。詳細はstaging側のコメント参照。
        'task_cpu': '512',
        'task_memory': '1024',
        'app_task_count': '1',
    },
}


def get(env):
    if env not in ENVIRONMENTS:
        raise SystemExit(f'envは {" / ".join(ENVIRONMENTS)} のいずれか: {env}')
    return ENVIRONMENTS[env]


@functools.cache
def account_id():
    """いま使っている認証情報のAWSアカウントIDを取る。"""
    return subprocess.run(
        ['aws', 'sts', 'get-caller-identity', '--query', 'Account', '--output', 'text'],
        capture_output=True, text=True, check=True).stdout.strip()


def registry():
    return f'{account_id()}.dkr.ecr.{REGION}.amazonaws.com'


def image_uri(image_tag):
    return f'{registry()}/{REPO}:{image_tag}'


def certificate_arn(env):
    return f'arn:aws:acm:{REGION}:{account_id()}:certificate/{get(env)["certificate_id"]}'


def image_exists_in_ecr(image_tag):
    """そのタグのイメージがECRにあるか。"""
    return subprocess.run(
        ['aws', 'ecr', 'describe-images', '--repository-name', REPO,
         '--image-ids', f'imageTag={image_tag}', '--region', REGION],
        capture_output=True).returncode == 0
