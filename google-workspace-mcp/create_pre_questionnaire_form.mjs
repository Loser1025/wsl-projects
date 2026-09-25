import { google } from 'googleapis';
import { getAuthorizedClient } from './dist/auth.js';

const auth = await getAuthorizedClient();
const forms = google.forms({ version: 'v1', auth });

// ---- 1. フォーム作成 ----
const createRes = await forms.forms.create({
  requestBody: { info: { title: '事前問診票（医療ダイエット）' } },
});
const formId = createRes.data.formId;
console.log('formId:', formId);

function textItem(title, { required = true, paragraph = false } = {}) {
  return {
    createItem: {
      item: { title, questionItem: { question: { required, textQuestion: { paragraph } } } },
      location: { index: null }, // set later
    },
  };
}

function radioItem(title, options, { required = true } = {}) {
  return {
    createItem: {
      item: {
        title,
        questionItem: {
          question: {
            required,
            choiceQuestion: { type: 'RADIO', options: options.map((v) => ({ value: v })) },
          },
        },
      },
      location: { index: null },
    },
  };
}

function checkboxItem(title, options, { required = true } = {}) {
  return {
    createItem: {
      item: {
        title,
        questionItem: {
          question: {
            required,
            choiceQuestion: { type: 'CHECKBOX', options: options.map((v) => ({ value: v })) },
          },
        },
      },
      location: { index: null },
    },
  };
}

function dateItem(title, { required = true } = {}) {
  return {
    createItem: {
      item: { title, questionItem: { question: { required, dateQuestion: {} } } },
      location: { index: null },
    },
  };
}

function pageBreak(title) {
  return {
    createItem: {
      item: { title, pageBreakItem: {} },
      location: { index: null },
    },
  };
}

// ---- 2. 質問リストを順番に構築 ----
const requests = [];

requests.push(textItem('患者ID'));
requests.push(textItem('郵便番号'));
requests.push(textItem('住所'));
requests.push(textItem('氏名'));
requests.push(textItem('氏名（フリガナ）'));
requests.push(textItem('電話番号'));
requests.push(textItem('メールアドレス'));
requests.push(dateItem('生年月日'));

requests.push(radioItem('性別', ['男性', '女性']));
requests.push(textItem('ご職業'));
requests.push(textItem('お仕事内容'));
requests.push(textItem('身長(cm)'));
requests.push(textItem('体重(kg)'));
requests.push(radioItem('現在のご家庭の状況を教えてください。', ['独身(子あり)', '独身(子なし)', '既婚(子あり)', '既婚(子なし)', '学生']));
requests.push(textItem('成人後に一番痩せていた時の体重と、その時期を教えてください（例：〇Kg　約●年●か月前）'));
requests.push(textItem('成人後の最大体重と、その時期を教えてください（例：〇Kg　約●年●か月前）'));
requests.push(textItem('いつまでに痩せたいですか？（例：〇ヶ月以内、〇月までなど）'));
requests.push(textItem('今までどのようなダイエットをされていましたか？（取り組み内容・時期）', { paragraph: true }));
requests.push(checkboxItem('気になる体の部位はどこですか？', ['上腹部', '下腹部', '太もも', 'ひざ上', 'ふくらはぎ', '二の腕', '側腹部', 'あご下', 'その他']));
requests.push(checkboxItem('タトゥーはありますか？', ['なし', '上腹部', '下腹部']));

requests.push(radioItem('現在お考えの治療方針に近いものをお選びください。', [
  '体型をしっかり変え、長期的に維持できる身体づくりに本格的に取り組みたい',
  '無理のない範囲で体重や見た目を改善し、徐々に変化を実感していきたい',
  '今の体型を維持しつつ、リバウンド予防として取り組みたい',
  'イベント前など、短期間でできる範囲の調整をしたい',
  'まずは自分に合うかどうか、気軽に試しながら検討したい',
]));
requests.push(textItem('月にかけている美容代はいくらくらいですか？'));
requests.push(textItem('月にかけているダイエット費用（例：ジム代やサプリ代など）はいくらくらいですか？'));
requests.push(radioItem('現在の仕事の忙しさについて、最も近いものをお選びください。', ['非常に忙しい', 'やや忙しい', '普通', 'あまり忙しくない', '仕事をしていない']));
requests.push(radioItem('職場の人間関係について、ストレスを感じることはありますか？', ['強く感じる', '少し感じる', 'ほとんど感じない', 'まったく感じない']));
requests.push(radioItem('現在の労働環境について、最も近いものをお選びください。', ['残業が多い', 'サービス残業が多い', '残業はあるが過度ではない', '残業はほとんどない']));
requests.push(radioItem('仕事や職場環境によるストレスが強い時期に、食事量の増加や体重増加を感じることはありますか？', ['よくある', 'ときどきある', 'あまりない', 'まったくない']));
requests.push(radioItem('現在、生活面や金銭面でのプレッシャーをどの程度感じていますか？(例：ローン・支払いの負担、将来への不安 など)', [
  '強く感じている（日常生活や気分に影響が出ている）',
  'ある程度感じている（気になることはあるが生活は送れている）',
  'あまり感じていない',
  'まったく感じていない',
]));

const branchAIndex = requests.length;
requests.push(radioItem('これまでに金銭的な理由で生活の見直しや立て直しを行ったご経験はありますか？ (例：債務整理・自己破産・返済計画の大幅な変更 など)', [
  'ある（現在も影響が続いている）',
  'ある（すでに解決している）',
  '検討したことはあるが、実際には行っていない',
  'まったくない',
]));

