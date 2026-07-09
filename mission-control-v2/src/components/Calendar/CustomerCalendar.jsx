import React, { useState, useEffect } from 'react';

const CustomerCalendar = () => {
  const [slots, setSlots] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetch('/api/get-availability')
      .then(res => res.json())
      .then(data => {
        setSlots(data.slots || []);
        setLoading(false);
      })
      .catch(err => {
        setError('空き枠の取得に失敗しました。');
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
