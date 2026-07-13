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
        if (!res.ok) {
          const msg = bodyText
            ? `API error ${res.status}: ${bodyText.slice(0, 200)}`
            : `API error ${res.status}`;
          throw new Error(msg);
        }
        let data;
        try {
          data = JSON.parse(bodyText);
        } catch (parseErr) {
          throw new Error(`JSON parse error: ${parseErr.message}`);
        }
        const busyData = data.calendarId1 ?? data;
        const busySet = new Set();
        Object.entries(busyData).forEach(([calId, calData]) => {
          if (calData && Array.isArray(calData.busy)) {
            calData.busy.forEach((b) => busySet.add(`${b.start}|${b.end}`));
          }
        });
        const freeSlots = allSlots.filter(
          (s) => !busySet.has(`${s.start.toISOString()}|${s.end.toISOString()}`)
        );
        setSlots(freeSlots);
      })
      .catch((e) => {
        console.error('Availability fetch failed:', e);
        setError(e.message);
      })
      .finally(() => setLoading(false));
  }, [timezone, businessHours, slotDurationMinutes, daysAhead]);

  if (loading) return <div className="p-4">読み込み中…</div>;
  if (error) return <div className="p-4 text-red-600">エラー: {error}</div>;

  return (
    <div className="p-4 border rounded shadow">
      <h2 className="text-xl font-bold mb-4">予約可能スロット</h2>
      {slots.length === 0 ? (
        <p className="text-gray-600">予約可能なスロットがありません</p>
      ) : (
        <ul className="space-y-2">
          {slots.map((slot) => (
            <li key={`${slot.start.toISOString()}|${slot.end.toISOString()}`} className="border p-2 rounded">
              <div className="font-medium">
                {formatDateTime(slot.start, timezone)} 〜 {formatTime(slot.end, timezone)}
              </div>
            </li>
          ))}
        </ul>
      )}
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