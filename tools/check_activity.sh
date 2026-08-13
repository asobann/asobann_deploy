#!/usr/bin/env bash
#
# 直近N分間に利用者の操作があったかを調べる。カットオーバー等でサービスを
# 停止する前に、誰かが遊んでいる最中でないかを確認するために使う。
#
# ALBの RequestCount は使えない。公開エンドポイントにはbotやスキャナが
# 常時アクセスしており（実測で4〜11件/5分）、利用者がゼロでも非ゼロになる。
#
# 代わりにアプリのログを見る。利用者の操作はすべてINFOで記録される。
#
# 使い方:
#   ./check_activity.sh [分数]      # 既定 30
#
# 終了コード:
#   0 = 操作の形跡なし（停止してよい）
#   1 = 操作あり（誰かが使っている可能性）
#
# 限界: テーブルを開いたまま何も操作していない人は検出できない。
#       ログに残るのは操作のみのため。

set -euo pipefail

LOG_GROUP=${LOG_GROUP:-/ecs/asobann-prod-Service-1UDE7ZTVIX7SG}
MINUTES=${1:-30}

# ?"..." はOR条件。利用者の操作としてログに現れるものを列挙する。
# mouse movement はログに出ないため対象外。
# update single component / remove component / remove kit はクライアントが
# 送らない死んだイベントなので対象から外している（asobann_docs
# worklogs/20260813.update-path-review.WIP）。
pattern='?"come by table" ?"set player" ?"update many component" ?"add component" ?"add kit" ?"sync with me"'

# 問い合わせは1回にまとめる。判定用と「直近の操作はいつか」用に別々に叩くと、
# filter-log-events が該当0件のページを返すことがあり、同じ条件なのに
# 食い違った答えが出る。24時間ぶん取ってきて、スクリプト側で切り分ける。
LOOKBACK_HOURS=${LOOKBACK_HOURS:-24}
now=$(date +%s)
threshold_ms=$(( (now - MINUTES * 60) * 1000 ))

echo "==> 直近 ${MINUTES} 分の利用者操作を調べる"
echo "    ロググループ: $LOG_GROUP"

events=$(aws logs filter-log-events --log-group-name "$LOG_GROUP" \
  --start-time $(( (now - LOOKBACK_HOURS * 3600) * 1000 )) --filter-pattern "$pattern" \
  --query 'events[].[timestamp,message]' --output text)

recent=$(printf '%s\n' "$events" | awk -v t="$threshold_ms" 'NF && $1 >= t')
count=$(printf '%s' "$recent" | grep -c . || true)

if [ "${count:-0}" -eq 0 ]; then
  echo "    操作なし"
else
  echo "    操作 ${count} 件を検出"
  printf '%s\n' "$recent" | tail -5 | while read -r ts msg; do
    echo "      $(date -d "@$(( ts / 1000 ))" '+%H:%M:%S')  ${msg}"
  done
fi

# 同じ結果から最後の操作時刻を取る
last=$(printf '%s\n' "$events" | awk 'NF {print $1}' | sort -n | tail -1)
if [[ "$last" =~ ^[0-9]+$ ]]; then
  last_sec=$(( last / 1000 ))
  echo "    直近の操作: $(date -d "@${last_sec}" '+%Y-%m-%d %H:%M:%S')（$(( (now - last_sec) / 60 ))分前）"
else
  echo "    直近${LOOKBACK_HOURS}時間に操作なし"
fi

if [ "${count:-0}" -eq 0 ]; then
  echo "==> 停止してよい"
  exit 0
fi
echo "==> 誰かが使っている可能性がある。時間をおいて再確認すること" >&2
exit 1
