/**
 * BigQuery Advanced Service（要有効化）を使ってSQLを実行し、
 * 結果を { フィールド名: 値(文字列) } の配列として返す。
 * ページングにも対応。
 */
function runBigQuery_(sql) {
  var projectId = CONFIG.BQ_PROJECT;
  var queryResults = BigQuery.Jobs.query({ query: sql, useLegacySql: false }, projectId);
  var jobId = queryResults.jobReference.jobId;

  while (!queryResults.jobComplete) {
    Utilities.sleep(1000);
    queryResults = BigQuery.Jobs.getQueryResults(projectId, jobId);
  }

  var fields = queryResults.schema.fields.map(function (f) { return f.name; });
  var rows = [];
  var page = queryResults;
  var pageToken = null;

  do {
    if (page.rows) {
      page.rows.forEach(function (row) {
        var obj = {};
        row.f.forEach(function (cell, i) {
          obj[fields[i]] = cell.v;
        });
        rows.push(obj);
      });
    }
    pageToken = page.pageToken;
    if (pageToken) {
      page = BigQuery.Jobs.getQueryResults(projectId, jobId, { pageToken: pageToken });
    }
  } while (pageToken);

  return rows;
}
