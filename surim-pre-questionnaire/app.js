const form = document.getElementById('qForm');
const submitBtn = document.getElementById('submitBtn');
const formWrap = document.getElementById('formWrap');
const resultEl = document.getElementById('result');

// 条件付き表示（data-show-if="fieldName=value"）
document.querySelectorAll('.conditional').forEach((el) => {
  const [name, expected] = el.dataset.showIf.split('=');
  const radios = form.querySelectorAll(`input[name="${name}"]`);
  radios.forEach((r) => {
    r.addEventListener('change', () => {
      el.classList.toggle('is-visible', r.value === expected && r.checked);
    });
  });
});

function renderResult(ok, message) {
  formWrap.style.display = 'none';
  resultEl.style.display = 'block';
  resultEl.innerHTML = `
    <div class="wrap"><div class="panel ${ok ? 'ok' : 'err'}">
      <div class="icon">
        ${ok
          ? '<svg viewBox="0 0 24 24" fill="none" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6L9 17l-5-5"/></svg>'
          : '<svg viewBox="0 0 24 24" fill="none" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 8v5M12 16h.01M12 21a9 9 0 100-18 9 9 0 000 18z"/></svg>'}
      </div>
      <h2>${ok ? '送信が完了しました' : '送信に失敗しました'}</h2>
      <p>${message}</p>
    </div></div>
  `;
}

function val(id) {
  return document.getElementById(id)?.value?.trim() || '';
}
function radioVal(name) {
  return form.querySelector(`input[name="${name}"]:checked`)?.value || '';
}
function checkboxVals(name) {
  return Array.from(form.querySelectorAll(`input[name="${name}"]:checked`)).map((el) => el.value);
}

form.addEventListener('submit', async (e) => {
  e.preventDefault();

  if (checkboxVals('interest').length === 0) {
    alert('下記の治療にご興味はございますかを1つ以上選択してください。');
    return;
  }

  const payload = {
    postal: val('postal'),
    address: val('address'),
    name: val('name'),
    kana: val('kana'),
    dob: val('dob'),
    gender: radioVal('gender'),
    bloodType: radioVal('bloodType'),
    height: val('height'),
    weight: val('weight'),

    visitHistory: radioVal('visitHistory'),
    referral: radioVal('referral'),
    interest: checkboxVals('interest').join('、'),
    payment: radioVal('payment'),

    symptomConcern: val('symptomConcern'),
    majorHistory: val('majorHistory'),
    medicalHistory: checkboxVals('medicalHistory').join('、'),
    chronicOngoing: radioVal('chronicOngoing'),
    currentMeds: val('currentMeds'),
    allergies: val('allergies'),
    metalImplant: radioVal('metalImplant'),
    cancerStatus: radioVal('cancerStatus'),
    cancerYears: val('cancerYears'),
    otherDiseaseName: val('otherDiseaseName'),

    pregnancy: radioVal('pregnancy'),
    breastfeeding: radioVal('breastfeeding'),
    pillUse: val('pillUse'),
    childbirth: radioVal('childbirth'),
    childbirthDetail: val('childbirthDetail'),
    finalConcern: val('finalConcern'),
  };

  submitBtn.disabled = true;
  submitBtn.textContent = '送信中...';
  try {
    const res = await fetch('/api/submit', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error('server_error');
    renderResult(true, 'ご回答ありがとうございました。ご来院時に受付にてお名前をお伝えください。');
  } catch (err) {
    submitBtn.disabled = false;
    submitBtn.textContent = '送信する';
    renderResult(false, '恐れ入りますが、しばらくしてから再度お試しいただくか、クリニックへ直接お問い合わせください。');
  }
});
