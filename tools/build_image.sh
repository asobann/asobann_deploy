#!/usr/bin/env bash
#
# asobann_app のイメージをビルドし、ECRにpushする。
#
# タグにはgitのコミットSHAを使う。`latest` や `production` のような可変タグは
# デプロイ対象の指定に使わない。同じタグが別の中身を指しうるため、
# 「本番で動いているのはどのイメージか」が曖昧になる（ADR 0002でわざわざ
# digestを記録する羽目になったのはこれが理由）。
#
# ビルドは1回だけ行い、同じdigestを staging → 本番 と昇格させる（ADR 0009）。
# 本番用に作り直したイメージは、stagingで確認したものとは別物になる。
#
# 前提: docker, aws cli, node（npx webpack）, uv
#
# 使い方:
#   ./build_image.sh            # ビルドのみ
#   ./build_image.sh --push     # ビルドしてECRにpush
#
# 出力の最後にimage URIとdigestを表示する。staging/本番のデプロイでは
# これをそのまま AppImage パラメータに渡す。

set -euo pipefail

# CIではプロファイルではなくロールを使う。AWS_PROFILE= と明示的に空を渡した場合は
# それを尊重したいので、:- ではなく - を使う（:- は空文字も「未設定」とみなす）。
export AWS_PROFILE=${AWS_PROFILE-asobann}

ACCOUNT=${ACCOUNT:-744617283020}
REGION=${REGION:-us-east-1}
REPO=${REPO:-asobann_aws}

REGISTRY="$ACCOUNT.dkr.ecr.$REGION.amazonaws.com"
APP_DIR=$(cd "$(dirname "$0")/../../asobann_app" && pwd)

PUSH=no
[ "${1:-}" = "--push" ] && PUSH=yes

echo "==> バージョンを決める"

cd "$APP_DIR"
sha=$(git rev-parse --short HEAD)
if [ -n "$(git status --porcelain)" ]; then
    # 未コミットの変更を含むイメージは再現できない。手元での確認には使えるが、
    # 本番に昇格させてはいけないので、タグで見分けられるようにする。
    sha="$sha-dirty"
    echo "警告: 未コミットの変更がある。このイメージを本番に出さないこと" >&2
fi
TAG="$REGISTRY/$REPO:$sha"
echo "$TAG"

echo "==> 依存を書き出す"

# Dockerfile.aws は requirements.txt を COPY する。uv.lock が正で、
# requirements.txt はその都度生成する中間物（gitignore済み）。
uv export --frozen --no-dev --no-emit-project --no-hashes -o requirements.txt --quiet
echo "$(grep -cE '^[a-zA-Z0-9]' requirements.txt) パッケージ"

echo "==> フロントエンドをビルドする"

# webpackの出力先は src/asobann/app/static/ で、これを Dockerfile.aws が
# src ごと COPY する。つまりビルド順序に依存がある（webpack → docker build）。
#
# node_modules があっても必ず npm ci する。ここを「無ければ入れる」にすると、
# 手元に残った別ブランチのnode_modulesでビルドしてしまう。実際に2026-08-09時点で
# 手元にはslowness_issueブランチのもの（webpack 5.93 / socket.io-client 4.7.5）が
# 残っており、masterのlock（5.72.1 / 4.5.1）と食い違っていた。
# npm ci は node_modules を捨ててlockどおりに入れ直す。
npm ci
npx webpack

echo "==> イメージをビルドする"

docker build -f Dockerfile.aws -t "$TAG" .

if [ "$PUSH" != "yes" ]; then
    echo
    echo "==> ビルド完了（pushしていない）"
    echo "image: $TAG"
    echo "pushするには: $0 --push"
    exit 0
fi

echo "==> ECRにpushする"

aws ecr get-login-password --region "$REGION" \
  | docker login --username AWS --password-stdin "$REGISTRY"
docker push "$TAG"

digest=$(aws ecr describe-images --repository-name "$REPO" --image-ids imageTag="$sha" \
  --query 'imageDetails[0].imageDigest' --output text)

echo
echo "==> push完了"
echo "image : $TAG"
echo "digest: $digest"
