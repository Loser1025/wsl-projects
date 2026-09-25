import { google } from 'googleapis';
import { getAuthorizedClient } from './dist/auth.js';

const auth = await getAuthorizedClient();
const forms = google.forms({ version: 'v1', auth });

const formId = '1ZEC_ANuC9gBhAaYONpAm6UN0cV6Fm0GJc3jUKiQBFeQ';

function textItem(title, { required = true, paragraph = false } = {}) {
  return { createItem: { item: { title, questionItem: { question: { required, textQuestion: { paragraph } } } }, location: { index: null } } };
}
function radioItem(title, options, { required = true } = {}) {
  return { createItem: { item: { title, questionItem: { question: { required, choiceQuestion: { type: 'RADIO', options: options.map((v) => ({ value: v })) } } } }, location: { index: null } } };
}
function checkboxItem(title, options, { required = true } = {}) {
  return { createItem: { item: { title, questionItem: { question: { required, choiceQuestion: { type: 'CHECKBOX', options: options.map((v) => ({ value: v })) } } } }, location: { index: null } } };
}
function dateItem(title, { required = true } = {}) {
  return { createItem: { item: { title, questionItem: { question: { required, dateQuestion: {} } } }, location: { index: null } } };
}
function pageBreak(title) {
  return { createItem: { item: { title, pageBreakItem: {} }, location: { index: null } } };
}

// ---- 1. 現在の全アイテムを削除 ----
const current = await forms.forms.get({ formId });
const deleteRequests = current.data.items.map((_, i) => ({ deleteItem: { location: { index: current.data.items.length - 1 - i } } }));
if (deleteRequests.length) {
  await forms.forms.batchUpdate({ formId, requestBody: { requests: deleteRequests } });
  console.log('deleted', deleteRequests.length, 'items');
}

// ---- 2. 新しい完全版アイテムリストを構築 ----
const requests = [];

requests.push(textItem('郵便番号'));
requests.push(textItem('住所'));
requests.push(textItem('氏名'));
requests.push(textItem('氏名（フリガナ）'));
requests.push(dateItem('生年月日'));
requests.push(radioItem('性別', ['男性', '女性']));
requests.push(radioItem('血液型', ['A型', 'B型', 'O型', 'AB型', '不明']));
requests.push(textItem('身長(cm)'));
requests.push(textItem('体重(kg)'));

requests.push(pageBreak('生活習慣・ご来院について'));
requests.push(radioItem('当クリニックにご来店されたことはございますか？（別店舗も含む）', ['今回がはじめて', '説明を受けたことがある', '施術をしたことがある']));
requests.push(radioItem('クリニックを知ったきっかけは何ですか？', ['Web広告', 'ラジオ', '喫煙所の動画', '看板']));
requests.push(checkboxItem('下記の治療にご興味はございますか？', ['クマ取り', '二重手術', 'AGA', '医療脱毛', '多汗症・ワキガ', 'テストステロン', '花粉症', 'ED', '医療ダイエット', '特になし']));
requests.push(radioItem('お酒をどのくらいの頻度で飲みますか？', ['飲まない', '１回/週', '２～３回/週', '４～５回/週', '６～７回/週']));
requests.push(radioItem('タバコをどのくらいの頻度で吸いますか？', ['吸わない', '０～５本/日', '６～１０本/日', '１箱/日', 'それ以上']));
requests.push(radioItem('旅行にどのくらいの頻度で行きますか？', ['０～１回/年', '２～３回/年', '４～５回/年', '６～８回/年', 'それ以上']));
requests.push(radioItem('ご年収はいくらですか？', ['２００万未満', '２００～４００万', '４００～６００万', '６００～８００万', '８００～１０００万', 'それ以上']));
requests.push(radioItem('保険証の種別を教えてください', ['社会保険', '国民健康保険']));
requests.push(textItem('平均の睡眠時間を教えてください。'));
requests.push(radioItem('ストレスについて教えてください。', ['少ない', '普通', '多い']));
requests.push(radioItem('お支払い方法のご希望はありますか？', ['現金', 'カード', 'デビットカード', '分割払い', '引き落とし']));
requests.push(radioItem('当院における診療はすべて自由診療である（保険適用がない）ことはご存じですか？', ['はい', 'いいえ']));
requests.push(radioItem('施術写真を院内及びHPで学術的症例としての使用にご協力いただけますでしょうか？', ['はい', 'いいえ']));

