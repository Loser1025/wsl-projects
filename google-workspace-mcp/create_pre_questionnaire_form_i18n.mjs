import { google } from 'googleapis';
import { getAuthorizedClient } from './dist/auth.js';

const auth = await getAuthorizedClient();
const forms = google.forms({ version: 'v1', auth });
const drive = google.drive({ version: 'v3', auth });

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
function withGoTo(options, mapping) {
  return options.map((opt) => (mapping[opt.value] ? { value: opt.value, goToSectionId: mapping[opt.value] } : { value: opt.value }));
}

async function buildForm(lang) {
  const createRes = await forms.forms.create({ requestBody: { info: { title: lang.title } } });
  const formId = createRes.data.formId;
  console.log(lang.code, 'formId:', formId);

  const requests = [];
  requests.push(textItem(lang.q.patientId));
  requests.push(textItem(lang.q.postal));
  requests.push(textItem(lang.q.address));
  requests.push(textItem(lang.q.name));
  requests.push(textItem(lang.q.nameRomaji));
  requests.push(textItem(lang.q.phone));
  requests.push(textItem(lang.q.email));
  requests.push(dateItem(lang.q.dob));

  requests.push(radioItem(lang.q.gender, lang.opt.gender));
  requests.push(textItem(lang.q.occupation));
  requests.push(textItem(lang.q.jobContent));
  requests.push(textItem(lang.q.height));
  requests.push(textItem(lang.q.weight));
  requests.push(radioItem(lang.q.household, lang.opt.household));
  requests.push(textItem(lang.q.leanestWeight));
  requests.push(textItem(lang.q.maxWeight));
  requests.push(textItem(lang.q.goalPeriod));
  requests.push(textItem(lang.q.dietHistory, { paragraph: true }));
  requests.push(checkboxItem(lang.q.bodyParts, lang.opt.bodyParts));
  requests.push(checkboxItem(lang.q.tattoo, lang.opt.tattoo));

  requests.push(radioItem(lang.q.treatmentPolicy, lang.opt.treatmentPolicy));
  requests.push(textItem(lang.q.beautyCost));
  requests.push(textItem(lang.q.dietCost));
  requests.push(radioItem(lang.q.busyness, lang.opt.busyness));
  requests.push(radioItem(lang.q.workStress, lang.opt.workStress));
  requests.push(radioItem(lang.q.workEnv, lang.opt.workEnv));
  requests.push(radioItem(lang.q.stressEating, lang.opt.stressEating));
  requests.push(radioItem(lang.q.financialPressure, lang.opt.financialPressure));

  const branchAIndex = requests.length;
  requests.push(radioItem(lang.q.financialHistory, lang.opt.financialHistory));

  const pageBreak2Index = requests.length;
  requests.push(pageBreak(lang.section.s2));

  requests.push(checkboxItem(lang.q.financialDetail, lang.opt.financialDetail, { required: false }));
  requests.push(textItem(lang.q.financialOther, { required: false }));

  const branchBIndex = requests.length;
  requests.push(radioItem(lang.q.financialTiming, lang.opt.financialTiming, { required: false }));

  const pageBreak3Index = requests.length;
  requests.push(pageBreak(lang.section.s3));

  requests.push(textItem(lang.q.financialTimingOther, { required: false }));

  const pageBreak4Index = requests.length;
  requests.push(pageBreak(lang.section.s4));

  requests.push(textItem(lang.q.concerns, { required: false, paragraph: true }));
  requests.push(checkboxItem(lang.q.medicalHistory, lang.opt.medicalHistory, { required: false }));

  const branchCIndex = requests.length;
  requests.push(radioItem(lang.q.cancerStatus, lang.opt.cancerStatus, { required: false }));

  const pageBreak5Index = requests.length;
  requests.push(pageBreak(lang.section.s5));

  requests.push(textItem(lang.q.cancerYears, { required: false }));

  const pageBreak6Index = requests.length;
  requests.push(pageBreak(lang.section.s6));

  requests.push(textItem(lang.q.otherDiseaseName, { required: false }));
  requests.push(radioItem(lang.q.pregnancy, lang.opt.yesNo));
  requests.push(radioItem(lang.q.breastfeeding, lang.opt.yesNo));
  requests.push(textItem(lang.q.medications, { required: false, paragraph: true }));

  requests.forEach((r, i) => { r.createItem.location.index = i; });

  const infoRequest = { updateFormInfo: { info: { description: lang.description }, updateMask: 'description' } };
  const batch1 = await forms.forms.batchUpdate({ formId, requestBody: { requests: [infoRequest, ...requests] } });
  const replies = batch1.data.replies.slice(1);

  const section2Id = replies[pageBreak2Index].createItem.itemId;
  const section3Id = replies[pageBreak3Index].createItem.itemId;
  const section4Id = replies[pageBreak4Index].createItem.itemId;
  const section5Id = replies[pageBreak5Index].createItem.itemId;
  const section6Id = replies[pageBreak6Index].createItem.itemId;

  const branchAItem = requests[branchAIndex].createItem.item;
  const branchBItem = requests[branchBIndex].createItem.item;
  const branchCItem = requests[branchCIndex].createItem.item;
  const branchAItemId = replies[branchAIndex].createItem.itemId;
  const branchBItemId = replies[branchBIndex].createItem.itemId;
  const branchCItemId = replies[branchCIndex].createItem.itemId;

  const financialHistoryOpts = lang.opt.financialHistory;
  const financialTimingOpts = lang.opt.financialTiming;
  const cancerStatusOpts = lang.opt.cancerStatus;

  const branchUpdateRequests = [
    {
      updateItem: {
        item: {
          itemId: branchAItemId,
          title: branchAItem.title,
          questionItem: { question: { required: true, choiceQuestion: { type: 'RADIO', options: withGoTo(branchAItem.questionItem.question.choiceQuestion.options, {
            [financialHistoryOpts[0]]: section2Id,
            [financialHistoryOpts[1]]: section2Id,
            [financialHistoryOpts[2]]: section4Id,
            [financialHistoryOpts[3]]: section4Id,
          }) } } },
        },
        location: { index: branchAIndex },
        updateMask: 'questionItem.question.choiceQuestion.options',
      },
    },
    {
      updateItem: {
        item: {
          itemId: branchBItemId,
          title: branchBItem.title,
          questionItem: { question: { required: false, choiceQuestion: { type: 'RADIO', options: withGoTo(branchBItem.questionItem.question.choiceQuestion.options, {
            [financialTimingOpts[0]]: section4Id,
            [financialTimingOpts[1]]: section4Id,
            [financialTimingOpts[2]]: section4Id,
            [financialTimingOpts[3]]: section4Id,
            [financialTimingOpts[4]]: section3Id,
          }) } } },
        },
        location: { index: branchBIndex },
        updateMask: 'questionItem.question.choiceQuestion.options',
      },
    },
    {
      updateItem: {
        item: {
          itemId: branchCItemId,
          title: branchCItem.title,
          questionItem: { question: { required: false, choiceQuestion: { type: 'RADIO', options: withGoTo(branchCItem.questionItem.question.choiceQuestion.options, {
            [cancerStatusOpts[0]]: section6Id,
            [cancerStatusOpts[1]]: section5Id,
          }) } } },
        },
        location: { index: branchCIndex },
        updateMask: 'questionItem.question.choiceQuestion.options',
      },
    },
  ];

  await forms.forms.batchUpdate({ formId, requestBody: { requests: branchUpdateRequests } });

  await drive.permissions.create({ fileId: formId, requestBody: { role: 'reader', type: 'anyone' } });

  const formRes = await forms.forms.get({ formId });
  console.log(lang.code, '編集URL:', `https://docs.google.com/forms/d/${formId}/edit`);
  console.log(lang.code, '回答用URL:', formRes.data.responderUri);
}

