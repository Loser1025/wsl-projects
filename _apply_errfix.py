# -*- coding: utf-8 -*-
import io, sys

path = "/home/loser/wsl-projects/mission-control-v2/src/components/Calendar/CustomerCalendar.jsx"

with io.open(path, "r", encoding="utf-8") as f:
    src = f.read()

old = """  useEffect(() => {
    fetch('/api/get-availability', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    })
      .then(res => res.json())
      .then(data => {
        setSlots(data.slots || []);
        setLoading(false);
      })
      .catch(err => {
        setError('空き枠の取得に失敗しました。');
        setLoading(false);
      });
  }, []);"""

new = """  useEffect(() => {
    fetch('/api/get-availability', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
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
        setSlots(data.slots || []);
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
          err && err.body ? '\\n応答本文:\\n' + err.body : ''
        );
        setError(message);
        setLoading(false);
      });
  }, []);"""

if old not in src:
    sys.stderr.write("OLD BLOCK NOT FOUND\\n")
    sys.exit(1)

src = src.replace(old, new, 1)

with io.open(path, "w", encoding="utf-8") as f:
    f.write(src)

print("OK: replaced")
