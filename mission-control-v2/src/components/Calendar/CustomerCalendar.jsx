import React, { useState, useEffect } from 'react';

const CustomerCalendar = () => {
  const [slots, setSlots] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const now = new Date();
    const body = {
      calendarId1: 'drib189@gmail.com',
      timeMin: now.toISOString(),
      timeMax: new Date(now.getTime() + 24 * 60 * 60 * 1000).toISOString(),
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
        // data.calendars の構造: { "<calendarId>": { busy: [{start, end}] } }
        const calendars = data.calendars || {};
        const busySlots = Object.keys(calendars).reduce((acc, id) => {
          const busy = calendars[id] && Array.isArray(calendars[id].busy)
            ? calendars[id].busy
            : [];
          return acc.concat(busy.map((b) => ({ start: b.start, end: b.end })));
        }, []);
        setSlots(busySlots);
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
        {slots.map((slot, index) => (
          <li key={index} onClick={() => handleBooking(slot)} style={{ cursor: 'pointer', margin: '10px', padding: '5px', border: '1px solid #ccc' }}>
            {slot.start} - {slot.end}
          </li>
        ))}
      </ul>
    </div>
  );
};

export default CustomerCalendar;

// dc-runtime registration
window.CustomerCalendar = CustomerCalendar;
