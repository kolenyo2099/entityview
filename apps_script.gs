// Receiver for push.py. Setup, once:
// 1. Open the results Google Sheet → Extensions → Apps Script, paste this file.
// 2. Project Settings → Script properties → add TOKEN = any long random string.
// 3. Deploy → New deployment → Web app. Execute as: Me. Who has access: Anyone.
// 4. Paste the .../exec URL and the TOKEN into the control panel.
// Each pushed CSV replaces the tab with the same name.

function doPost(e) {
  const body = JSON.parse(e.postData.contents);
  const token = PropertiesService.getScriptProperties().getProperty('TOKEN');
  if (!token) return reply({ok: false, error: 'no TOKEN script property found (check the name is exactly TOKEN and it was saved)'});
  if (body.token !== token.trim()) return reply({ok: false, error:
      `token mismatch: sheet has ${token.trim().length} characters, panel sent ${String(body.token).length}`});

  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sh = ss.getSheetByName(body.tab) || ss.insertSheet(body.tab);
  if (body.reset) sh.clearContents();
  const rows = body.rows;
  if (rows.length) {
    const width = Math.max(...rows.map(r => r.length));
    const values = rows.map(r => r.concat(Array(width - r.length).fill(''))
                                  .map(v => String(v).startsWith('=') ? "'" + v : v));  // no formula injection from article text
    const range = sh.getRange(sh.getLastRow() + 1, 1, values.length, width);
    range.offset(0, 0, values.length, 1).setNumberFormat('@');  // ids stay text ("12e45" is not a number)
    range.setValues(values);
  }
  return reply({ok: true, rows: rows.length});
}

function reply(o) {
  return ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON);
}
