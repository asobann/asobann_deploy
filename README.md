[asobann](https://github.com/asobann/asobann_app) を AWS へ CloudFormation でデプロイする。

現行構成は **ECS on Fargate**（`aws/fargate.yaml`）。データストアは MongoDB Atlas。
構成の詳細は [docs/aws-architecture.md](docs/aws-architecture.md) と、
asobann_app 側の ADR（`docs/adr/`）を参照。

`aws/asobann_aws.yaml` と `aws/templates/` は移行前の ECS on EC2 構成。旧スタックの
削除が済むまで残してあるだけで、**新規のデプロイには使わない**。

## 前提

- Python >= 3.12 と [uv](https://docs.astral.sh/uv/)。このリポジトリのツール用に `uv sync` を実行しておく
- AWS CLI（プロファイル `asobann`）
- docker
- asobann_app をチェックアウト済み（イメージのビルドはあちら側で行う）

## デプロイ手順

ビルドしたイメージを1つだけ作り、同じものを staging → 本番と昇格させる（ADR 0009）。
本番用に作り直したイメージは、stagingで確認したものとは別物になる。

```shell
# ① イメージをビルドする（asobann_app 側。AWSには触らない）
cd /path/to/asobann_app
./scripts/build_image.sh
#    → asobann_aws:<short-sha> ができる。タグだけ知りたいときは --print-tag

# ② ローカルで起動確認する
cd /path/to/asobann_deploy
./tools/smoke_test_image.sh asobann_aws:<short-sha>

# ③ ECRへpushする
uv run python tools/push_image.py asobann_aws:<short-sha>

# ④ stagingへデプロイして確認する
uv run python tools/deploy.py --env staging --image-tag <short-sha>

# ⑤ 同じタグを本番へ
uv run python tools/deploy.py --env prod --image-tag <short-sha>
```

ワークスペース（devenv）からは `inv build --push` / `inv smoke-test` /
`inv deploy --env=staging` で同じことができる。複数リポジトリを跨ぐので、入口を
1つにまとめてあるだけで、中身は上のスクリプト。

環境を変えずにパラメータとテンプレートの妥当性だけ確かめたいときは
`--no-execute-changeset` を付ける（changesetを作るだけで実行しない）。

## ツール

| | 役割 |
|---|---|
| `tools/environments.py` | staging / 本番の定義。**スタック名・ホスト名・CPU/メモリ・証明書ID・SSMパラメータ名の唯一の正** |
| `tools/deploy.py` | CloudFormationスタックの更新。デプロイ前にMongoDB接続を検証する |
| `tools/push_image.py` | ビルド済みイメージをECRへpush |
| `tools/check_mongodb_uri.py` | SSMの接続文字列を検証する。値は表示せず、構造と認証可否だけ出す |
| `tools/smoke_test_image.sh` | イメージがローカルで起動し応答するか確認する |
| `tools/dump_mongodb.sh` | 本番MongoDBのダンプ取得 |
| `tools/rewrite_image_urls.js` | テーブルデータに埋め込まれた画像URLのバケット名を書き換える |

**AWSアカウントIDはリポジトリに書かない。** 実行時に `aws sts get-caller-identity` で
取る。publicリポジトリだからというだけでなく、定数で持つとプロファイルの設定ミスが
黙って通るため。証明書もARNではなくIDだけを持ち、ARNは実行時に組み立てる。

MongoDBの接続文字列は SSM Parameter Store の SecureString に置き、どこにも平文で
持たない（ADR 0006）。

## 制約

- テーブルのデータはデプロイ・スタック更新・タスク再起動をまたいで保持される
- アップロード画像用の S3 バケットが作られる
- Route53 上のドメインと ACM 証明書が事前に必要
- AWS無料枠には収まらない
