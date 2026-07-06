# AWS構成（asobann_deploy）

最終更新: 2026-07-06（リポジトリのテンプレートから文書化。実環境は未確認）

## スタック構成

`aws/asobann_aws.yaml` が親スタックで、以下のネストスタックを組み立てる:

```
asobann_aws.yaml
├── templates/vpc.yaml            … VPC・サブネット
├── templates/load-balancer.yaml  … ALB(80/443) + TargetGroup(sticky有効) + Route53レコード + ACM証明書利用
├── templates/cluster.yaml        … ECSクラスタ + AutoScalingGroup(EC2) + SecurityGroup + IAMロール
├── templates/s3-bucket.yaml      … アップロード画像用S3バケット
└── templates/service.yaml
    ├── service/app.yaml          … アプリ(ECSサービス, port 5000, bridge)
    ├── service/mongodb.yaml      … MongoDB(ECSサービス, EBS永続化, SRVサービスディスカバリ)
    └── service/redis.yaml        … Redis(ECSサービス, SRVサービスディスカバリ)
```

- 起動タイプはEC2（インスタンスタイプはパラメータ、既定 t3.small）
- Mongo/Redisは内部ネームスペース（例: `_mongodb._tcp.mongodb.asobann-internal.yattom.jp`）のSRVレコードで発見される。アプリ側は `mongodb+srv://` / `redis+srv://` を解決する
- MongoDBのデータは rexray/ebs ドライバのDockerボリューム（gp2, 10GB, `mongodb-data-<env>`）で永続化
- アプリイメージは asobann_app/Dockerfile.aws でビルドし、ECRへpush（`tools/build_image.py`。アカウントID等ハードコードあり）

## 主要パラメータ（親スタック）

| パラメータ | 説明 |
|---|---|
| `PublicHostname` | 公開ホスト名（Route53に登録済みドメイン必須） |
| `CertificateArn` | HTTPS用ACM証明書 |
| `MaintenanceIpRange` | SSH(22)を許可するCIDR |
| `MongoDbPassword` | Mongo adminパスワード（**NoEcho未設定・平文で環境変数へ展開される**） |
| `AppImage` / `AppTaskFamily` / `AppTaskCount` | アプリのECRイメージとタスク数（既定3） |
| `UploadedImageStore` | `s3` or `local` |
| `AwsKey` / `AwsSecret` | アプリがS3へアクセスするIAMユーザー認証情報（タスクロール未使用） |
| `AwsCognitoUserPoolId` / `AwsCognitoClientId` | Cognito（認証機能は未完成） |
| `FlaskEnv` | `development` / `production` |
| `DebugOpts` | ASOBANN_DEBUG_OPTSへ |

## デプロイの流れ（概要）

1. asobann_appでイメージビルド（`npx webpack` → `pipenv requirements > requirements.txt` → `docker build -f Dockerfile.aws`）→ ECRへpush
2. `aws cloudformation package` でテンプレートをS3へ → `aws cloudformation deploy`
3. アプリコンテナはCMDで `asobann.deploy`（キット初期データ投入）→ `asobann.wsgi` を実行

READMEに詳細手順があるが、`cd aws_dev` は現在の `aws/` ディレクトリの旧名なので読み替えること。

## 既知の問題（2026-07時点、要対応）

詳細は devenv の issues.20260706.md §7。

1. **LaunchConfigurationはAWSが新規作成を停止済み** — Launch Templateへの書き換えが必要。現状のままでは再デプロイできない可能性が高い
2. **AMIが古い固定値**（`ami-007cd1678c6286a05`、2020年ごろのECS optimized）— SSMパラメータ参照へ
3. **mongo:latest / redis:latest** — 再デプロイでメジャーバージョンが飛ぶと既存EBSデータでmongodが起動しなくなる。バージョン固定必須
4. **rexray/ebs は開発終了** — ECSネイティブEBS/EFS/マネージドDBへの移行を検討
5. **S3が `public-read` オブジェクトACL前提** — 2023年以降の新規バケットではACL無効が既定でアップロードが失敗する
6. `app.yaml` のEnvironmentに `NAME:`（大文字）キーが混在 — `Name:` が正。該当環境変数が渡っていない可能性
7. Route53のHostedZone名 `asobann.yattom.jp.` とCanonicalHostedZoneIdがテンプレートにハードコード
8. シークレット（MongoDbPassword, AwsSecret）が平文パラメータ — Secrets Manager / SSM SecureString化を推奨
9. バックアップの仕組みなし（MongoDBは単一コンテナ+単一EBS）
