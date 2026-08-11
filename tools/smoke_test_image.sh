#!/usr/bin/env bash
#
# ビルドしたイメージがローカルで起動し、応答することを確認する（ADR 0009の手順③）。
#
# 使い捨てのmongoを立て、本番と同じ FLASK_ENV=production で起動する。
# 本番のAtlasには接続しない。画像の保存先も local にしてAWS認証情報を要らなくする。
#
# 確認しているのは「起動してDBに繋がり、ページと静的ファイルを返せる」ところまで。
# 同期（WebSocket）や実データでの動作は見ていないので、stagingでの確認は別途必要。
#
# 前提: docker
#
# 使い方:
#   ./smoke_test_image.sh <image>
#   ./smoke_test_image.sh 744617283020.dkr.ecr.us-east-1.amazonaws.com/asobann_aws:31ed4ac
#
# 終了コード: 0 = 応答した / 1 = 失敗（失敗時はコンテナのログを表示する）

set -euo pipefail

IMAGE=${1:?イメージを指定すること}
PORT=${PORT:-15000}
NETWORK=asobann-smoke
MONGO_IMAGE=${MONGO_IMAGE:-mongo:5}

# 途中で失敗しても使い捨てのコンテナとネットワークを残さない。
cleanup() {
    docker rm -f smoke-app smoke-mongo >/dev/null 2>&1 || true
    docker network rm "$NETWORK" >/dev/null 2>&1 || true
}
trap cleanup EXIT

cleanup

echo "==> 使い捨てのmongoを立てる"

docker network create "$NETWORK" >/dev/null
docker run -d --name smoke-mongo --network "$NETWORK" "$MONGO_IMAGE" >/dev/null

echo "==> イメージを起動する"

# タスク定義と同じくキット初期化を飛ばす（ADR 0007）。イメージのCMDのままだと
# asobann.deploy が走り、DBのキットを上書きしてしまう。
docker run -d --name smoke-app --network "$NETWORK" -p "$PORT:5000" \
  -e FLASK_ENV=production \
  -e MONGODB_URI=mongodb://smoke-mongo:27017/asobann_smoke \
  -e PUBLIC_HOSTNAME=localhost \
  -e GOOGLE_ANALYTICS_ID= \
  -e UPLOADED_IMAGE_STORE=local \
  "$IMAGE" python3 -m asobann.asgi >/dev/null

echo "==> 応答を確かめる"

fail() { echo "$1" >&2; echo "--- コンテナのログ" >&2; docker logs smoke-app >&2 2>&1; exit 1; }

# 起動を待つ。mongoの起動待ちも含めてリトライで吸収する。
#
# --retry-all-errors が要る。dockerはコンテナ起動と同時にホストのポートをbindするため、
# アプリがlistenする前の接続は「接続拒否」ではなく接続リセットになる。
# --retry-connrefused だけでは再試行されず、即座に 000 で諦めてしまう。
code=$(curl -s --retry 15 --retry-delay 2 --retry-all-errors --retry-connrefused \
  -o /dev/null -w '%{http_code}' "http://localhost:$PORT/" || true)
[ "$code" = "302" ] || fail "GET / が 302 でない: $code"
echo "GET /              -> 302"

# / は新しいテーブルへのリダイレクト。追いかけてテーブルのページが出るまで見る。
code=$(curl -s -L -o /dev/null -w '%{http_code}' "http://localhost:$PORT/")
[ "$code" = "200" ] || fail "テーブルのページが 200 でない: $code"
echo "GET /tables/xxx    -> 200"

# webpackの成果物がイメージに入っているか。ビルド順序を間違えると落ちる。
# -w の書式に改行が要る。無いと read がEOFで非ゼロを返し、set -e で静かに落ちる。
read -r code size < <(curl -s -o /dev/null -w '%{http_code} %{size_download}\n' \
  "http://localhost:$PORT/static/main.js")
[ "$code" = "200" ] || fail "main.js が 200 でない: $code"
[ "$size" -gt 100000 ] || fail "main.js が小さすぎる: $size bytes"
echo "GET /static/main.js -> 200 ($size bytes)"

docker logs smoke-app 2>&1 | grep -q "connected to mongo" || fail "mongoに接続できていない"
echo "mongo接続           -> OK"

echo
echo "==> 起動確認OK: $IMAGE"
