import React, { useState, useEffect } from 'react';

const JST = 'Asia/Tokyo';

// JST の壁時計基準で日付文字列 'YYYY-MM-DD' を取得
function getJstDateStr(base) {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: JST, year: 'numeric', month: '2-digit', day: '2-digit',
  }).formatToParts(base);
  const get = (t) => parts.find((p) => p.type === t).value;
  return `${get('year')}-${get('month')}-${get('day')}`;
}

// 予約窓（今日・明日の 09:00–21:00 JST、1時間刻み＝1日12枠・計24枠）の全スロットを生成。
// 「現在時刻より過去に終わる枠」は除外。時刻はオフセット付き ISO で構築し UTC インスタントとして扱う。
function generateAllSlots() {
  const now = new Date();
  const slots = [];
  for (let d = 0; d < 2; d++) {
    const base = new Date(now.getTime() + d * 24 * 60 * 60 * 1000);
    const dateStr = getJstDateStr(base);
    for (let h = 9; h < 21; h++) {
      const start = new Date(`${dateStr}T${String(h).padStart(2, '0')}:00:00+09:00`);
      const end = new Date(`${dateStr}T${String(h + 1).padStart(2, '0')}:00:00+09:00`);
      if (end.getTime() <= now.getTime()) continue;
      slots.push({ start, end });
    }
  }
  return slots;
}

// JST 表示用フォーマット: '7/10 18:00'
function formatJstDateTime(date) {
  return new Intl.DateTimeFormat('ja-JP', {
    timeZone: JST, month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(date);
}

// JST 表示用フォーマット（時刻のみ）: '19:00'
function formatJstTime(date) {
  return new Intl.DateTimeFormat('ja-JP', {
    timeZone: JST, hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(date);
}

const CustomerCalendar = () => {
  const [slots, setSlots] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const allSlots = generateAllSlots();
    // 予約窓の全スロットの開始〜終了で上書き（calendarId1 は維持）
    const timeMin = allSlots.length ? allSlots[0].start.toISOString() : new Date().toISOString();
    const timeMax = allSlots.length
      ? allSlots[allSlots.length - 1].end.toISOString()
      : new Date(Date.now() + 48 * 60 * 60 * 1000).toISOString();
    const body = {
      calendarId1: 'drib189@gmail.com',
      timeMin,
      timeMax,
    };
    fetch('/api/get-availability', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
      .then(async (res) => {
        let bodyText = '';
        try {
          bodyText = await res.text();
        } catch (textErr) {
          bodyText = '';
        }
        // HTTP エラーステータスの場合は詳細を含む例外を投げる
        if (!res.ok) {
          const snippet =
            bodyText.length > 500 ? bodyText.slice(0, 500) + '…(省略)' : bodyText;
          const err = new Error(
            `空き枠の取得に失敗しました（ステータス: ${res.status} ${res.statusText} / 本文: ${snippet || '(本文なし)'}）`
          );
          err.isHttpError = true;
          err.status = res.status;
          err.body = bodyText;
          throw err;
        }
        // 応答本文を手動パースし、JSON でない場合も詳細を出せるようにする
        let data;
        try {
          data = JSON.parse(bodyText);
        } catch (parseErr) {
          const err = new Error(
            `空き枠の取得に失敗しました（JSONパースエラー: ${parseErr.message} / 本文: ${(bodyText || '').slice(0, 500)}）`
          );
          err.isParseError = true;
          err.body = bodyText;
          throw err;
        }
        return data;
      })
      .then((data) => {
        // 本番APIはトップレベルにカレンダーIDを置いて返す: { "<calendarId>": { busy: [{start, end}] } }
        const calendars = data || {};
        // API から得た busy 区間リストを収集
        const busyIntervals = Object.keys(calendars).reduce((acc, id) => {
          const busy = calendars[id] && Array.isArray(calendars[id].busy)
            ? calendars[id].busy
            : [];
          return acc.concat(busy.map((b) => ({ start: b.start, end: b.end })));
        }, []);
        // allSlots と busy 区間を重なり判定で合成し、{start, end, busy} の配列を作る
        const merged = allSlots.map((slot) => {
          const slotStart = slot.start.getTime();
          const slotEnd = slot.end.getTime();
          const isBusy = busyIntervals.some((b) => {
            const busyStart = new Date(b.start).getTime();
            const busyEnd = new Date(b.end).getTime();
            return slotStart < busyEnd && slotEnd > busyStart;
          });
          return { start: slot.start, end: slot.end, busy: isBusy };
        });
        setSlots(merged);
        setLoading(false);
      })
      .catch((err) => {
        let message;
        if (err && err.isHttpError) {
          message = err.message;
        } else if (err && err.isParseError) {
          message = err.message;
        } else {
          // ネットワークエラー等で fetch 自体が例外を投げた場合
          const msg = err && err.message ? err.message : String(err);
          message = `空き枠の取得に失敗しました（例外: ${msg}）`;
        }
        console.error(
          '[CustomerCalendar] 空き枠の取得に失敗しました:',
          err,
          err && err.body ? '\n応答本文:\n' + err.body : ''
        );
        setError(message);
        setLoading(false);
      });
  }, []);

  const handleBooking = (slot) => {
    fetch('/api/create-booking', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ slot }),
    })
      .then(res => res.json())
      .then(data => {
        if (data.success) {
          alert('予約が完了しました！');
        } else {
          alert('予約に失敗しました: ' + (data.message || '不明なエラー'));
        }
      })
      .catch(() => alert('予約リクエストの送信に失敗しました。'));
  };

  if (loading) return <div>読み込み中...</div>;
  if (error) return <div>{error}</div>;

  return (
    <div className="calendar-container">
      <h2>予約可能枠</h2>
      <ul>
        {slots.map((slot, index) => {
          const jsx = (
            <li
              key={index}
              onClick={slot.busy ? undefined : () => handleBooking(slot)}
              style={{
                margin: '10px',
                padding: '5px',
                border: '1px solid #ccc',
                cursor: slot.busy ? 'default' : 'pointer',
                backgroundColor: slot.busy ? '#e0e0e0' : '#e6ffe6',
                color: slot.busy ? '#888' : '#000',
                listStyle: 'none',
              }}
            >
              {formatJstDateTime(slot.start)} - {formatJstDateTime(slot.end)}
            </li>
          );
          return jsx;
        })}
      </ul>
    </div>
  );
};

export default CustomerCalendar;

// dc-runtime registration
window.CustomerCalendar = CustomerCalendar;
