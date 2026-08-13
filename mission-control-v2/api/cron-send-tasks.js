const DB_URL = 'https://fulcrum-tasks-default-rtdb.asia-southeast1.firebasedatabase.app';

module.exports = async (req, res) => {
  // 1. Cron認証チェック (Vercel Cron または手動呼び出し時の認証)
  const authHeader = req.headers['authorization'];
  if (process.env.CRON_SECRET && authHeader !== `Bearer ${process.env.CRON_SECRET}`) {
    return res.status(401).json({ error: 'Unauthorized' });
  }

  const webhookUrl = process.env.GOOGLE_CHAT_WEBHOOK_URL;
  if (!webhookUrl) {
    return res.status(500).json({ error: 'Missing GOOGLE_CHAT_WEBHOOK_URL env var' });
  }

  try {
    // 2. Firebase RTDB からタスクとセクションを取得
    const [tasksRes, secsRes] = await Promise.all([
      fetch(`${DB_URL}/tasks.json`),
      fetch(`${DB_URL}/sections.json`)
    ]);

    if (!tasksRes.ok || !secsRes.ok) {
      throw new Error(`Failed to fetch data from Firebase RTDB (tasks: ${tasksRes.status}, secs: ${secsRes.status})`);
    }

    const rawTasks = (await tasksRes.json()) || {};
    const rawSecs = (await secsRes.json()) || {};

    const tasks = Array.isArray(rawTasks) ? rawTasks : Object.values(rawTasks);
    const sections = Array.isArray(rawSecs) ? rawSecs : Object.values(rawSecs);

    const activeSections = sections.filter(s => s && s.id);
    const sectionMap = {};
    activeSections.forEach(s => { sectionMap[s.id] = s.name; });

    // 3. 「完了 (done)」以外のタスクを抽出・集計
    const activeTasks = tasks.filter(t => t && t.status !== 'done');

    // 4. セクションごとにグループ化
    const grouped = {};
    activeTasks.forEach(t => {
      const secId = t.section || '__unassigned__';
      if (!grouped[secId]) grouped[secId] = [];
      grouped[secId].push(t);
    });

    // 5. Google Chat メッセージ（Cards v2）の組み立て
    const cardPayload = createCardPayload(grouped, sectionMap, activeTasks.length, activeSections);

    // 6. Google Chat へ POST 送信
    const chatRes = await fetch(webhookUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json; charset=UTF-8' },
      body: JSON.stringify(cardPayload)
    });

    if (!chatRes.ok) {
      const errText = await chatRes.text();
      throw new Error(`Google Chat API error: ${chatRes.status} ${errText}`);
    }

    return res.status(200).json({ success: true, count: activeTasks.length });
  } catch (err) {
    console.error('Cron send tasks error:', err);
    return res.status(500).json({ error: err.message });
  }
};

// --- Google Chat Card v2 ヘルパー関数 ---

function getStatusLabel(status) {
  switch (status) {
    case 'doing': return '進行中';
    case 'review': return 'レビュー';
    case 'todo':
    default: return '未着手';
  }
}

function getUrgencyBadge(urgency) {
  switch (urgency) {
    case 'high': return '🔴 [高]';
    case 'medium': return '🟡 [中]';
    case 'low': return '⚪ [低]';
    default: return '🔹';
  }
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function createCardPayload(groupedTasks, sectionMap, totalCount, allSections) {
  const todayStr = new Date().toLocaleDateString('ja-JP', {
    timeZone: 'Asia/Tokyo',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit'
  });

  const widgets = [];

  // 登録されている全セクションを走査
  allSections.forEach(sec => {
    const secId = sec.id;
    const secName = sec.name;
    const tasks = groupedTasks[secId] || [];

    if (tasks.length > 0) {
      let textLines = `<b>📂 ${escapeHtml(secName)}</b> (残 ${tasks.length}件)<br/>`;
      tasks.forEach(t => {
        const urg = getUrgencyBadge(t.priority);
        const st = getStatusLabel(t.status);
        const assignee = t.assignee ? `(担当: ${escapeHtml(t.assignee)})` : '';
        textLines += `・${urg} <b>${escapeHtml(t.title)}</b> <code>[${st}]</code> ${assignee}<br/>`;
      });
      widgets.push({ textParagraph: { text: textLines } });
    } else {
      // 残タスクがないセクションへの登録促進メッセージ
      widgets.push({
        textParagraph: {
          text: `<b>📂 ${escapeHtml(secName)}</b><br/><font color="#888888">💡 現在、完了以外の残タスクはありません。新規タスクの追加・登録をご検討ください。</font>`
        }
      });
    }
  });

  // 未分類セクション（セクション未指定のタスクがある場合のみ表示）
  if (groupedTasks['__unassigned__'] && groupedTasks['__unassigned__'].length > 0) {
    const unassignedTasks = groupedTasks['__unassigned__'];
    let textLines = `<b>📂 未分類</b> (残 ${unassignedTasks.length}件)<br/>`;
    unassignedTasks.forEach(t => {
      const urg = getUrgencyBadge(t.urgency);
      const st = getStatusLabel(t.status);
      const assignee = t.assignee ? `(担当: ${escapeHtml(t.assignee)})` : '';
      textLines += `・${urg} <b>${escapeHtml(t.title)}</b> <code>[${st}]</code> ${assignee}<br/>`;
    });
    widgets.push({ textParagraph: { text: textLines } });
  }

  const appUrl = process.env.APP_URL || 'https://mission-control-v2.vercel.app';

  return {
    cardsV2: [
      {
        cardId: 'daily-tasks-card',
        card: {
          header: {
            title: `📋 本日の残タスク通知 (${todayStr})`,
            subtitle: `全残タスク数: ${totalCount} 件`,
            imageUrl: 'https://fonts.gstatic.com/s/i/short-term/release/googlesymbols/task/default/48px.svg',
            imageType: 'CIRCLE'
          },
          sections: [
            {
              widgets: widgets
            },
            {
              widgets: [
                {
                  buttonList: {
                    buttons: [
                      {
                        text: '🔗 Mission Control を開く',
                        onClick: {
                          openLink: {
                            url: appUrl
                          }
                        }
                      }
                    ]
                  }
                }
              ]
            }
          ]
        }
      }
    ]
  };
}
