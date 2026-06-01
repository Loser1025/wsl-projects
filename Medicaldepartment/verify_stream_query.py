import sys, io, requests, subprocess
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

GCLOUD_PATH = r"C:\Users\Loser\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.ps1"
BQ_PROJECT  = "stream-443709"

def get_token():
    r = subprocess.run(["powershell", "-NoProfile", "-Command", f"& '{GCLOUD_PATH}' auth print-access-token"],
        capture_output=True, text=True, encoding="utf-8")
    return r.stdout.strip()

def bq_query(sql, token):
    url  = f"https://bigquery.googleapis.com/bigquery/v2/projects/{BQ_PROJECT}/queries"
    resp = requests.post(url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"query": sql, "useLegacySql": False, "timeoutMs": 60000, "maxResults": 500})
    data = resp.json()
    if not resp.ok:
        raise RuntimeError(data)
    fields = [f["name"] for f in data.get("schema", {}).get("fields", [])]
    return [{fields[i]: r["f"][i].get("v") for i in range(len(fields))} for r in data.get("rows", [])]

token = get_token()

# 当月1日以降の件数確認
print("=== 当月（2026/05/01〜）の契約件数 ===")
r3 = bq_query("""
SELECT COUNT(*) as cnt
FROM `stream-443709.stream.contracts` con
JOIN `stream-443709.stream.clients` c ON c.id = con.client_id
WHERE c.source_code = 'RKR'
  AND DATE(con.contracted_at, 'Asia/Tokyo') >= DATE_TRUNC(CURRENT_DATE('Asia/Tokyo'), MONTH)
  AND con.canceled_at IS NULL
""", token)
print(f"  件数: {r3[0]['cnt']}")

# シートの既存データと照合（patient_id=189048）
print("\n=== シート既存行の照合（source_id=189048）===")
r2 = bq_query("""
SELECT
  FORMAT_TIMESTAMP('%Y/%m/%d', con.contracted_at, 'Asia/Tokyo') AS contracted_date,
  CAST(c.source_id AS STRING) AS patient_id,
  CONCAT(c.last_name, ' ', c.first_name) AS name,
  pc.name AS product_class,
  con.menu_name AS menu_name,
  CAST(con.contract_amount AS STRING) AS amount
FROM `stream-443709.stream.contracts` con
JOIN `stream-443709.stream.clients` c ON c.id = con.client_id
LEFT JOIN `stream-443709.stream.product_classes` pc ON pc.id = con.product_class_id
WHERE c.source_id = 189048 AND c.source_code = 'RKR'
  AND DATE(con.contracted_at, 'Asia/Tokyo') = '2026-05-21'
ORDER BY con.contracted_at
""", token)
for row in r2:
    print(f"  契約日={row['contracted_date']} | 患者ID={row['patient_id']} | 名前={row['name']} | 商材={row['product_class']} | メニュー={row['menu_name']} | 金額={row['amount']}")

# 当月サンプル5件
print("\n=== 当月契約サンプル（先頭5件）===")
r4 = bq_query("""
SELECT
  FORMAT_TIMESTAMP('%Y/%m/%d', con.contracted_at, 'Asia/Tokyo') AS contracted_date,
  CAST(c.source_id AS STRING) AS patient_id,
  CONCAT(c.last_name, ' ', c.first_name) AS name,
  pc.name AS product_class,
  con.menu_name AS menu_name,
  CAST(con.contract_amount AS STRING) AS amount
FROM `stream-443709.stream.contracts` con
JOIN `stream-443709.stream.clients` c ON c.id = con.client_id
LEFT JOIN `stream-443709.stream.product_classes` pc ON pc.id = con.product_class_id
WHERE c.source_code = 'RKR'
  AND DATE(con.contracted_at, 'Asia/Tokyo') >= DATE_TRUNC(CURRENT_DATE('Asia/Tokyo'), MONTH)
  AND con.canceled_at IS NULL
ORDER BY con.contracted_at
LIMIT 5
""", token)
for row in r4:
    print(f"  {row['contracted_date']} | {row['patient_id']} | {row['name']} | {row['product_class']} | {row['menu_name']} | {row['amount']}")