const pageBreak2Index = requests.length;
requests.push(pageBreak('生活の見直し経験について'));

requests.push(checkboxItem('（「ある」の方のみ）当時の状況について教えてください。', ['債務整理を行った', '自己破産を行った', '返済計画の大幅な見直しを行った', 'ローン・借入の整理を行った', 'その他'], { required: false }));
requests.push(textItem('（「その他」を選択した方のみ）状況を教えてください。', { required: false }));

const branchBIndex = requests.length;
requests.push(radioItem('（「ある」の方のみ）その時期はいつ頃になりますか？', ['1年以内', '1〜3年前', '3〜5年前', '5年以上前', 'その他'], { required: false }));

const pageBreak3Index = requests.length;
requests.push(pageBreak('時期の詳細'));

requests.push(textItem('（「その他」を選択した方のみ）おおよその時期を教えてください。', { required: false }));

const pageBreak4Index = requests.length;
requests.push(pageBreak('現在の症状・既往歴'));

requests.push(textItem('現在の症状について不安なこと、聞きたいこと、心配なことなどがあれば教えてください。', { required: false, paragraph: true }));
requests.push(checkboxItem('該当する既往歴があれば教えてください。', ['大豆アレルギー', '麻酔アレルギー', '糖尿病', '高血圧', '肝機能障害', '腎機能障害', '心臓病', '喘息', 'ケロイド体質', 'がん', 'その他既往歴'], { required: false }));

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
requests.push(textItem('心配なこと、飲んでいるお薬があれば教えてください。', { required: false, paragraph: true }));

// location.index を確定
requests.forEach((r, i) => {
  r.createItem.location.index = i;
});

// ---- 3. 説明文の設定 + 全項目作成（1回のbatchUpdate） ----
const infoRequest = {
  updateFormInfo: {
    info: {
      description: 'ご来院前にご記入いただく事前問診票です。ご回答内容は診療目的にのみ使用し、厳重に管理いたします。',
    },
    updateMask: 'description',
  },
};

const batch1 = await forms.forms.batchUpdate({
  formId,
  requestBody: { requests: [infoRequest, ...requests] },
});

// replies[0] は updateFormInfo なので、requestsのreplyは1つずらす
const replies = batch1.data.replies.slice(1);
const section2Id = replies[pageBreak2Index].createItem.itemId;
const section3Id = replies[pageBreak3Index].createItem.itemId;
const section4Id = replies[pageBreak4Index].createItem.itemId;
const section5Id = replies[pageBreak5Index].createItem.itemId;
const section6Id = replies[pageBreak6Index].createItem.itemId;

console.log('sections:', { section2Id, section3Id, section4Id, section5Id, section6Id });

// ---- 4. 分岐（goToSectionId）を設定する2回目のbatchUpdate ----
const branchARequests = requests[branchAIndex].createItem.item;
const branchBRequests = requests[branchBIndex].createItem.item;
const branchCRequests = requests[branchCIndex].createItem.item;

const branchAItemId = replies[branchAIndex].createItem.itemId;
const branchBItemId = replies[branchBIndex].createItem.itemId;
const branchCItemId = replies[branchCIndex].createItem.itemId;

function withGoTo(options, mapping) {
  return options.map((opt) => {
    const sectionId = mapping[opt.value];
    return sectionId ? { value: opt.value, goToSectionId: sectionId } : { value: opt.value };
  });
}

const branchUpdateRequests = [
  {
    updateItem: {
      item: {
        itemId: branchAItemId,
        title: branchARequests.title,
        questionItem: {
          question: {
            required: true,
            choiceQuestion: {
              type: 'RADIO',
              options: withGoTo(branchARequests.questionItem.question.choiceQuestion.options, {
                'ある（現在も影響が続いている）': section2Id,
                'ある（すでに解決している）': section2Id,
                '検討したことはあるが、実際には行っていない': section4Id,
                'まったくない': section4Id,
              }),
            },
          },
        },
      },
      location: { index: branchAIndex },
      updateMask: 'questionItem.question.choiceQuestion.options',
    },
  },
  {
    updateItem: {
      item: {
        itemId: branchBItemId,
        title: branchBRequests.title,
        questionItem: {
          question: {
            required: false,
            choiceQuestion: {
              type: 'RADIO',
              options: withGoTo(branchBRequests.questionItem.question.choiceQuestion.options, {
                '1年以内': section4Id,
                '1〜3年前': section4Id,
                '3〜5年前': section4Id,
                '5年以上前': section4Id,
                'その他': section3Id,
              }),
            },
          },
        },
      },
      location: { index: branchBIndex },
      updateMask: 'questionItem.question.choiceQuestion.options',
    },
  },
  {
    updateItem: {
      item: {
        itemId: branchCItemId,
        title: branchCRequests.title,
        questionItem: {
          question: {
            required: false,
            choiceQuestion: {
              type: 'RADIO',
              options: withGoTo(branchCRequests.questionItem.question.choiceQuestion.options, {
                '治療中': section6Id,
                '治療終了': section5Id,
              }),
            },
          },
        },
      },
      location: { index: branchCIndex },
      updateMask: 'questionItem.question.choiceQuestion.options',
    },
  },
];

await forms.forms.batchUpdate({ formId, requestBody: { requests: branchUpdateRequests } });

console.log('DONE');
console.log('編集URL:', `https://docs.google.com/forms/d/${formId}/edit`);

const formRes = await forms.forms.get({ formId });
console.log('回答用URL:', formRes.data.responderUri);
