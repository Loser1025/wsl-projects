import React, { useState, useEffect } from 'react';
import PropTypes from 'prop-types';

// デフォルトタイムゾーン
const DEFAULT_TIMEZONE = 'Asia/Tokyo';

// デフォルト営業時間
const DEFAULT_BUSINESS_HOURS = { start: 9, end: 21 };
// デフォルトスロット間隔（分）
const DEFAULT_SLOT_DURATION_MINUTES = 60;
// デフォルト予約可能日数（今日・明日＝2日）
const DEFAULT_DAYS_AHEAD = 2;

// 指定タイムゾーンの壁時計基準で日付文字列 'YYYY-MM-DD' を取得
function getDateStr(base, tz) {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit',
  }).formatToParts(base);
  const get = (t) => parts.find((p) => p.type === t).value;
  return `${get('year')}-${get('month')}-${get('day')}`;
}

// 予約窓（営業時間、スロット間隔、予約可能日数を指定可能）の全スロットを生成。
// 「指定タイムゾーンの現在時刻より過去に終わる枠」は除外。時刻はオフセット付き ISO で構築し UTC インスタントとして扱う。
function generateAllSlots(tz, options = {}) {
  const {
    businessHours = DEFAULT_BUSINESS_HOURS,
    slotDurationMinutes = DEFAULT_SLOT_DURATION_MINUTES,
    daysAhead = DEFAULT_DAYS_AHEAD,
  } = options;
  
  const { start: startHour, end: endHour } = businessHours;
  const now = new Date();
  const slots = [];
  
  for (let d = 0; d < daysAhead; d++) {
    const base = new Date(now.getTime() + d * 24 * 60 * 60 * 1000);
    const dateStr = getDateStr(base, tz);
    
    for (let h = startHour; h < endHour; h += slotDurationMinutes / 60) {
      // オフセットを計算して正しいタイムゾーンで時刻を構築
      const start = new Date(`${dateStr}T${String(h).padStart(2, '0')}:00:00`);
      const endMinutes = h + slotDurationMinutes / 60;
      const end = new Date(`${dateStr}T${String(endMinutes).padStart(2, '0')}:00:00`);
      
      // 指定タイムゾーンでの「現在時刻」を取得して過去枠判定
      const nowInTz = new Date(
        new Intl.DateTimeFormat('en-CA', {
          timeZone: tz,
          year: 'numeric', month: '2-digit', day: '2-digit',
          hour: '2-digit', minute: '2-digit', second: '2-digit',
          hour12: false
        }).formatToParts(now).map(p => p.value).join('')
      );
      
      if (end.getTime() <= nowInTz.getTime()) continue;
      slots.push({ start, end });
    }
  }
  return slots;
}

// 指定タイムゾーン表示用フォーマット: '7/10 18:00'
function formatDateTime(date, tz) {
  return new Intl.DateTimeFormat('ja-JP', {
    timeZone: tz, month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(date);
}

// 指定タイムゾーン表示用フォーマット（時刻のみ）: '19:00'
function formatTime(date, tz) {
  return new Intl.DateTimeFormat('ja-JP', {
    timeZone: tz, hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(date);
}

const CustomerCalendar = ({
  timezone = DEFAULT_TIMEZONE,
  businessHours = DEFAULT_BUSINESS_HOURS,
  slotDurationMinutes = DEFAULT_SLOT_DURATION_MINUTES,
  daysAhead = DEFAULT_DAYS_AHEAD,
}) => {
  const [slots, setSlots] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const allSlots = generateAllSlots(timezone, {
      businessHours,
      slotDurationMinutes,
      daysAhead,
    });
    // 予約窓の全スロットの開始〜終了で上書き（calendarId1 は維持）
    const timeMin = allSlots.length ? allSlots[0].start.toISOString() : new Date().toISOString();
    const timeMax = allSlots.length
      ? allSlots[allSlots.length - 1].end.toISOString()
      : new Date(Date.now() + 48 * 60 * 60 * 1000).toISOString();
    const body = {
      calendarId1: 'drib189@gmail.com',
      calendarId2: 'murayama@conscience-co.jp',
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
  }, [timezone]);

  const handleBooking = (slot) => {
    fetch('/api/create-booking', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        calendarId: 'drib189@gmail.com',
        start: slot.start,
        end: slot.end,
      }),
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
              {formatDateTime(slot.start, timezone)} - {formatDateTime(slot.end, timezone)}
            </li>
          );
          return jsx;
        })}
      </ul>
    </div>
  );
};

CustomerCalendar.propTypes = {
  timezone: PropTypes.string,
  businessHours: PropTypes.shape({
    start: PropTypes.number.isRequired,
    end: PropTypes.number.isRequired,
  }),
  slotDurationMinutes: PropTypes.number,
  daysAhead: PropTypes.number,
};

CustomerCalendar.defaultProps = {
  timezone: DEFAULT_TIMEZONE,
  businessHours: DEFAULT_BUSINESS_HOURS,
  slotDurationMinutes: DEFAULT_SLOT_DURATION_MINUTES,
  daysAhead: DEFAULT_DAYS_AHEAD,
};

export default CustomerCalendar;

// dc-runtime registration
window.CustomerCalendar = CustomerCalendar;