// =================== 한국어 ===================
const ko = {
  code: 'KO',
  title: '사전 문진표(의료 다이어트)',
  description: '내원 전에 작성해 주시는 사전 문진표입니다. 답변 내용은 진료 목적으로만 사용되며 철저히 관리됩니다.',
  q: {
    patientId: '환자 ID', postal: '우편번호', address: '주소', name: '성명', nameRomaji: '성명(여권 영문/로마자 표기)',
    phone: '전화번호', email: '이메일 주소', dob: '생년월일',
    gender: '성별', occupation: '직업', jobContent: '업무 내용', height: '키(cm)', weight: '체중(kg)',
    household: '현재 가정 상황을 알려주세요.',
    leanestWeight: '성인 후 가장 가벼웠을 때의 체중과 그 시기를 알려주세요（예: 〇kg 약 ●년 ●개월 전）',
    maxWeight: '성인 후 최대 체중과 그 시기를 알려주세요（예: 〇kg 약 ●년 ●개월 전）',
    goalPeriod: '언제까지 살을 빼고 싶으신가요?（예: 〇개월 이내, 〇월까지 등）',
    dietHistory: '지금까지 어떤 다이어트를 하셨나요?（방법・시기）',
    bodyParts: '신경 쓰이는 신체 부위는 어디인가요?', tattoo: '문신이 있으신가요?',
    treatmentPolicy: '현재 생각하고 계신 치료 방향에 가까운 것을 선택해 주세요.',
    beautyCost: '한 달에 미용비로 쓰는 비용은 얼마 정도인가요?',
    dietCost: '한 달에 다이어트 비용(예: 헬스장, 보조제 등)으로 쓰는 비용은 얼마 정도인가요?',
    busyness: '현재 업무의 바쁜 정도에 대해 가장 가까운 것을 선택해 주세요.',
    workStress: '직장 내 인간관계에 대해 스트레스를 느끼시나요?',
    workEnv: '현재 근무 환경에 대해 가장 가까운 것을 선택해 주세요.',
    stressEating: '업무나 직장 환경으로 인한 스트레스가 강한 시기에 식사량 증가나 체중 증가를 느끼시나요?',
    financialPressure: '현재 생활면이나 금전면에서 느끼는 부담은 어느 정도인가요?（예: 대출・상환 부담, 미래에 대한 불안 등）',
    financialHistory: '지금까지 금전적인 이유로 생활을 재정비하거나 다시 세운 경험이 있으신가요?（예: 채무 정리・개인 파산・상환 계획의 큰 변경 등）',
    financialDetail: '(「있다」인 경우만) 당시 상황에 대해 알려주세요.',
    financialOther: '(「기타」선택자만) 상황을 알려주세요.',
    financialTiming: '(「있다」인 경우만) 그 시기는 언제쯔음인가요?',
    financialTimingOther: '(「기타」선택자만) 대략적인 시기를 알려주세요.',
    concerns: '현재 증상에 대해 불안한 점, 묻고 싶은 것, 걱정되는 것이 있으면 알려주세요.',
    medicalHistory: '해당하는 기존 병력이 있으면 알려주세요.',
    cancerStatus: '(「암」체크한 경우만) 현재 치료 중이신가요?',
    cancerYears: '(「치료 종료」인 경우만) 치료 후 경과 연수는 어느 정도인가요?',
    otherDiseaseName: '(「기타 기존 병력」체크한 경우만) 병명을 알려주세요.',
    pregnancy: '현재 임신 중 또는 임신을 준비 중이신가요?',
    breastfeeding: '현재 수유 중이신가요?',
    medications: '걱정되는 점, 복용 중인 약이 있으면 알려주세요.',
  },
  opt: {
    gender: ['남성', '여성'],
    household: ['미혼(자녀 있음)', '미혼(자녀 없음)', '기혼(자녀 있음)', '기혼(자녀 없음)', '학생'],
    bodyParts: ['윗배', '아랫배', '허벅지', '무릎 위', '종아리', '팔뚝', '옆구리', '턱 아래', '기타'],
    tattoo: ['없음', '윗배', '아랫배'],
    treatmentPolicy: [
      '체형을 확실히 바꾸고 장기적으로 유지할 수 있는 몸을 만들고 싶다',
      '무리하지 않는 범위에서 체중이나 외형을 개선하고 점차 변화를 느끼고 싶다',
      '지금의 체형을 유지하면서 요요 방지를 위해 관리하고 싶다',
      '행사 전 등 짧은 기간에 가능한 범위에서 조절하고 싶다',
      '우선 나에게 맞는지 가볍게 시도해보며 검토하고 싶다',
    ],
    busyness: ['매우 바쁘다', '조금 바쁘다', '보통', '별로 바쁘지 않다', '일을 하지 않는다'],
    workStress: ['강하게 느낀다', '조금 느낀다', '거의 느끼지 않는다', '전혀 느끼지 않는다'],
    workEnv: ['야근이 많다', '무급 야근이 많다', '야근은 있지만 과도하지 않다', '야근이 거의 없다'],
    stressEating: ['자주 있다', '때때로 있다', '별로 없다', '전혀 없다'],
    financialPressure: [
      '강하게 느끼고 있다(일상생활이나 기분에 영향이 있다)',
      '어느 정도 느끼고 있다(신경 쓰이지만 생활은 가능하다)',
      '별로 느끼지 않는다',
      '전혀 느끼지 않는다',
    ],
    financialHistory: ['있다(현재도 영향이 계속되고 있다)', '있다(이미 해결했다)', '검토한 적은 있지만 실제로 하지는 않았다', '전혀 없다'],
    financialDetail: ['채무 정리를 했다', '개인 파산을 했다', '상환 계획을 크게 재검토했다', '대출 정리를 했다', '기타'],
    financialTiming: ['1년 이내', '1~3년 전', '3~5년 전', '5년 이상 전', '기타'],
    medicalHistory: ['대두(콩) 알레르기', '마취 알레르기', '당뇨병', '고혈압', '간기능 장애', '신장기능 장애', '심장병', '천식', '켈로이드 체질', '암', '기타 기존 병력'],
    cancerStatus: ['치료 중', '치료 종료'],
    yesNo: ['예', '아니요'],
  },
  section: { s2: '생활 재정비 경험에 대해', s3: '시기 상세', s4: '현재 증상・기존 병력', s5: '암 치료에 대해', s6: '기타 병력・임신・수유' },
};

