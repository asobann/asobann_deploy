#!/usr/bin/env bash
#
# 本番MongoDBのダンプを取得する。
#
# 本番EC2にはシェルで入れない（SSH秘密鍵を紛失、EC2 Instance ConnectとSSMは
# ECS-optimized AMIにエージェントが無く利用不可）。そのため、mongoコンテナが
# バインドされているEC2ホストの動的ポートに対して、実行元のIPからだけ一時的に
# セキュリティグループを開け、mongodumpし、終了時に必ず閉じる。
#
# 前提: aws cli（本番スタックを読める権限）、docker
#       ローカルにmongodumpは不要（コンテナで実行する）
#
# 使い方:
#   ./dump_mongodb.sh [出力ディレクトリ]
#
# 取得したダンプの検証:
#   docker run -d --name mongo-verify -p 27018:27017 mongo:5
#   docker run --rm --network host -v "$PWD:/in" mongo:5 \
#     mongorestore --host localhost:27018 --archive=/in/<file> --gzip --nsInclude 'asobann_dev.*'
#   docker rm -f mongo-verify

set -euo pipefail

STACK=${STACK:-asobann-prod}
CLUSTER=${CLUSTER:-asobann-prod-Cluster-7YBO3O7SWITB}
TASK_FAMILY=${TASK_FAMILY:-mongodb}
MONGO_IMAGE=${MONGO_IMAGE:-mongo:5}
MONGO_USER=${MONGO_USER:-admin}
OUTDIR=${1:-$(pwd)}

ARCHIVE="$OUTDIR/asobann-$(date +%Y%m%d-%H%M%S).gz"

# 出力先の準備はセキュリティグループを開ける前に済ませる。書けないディレクトリを
# 指定していた場合に、穴を開けてから失敗するのを避けるため。
mkdir -p "$OUTDIR"

echo "==> 対象を特定する"

# mongoタスクのhostPortは動的割り当てのため、タスク再起動のたびに変わる。毎回引き直す。
task_arn=$(aws ecs list-tasks --cluster "$CLUSTER" --family "$TASK_FAMILY" \
  --desired-status RUNNING --query 'taskArns[0]' --output text)
[ "$task_arn" = "None" ] && { echo "mongoタスクが見つからない" >&2; exit 1; }

host_port=$(aws ecs describe-tasks --cluster "$CLUSTER" --tasks "$task_arn" \
  --query 'tasks[0].containers[0].networkBindings[0].hostPort' --output text)

container_arn=$(aws ecs describe-tasks --cluster "$CLUSTER" --tasks "$task_arn" \
  --query 'tasks[0].containerInstanceArn' --output text)
instance_id=$(aws ecs describe-container-instances --cluster "$CLUSTER" \
  --container-instances "$container_arn" --query 'containerInstances[0].ec2InstanceId' --output text)

read -r public_ip sg_ids <<<"$(aws ec2 describe-instances --instance-ids "$instance_id" \
  --query 'Reservations[0].Instances[0].[PublicIpAddress, join(`,`, SecurityGroups[].GroupId)]' \
  --output text)"

# SGが複数あるとどれを開ければよいか一意に決まらないので、その場合は手動対応にする
case "$sg_ids" in
  '' | None) echo "セキュリティグループを特定できなかった" >&2; exit 1 ;;
  *,*)       echo "セキュリティグループが複数ある($sg_ids)。手動で確認すること" >&2; exit 1 ;;
esac

# パブリックIPが無いインスタンスには手元から到達できない。ここで止めないと
# mongodumpが分かりにくい接続エラーで落ちる。
case "$public_ip" in
  '' | None) echo "インスタンスにパブリックIPが無いため到達できない" >&2; exit 1 ;;
esac

my_ip=$(curl -s --max-time 10 https://checkip.amazonaws.com)
[ -n "$my_ip" ] || { echo "自分のグローバルIPを取得できなかった" >&2; exit 1; }

echo "    instance : $instance_id ($public_ip)"
echo "    hostPort : $host_port"
echo "    SG       : $sg_ids"
echo "    自分のIP : $my_ip"

# 開けたルールは何があっても閉じる。
# authorizeが失敗した場合まで「削除に失敗した」と警告すると、開いていないのに
# 手動確認を促すことになるので、開けたときだけ閉じる。
opened=no
revoke() {
  [ "$opened" = yes ] || return 0
  echo "==> セキュリティグループのルールを削除する"
  if aws ec2 revoke-security-group-ingress --group-id "$sg_ids" \
       --ip-permissions "IpProtocol=tcp,FromPort=${host_port},ToPort=${host_port},IpRanges=[{CidrIp=${my_ip}/32}]" \
       >/dev/null 2>&1; then
    echo "    削除した"
  else
    echo "    削除に失敗した。手動で確認すること: aws ec2 describe-security-groups --group-ids $sg_ids" >&2
  fi
}
trap revoke EXIT

echo "==> tcp/${host_port} を ${my_ip}/32 にだけ開ける"
aws ec2 authorize-security-group-ingress --group-id "$sg_ids" \
  --ip-permissions "IpProtocol=tcp,FromPort=${host_port},ToPort=${host_port},IpRanges=[{CidrIp=${my_ip}/32,Description='temporary mongodump access'}]" \
  --query 'SecurityGroupRules[].SecurityGroupRuleId' --output text
opened=yes

# パスワードはCloudFormationのパラメータに平文で入っている（NoEcho未設定）。
# 引数に渡すとホストのプロセス一覧に出るので、環境変数で受け渡す。
export PW
PW=$(aws cloudformation describe-stacks --stack-name "$STACK" \
  --query 'Stacks[0].Parameters[?ParameterKey==`MongoDbPassword`].ParameterValue' --output text)

echo "==> mongodump"
docker run --rm --user "$(id -u):$(id -g)" -e PW -v "$OUTDIR:/out" "$MONGO_IMAGE" \
  sh -c "mongodump --host \"${public_ip}:${host_port}\" -u \"${MONGO_USER}\" -p \"\$PW\" \
         --authenticationDatabase admin --archive=\"/out/$(basename "$ARCHIVE")\" --gzip"

echo "==> 完了: $ARCHIVE"
ls -lh "$ARCHIVE"