requests.push(pageBreak('現在の症状・既往歴'));
requests.push(textItem('現在の症状について不安なこと、聞きたいこと、心配なことなどがあれば教えてください。', { required: false, paragraph: true }));
requests.push(textItem('過去に大きな病気や怪我、手術（癌・交通事故など）のご経験があれば教えてください（病名・治療内容・何歳ごろか・手術歴の有無をご記載ください）', { required: false, paragraph: true }));
requests.push(checkboxItem('該当する既往歴があれば教えてください。', [
  '大豆アレルギー', '麻酔アレルギー', '糖尿病', '高血圧', '肝機能障害', '腎機能障害', '心臓病', '喘息', 'ケロイド体質',
  '無呼吸', '前立腺肥大', '透析', '緑内障', '白内障', 'アトピー性皮膚炎',
  'がん', 'その他既往歴',
], { required: false }));
requests.push(radioItem('申告いただいた持病に関して現在病院に通われていますか？', ['はい', 'いいえ'], { required: false }));
requests.push(textItem('服用中のお薬やサプリがあれば教えてください。', { required: false }));
requests.push(textItem('アレルギーの食べ物や薬があれば教えてください。', { required: false }));
requests.push(radioItem('局所麻酔の経験はありますか？', ['はい', 'いいえ'], { required: false }));
requests.push(textItem('（「はい」の方のみ）麻酔時に異常はありましたか？その時の症状を教えてください。', { required: false }));
requests.push(radioItem('今まで採血や点滴などをして具合が悪くなったことはありますか？', ['はい', 'いいえ'], { required: false }));
requests.push(textItem('（「はい」の方のみ）具体的な症状と、いつ頃かを教えてください。', { required: false }));
requests.push(radioItem('血が止まりにくいと言われたことはありますか？', ['はい', 'いいえ'], { required: false }));
requests.push(radioItem('ペースメーカーや金属（プレート・糸）は入っていますか？', ['はい', 'いいえ'], { required: false }));
requests.push(radioItem('現在、歯科矯正・インプラントをしていますか？', ['はい', 'いいえ'], { required: false }));
requests.push(radioItem('1年以内に献血をされた経験はございますか？', ['はい', 'いいえ'], { required: false }));
requests.push(radioItem('輸血経験はありますか？', ['はい', 'いいえ'], { required: false }));
requests.push(textItem('（「はい」の方のみ）どのような治療内容で輸血を行ったのかを教えてください。', { required: false }));
requests.push(radioItem('インフルエンザ等のワクチンを１週間以内に接種しましたか？', ['はい', 'いいえ'], { required: false }));
requests.push(textItem('（「はい」の方のみ）接種された日付を教えてください。', { required: false }));
requests.push(radioItem('インフルエンザ等のワクチンをこれから接種する予定はございますか？', ['はい', 'いいえ'], { required: false }));
requests.push(textItem('（「はい」の方のみ）接種を予定されている日付を教えてください。', { required: false }));

const branchCIndex = requests.length;
requests.push(radioItem('（「がん」にチェックした方のみ）現在治療中ですか？', ['治療中', '治療終了'], { required: false }));

const pageBreak5Index = requests.length;
requests.push(pageBreak('がん治療について'));
requests.push(textItem('（「がん治療終了」の方のみ）治療後の経過年数はどのくらいですか？', { required: false }));

const pageBreak6Index = requests.length;
requests.push(pageBreak('その他既往歴・妊娠・授乳'));
requests.push(textItem('（「その他既往歴」にチェックした方のみ）病名を教えてください。', { required: false }));
requests.push(radioItem('現在、妊娠中または妊活中ですか？', ['はい', 'いいえ']));
requests.push(radioItem('現在、授乳中ですか？', ['はい', 'いいえ']));
requests.push(textItem('（女性の方のみ）現在、ピル服用中ですか？服用中の場合はお薬名を教えてください。', { required: false }));
requests.push(radioItem('（女性の方のみ）出産のご経験はありますか？', ['はい', 'いいえ'], { required: false }));
requests.push(textItem('（「はい」の方のみ）出産時のご年齢と方法（経腟／帝王切開）を教えてください。', { required: false }));
requests.push(textItem('心配なこと、飲んでいるお薬があれば教えてください。', { required: false, paragraph: true }));

requests.forEach((r, i) => { r.createItem.location.index = i; });

const batch1 = await forms.forms.batchUpdate({ formId, requestBody: { requests } });
const replies = batch1.data.replies;

const section5Id = replies[pageBreak5Index].createItem.itemId;
const section6Id = replies[pageBreak6Index].createItem.itemId;
const branchCItem = requests[branchCIndex].createItem.item;
const branchCItemId = replies[branchCIndex].createItem.itemId;

function withGoTo(options, mapping) {
  return options.map((opt) => (mapping[opt.value] ? { value: opt.value, goToSectionId: mapping[opt.value] } : { value: opt.value }));
}

const branchUpdate = {
  updateItem: {
    item: {
      itemId: branchCItemId,
      title: branchCItem.title,
      questionItem: { question: { required: false, choiceQuestion: { type: 'RADIO', options: withGoTo(branchCItem.questionItem.question.choiceQuestion.options, {
        '治療中': section6Id,
        '治療終了': section5Id,
      }) } } },
    },
    location: { index: branchCIndex },
    updateMask: 'questionItem.question.choiceQuestion.options',
  },
};

await forms.forms.batchUpdate({ formId, requestBody: { requests: [branchUpdate] } });

console.log('DONE. total items:', requests.length);
const formRes = await forms.forms.get({ formId });
console.log('回答用URL:', formRes.data.responderUri);