// =================== 繁體中文（台灣） ===================
const tw = {
  code: 'TW',
  title: '術前問診表（醫療瘦身）',
  description: '這是您來院前需要填寫的術前問診表。您的回答僅用於診療目的，並將嚴密管理。',
  q: {
    patientId: '病患編號', postal: '郵遞區號', address: '地址', name: '姓名', nameRomaji: '姓名（護照英文/羅馬拼音）',
    phone: '電話號碼', email: '電子信箱', dob: '出生日期',
    gender: '性別', occupation: '職業', jobContent: '工作內容', height: '身高(cm)', weight: '體重(kg)',
    household: '請告訴我們您目前的家庭狀況。',
    leanestWeight: '請告訴我們您成年後體重最輕時的體重與時期（例：〇kg 約●年●個月前）',
    maxWeight: '請告訴我們您成年後的最大體重與時期（例：〇kg 約●年●個月前）',
    goalPeriod: '您希望在什麼時候之前瘦下來？（例：〇個月內、〇月之前等）',
    dietHistory: '到目前為止您嘗試過哪些減重方法？（內容・時期）',
    bodyParts: '您在意的身體部位是哪裡？', tattoo: '您有刺青嗎？',
    treatmentPolicy: '請選擇最接近您目前治療方向的選項。',
    beautyCost: '您每月花費在美容上的費用大約是多少？',
    dietCost: '您每月花費在減重上的費用（例如健身房費用、保健食品費用等）大約是多少？',
    busyness: '請選擇最接近您目前工作忙碌程度的選項。',
    workStress: '您會因職場人際關係感到壓力嗎？',
    workEnv: '請選擇最接近您目前工作環境的選項。',
    stressEating: '當工作或職場環境壓力較大時，您會感覺食量增加或體重增加嗎？',
    financialPressure: '您目前在生活或金錢方面感受到的壓力程度為何？（例：貸款・還款負擔、對未來的不安等）',
    financialHistory: '過去是否曾因金錢因素而需要重新調整或重建生活？（例：債務整理・個人破產・大幅變更還款計畫等）',
    financialDetail: '（僅「有」的人）請告訴我們當時的狀況。',
    financialOther: '（僅選擇「其他」的人）請告訴我們狀況。',
    financialTiming: '（僅「有」的人）那大約是什麼時期？',
    financialTimingOther: '（僅選擇「其他」的人）請告訴我們大概的時期。',
    concerns: '如果您對目前的症狀有任何不安、想詢問或擔心的事情，請告訴我們。',
    medicalHistory: '如有符合的既往病史，請告訴我們。',
    cancerStatus: '（僅勾選「癌症」的人）目前是否正在治療中？',
    cancerYears: '（僅「治療已結束」的人）治療後經過了多久？',
    otherDiseaseName: '（僅勾選「其他既往病史」的人）請告訴我們病名。',
    pregnancy: '您目前是否懷孕中或正在備孕？',
    breastfeeding: '您目前是否在哺乳？',
    medications: '如有擔心的事情或正在服用的藥物，請告訴我們。',
  },
  opt: {
    gender: ['男性', '女性'],
    household: ['單身(有子女)', '單身(無子女)', '已婚(有子女)', '已婚(無子女)', '學生'],
    bodyParts: ['上腹部', '下腹部', '大腿', '膝蓋上方', '小腿', '上臂', '側腰', '下顎', '其他'],
    tattoo: ['無', '上腹部', '下腹部'],
    treatmentPolicy: [
      '想要確實改變體型，並認真投入可長期維持的身體管理',
      '想在不勉強的範圍內改善體重或外觀，逐步感受變化',
      '想在維持現有體型的同時，作為復胖預防來管理',
      '想在活動前等短期內做可行範圍的調整',
      '想先輕鬆嘗試看看是否適合自己，再做考慮',
    ],
    busyness: ['非常忙碌', '有點忙碌', '普通', '不太忙碌', '目前沒有工作'],
    workStress: ['感到強烈壓力', '感到一些壓力', '幾乎不會感到壓力', '完全不會感到壓力'],
    workEnv: ['加班很多', '無薪加班很多', '有加班但不過度', '幾乎沒有加班'],
    stressEating: ['經常如此', '有時如此', '不太會', '完全不會'],
    financialPressure: [
      '感受強烈（已影響日常生活或心情）',
      '有一定程度的感受（會在意但仍能維持生活）',
      '不太有感受',
      '完全沒有感受',
    ],
    financialHistory: ['有（目前仍持續受到影響）', '有（已經解決）', '曾考慮過但實際上沒有進行', '完全沒有'],
    financialDetail: ['進行了債務整理', '進行了個人破產', '大幅調整了還款計畫', '整理了貸款・借款', '其他'],
    financialTiming: ['1年以內', '1〜3年前', '3〜5年前', '5年以上前', '其他'],
    medicalHistory: ['黃豆過敏', '麻醉過敏', '糖尿病', '高血壓', '肝功能障礙', '腎功能障礙', '心臟病', '氣喘', '蟹足腫體質', '癌症', '其他既往病史'],
    cancerStatus: ['治療中', '治療已結束'],
    yesNo: ['是', '否'],
  },
  section: { s2: '生活重建經驗相關', s3: '時期詳情', s4: '目前症狀・既往病史', s5: '癌症治療相關', s6: '其他病史・懷孕・哺乳' },
};

await buildForm(ko);
await buildForm(tw);
