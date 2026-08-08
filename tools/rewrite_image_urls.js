// テーブルデータに直接埋め込まれた画像URLのバケット名を置き換える。
//
// アップロードされた画像のURLは https://<bucket>.s3.<region>.amazonaws.com/upload/<name>
// という形でコンポーネントのデータに保存される。S3のオブジェクトをコピーしても
// このURLは変わらないため、バケットを移したら書き換えが必要になる。
//
// 最終ダンプをリストアするとデータが元に戻るので、カットオーバー時にも再実行すること。
//
// 使い方:
//   mongosh "<uri>" --file rewrite_image_urls.js \
//     --eval 'var OLD="旧バケット名", NEW="新バケット名"'
//
// 書き換えずに件数だけ確認する（本番に流す前に必ず一度実行すること）:
//   mongosh "<uri>" --file rewrite_image_urls.js \
//     --eval 'var OLD="...", NEW="...", DRY=true'

if (typeof OLD === 'undefined' || typeof NEW === 'undefined') {
    throw new Error('OLD と NEW を --eval で指定すること');
}

const DRY_RUN = typeof DRY !== 'undefined' && DRY;

// Extended JSONへの往復で置換する。ObjectIdやDate等のBSON型は $oid / $date 表現に
// なるため、単純な文字列置換をしても型が壊れない。
//
// 再帰的に走査して文字列の葉だけを置き換える方法は使わないこと。mongoshのBSON
// デシリアライザは別realmのオブジェクトを返すため `value.constructor === Object`
// による埋め込みドキュメントの判定が常にfalseになり、置換が実行されない。
function serialize(doc) {
    return EJSON.stringify(doc, null, 0, {relaxed: false});
}

const collections = ['tables', 'table_metas', 'components', 'kits'];
let total = 0;

if (DRY_RUN) {
    print('dry-run: 件数を数えるだけで書き換えは行わない');
}

collections.forEach(name => {
    const collection = db.getCollection(name);
    let count = 0;
    collection.find({}).forEach(doc => {
        // 判定と置換で同じシリアライズ結果を使い回す
        const canonical = serialize(doc);
        if (canonical.indexOf(OLD) === -1) {
            return;
        }
        if (!DRY_RUN) {
            collection.replaceOne({_id: doc._id}, EJSON.parse(canonical.split(OLD).join(NEW)));
        }
        count++;
    });
    print(`${name}: ${count} 件${DRY_RUN ? 'が該当' : 'を書き換え'}`);
    total += count;
});

print(`合計 ${total} 件`);

// 残っていないことを確認する。書き換えたつもりで実際には効いていない事故を防ぐため、
// 件数の報告だけで終わらせない。
if (!DRY_RUN) {
    let remaining = 0;
    collections.forEach(name => {
        db.getCollection(name).find({}).forEach(doc => {
            if (serialize(doc).indexOf(OLD) !== -1) {
                remaining++;
            }
        });
    });
    print(remaining === 0 ? '旧バケット名の残留なし' : `警告: ${remaining} 件が未置換のまま残っている`);
}
