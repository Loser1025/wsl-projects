import React, { useState } from 'react';

const CustomerCalendar = () => {
  const [selectedDate, setSelectedDate] = useState('');

  const handleBooking = async () => {
    const response = await fetch('/api/create-booking', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ 
        customerName: 'Guest', 
        date: selectedDate, 
        time: '10:00' 
      }),
    });
    const data = await response.json();
    if (data.success) alert('予約が完了しました！');
  };

  return (
    <div className="p-4 border rounded shadow">
      <h2 className="text-xl font-bold mb-4">顧客カレンダー</h2>
      <input 
        type="date" 
        onChange={(e) => setSelectedDate(e.target.value)}
        className="border p-2 mb-4 w-full"
      />
      <button 
        onClick={handleBooking}
        className="bg-blue-500 text-white px-4 py-2 rounded"
      >
        予約する
      </button>
    </div>
  );
};

export default CustomerCalendar;
