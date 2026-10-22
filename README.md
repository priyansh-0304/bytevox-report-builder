# Show-your-work report builder

Upload a CSV, build a short report from it, share it with a link. Every number has a
**How was this calculated?** panel showing the plain-English description, the equivalent query,
and exactly how many rows were used and left out.

**Stack:** Python 3.10+ · FastAPI · SQLite (standard library) · plain JavaScript (no build step, no CDN).

## Run it (3 commands)

```bash
python3 -m venv .venv && source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:create_app --factory --port 8000          # open http://127.0.0.1:8000
```

Then create an account and upload `sample_data/messy_sales.csv` (3,000 invented rows with blanks, bad
dates, `N/A`, `₹1,200`, a `<script>` tag in a text field, and four deliberately broken lines).
Regenerate it with `python scripts/make_sample_csv.py`.

Tests: `python -m pytest -q` (72 tests, a few seconds).
Settings (environment variables): `RB_DB_PATH`, `RB_MAX_UPLOAD_MB` (default 5), `RB_MAX_ROWS` (default 100000),
`RB_COOKIE_SECURE=1` (set this behind HTTPS).

## What I built

- **Accounts** (email + password, scrypt-hashed, HttpOnly session cookie). Each user sees only their own data.
- **CSV upload** parsed on the server, with a profile: row count, blanks and unreadable values per column,
  inferred types, and every rejected row with its line number and reason.
- **Report builder**: metric (sum / average / count / min / max, optionally split by a category), bar or line
  chart, top-rows table, text note. Add, remove and reorder (drag a block by its ⠿ handle, with a mouse or a finger;
  with the keyboard, focus the handle and press ↑/↓). A report-level date-range filter and category filter apply to
  every block.
- **Show your work** on every metric, chart and table.
- **Share links**: read-only, no sign-in, required expiry (1 hour to 90 days), instant revoke, list of links.
- **Real conditions**: loading / empty / error states, phone-width layout, keyboard use, server-side validation,
  clear messages for too-large / not-CSV / bad-encoding files.
- **My one optional feature: suggested charts.** After an upload the dataset page proposes up to 7 blocks
  (total, average, row count, bars by the best categories, a line over time, a top-10 table) chosen by plain rules
  over the column profile (`app/suggest.py`): no AI, deterministic, each with a one-line reason. Nothing is added
  until you click, and suggestions go through the same validation and engine as hand-made blocks.
- **Also**: delete a dataset (removes its rows, reports and share links), a drag-and-drop upload with a progress bar,
  hover tooltips on charts, a light/dark toggle (follows the system setting until you choose), and a print stylesheet
  so the browser's *Print / PDF* gives a clean report. (That is not a full PDF export feature; I did not count it as
  my optional extra.)
- **Tests**: aggregation and row accounting, bad files, expired link, revoked link, another user's
  dataset/report/links, suggestions, dataset deletion, and the rate limit.

## How my report builder works

**Column types and bad rows.** The file is decoded as UTF-8 (anything else is refused with an instruction to
re-save it), and the delimiter is picked from the header line (`,` `;` tab `|`). For each column, blank-like
values (`""`, `NA`, `N/A`, `null`, `none`, `nan`, `-`) count as *blank*. Of the remaining values, if at least 90%
parse as dates the column is a **date**; else if at least 90% parse as numbers it is a **number** (handles `1,234.50`,
Indian grouping `12,34,567`, and a leading `$ ₹ € £`; `inf`/`nan` are refused); else it is a **category** if it has
at most 50 distinct values and no more than half as many distinct values as rows (minimum 5); otherwise **text**.
Slashed dates are the risky one: if any value has a first part above 12 the column is read DD/MM, if any
second part is above 12 it is read MM/DD, and if it is genuinely ambiguous it is read DD/MM and the profile shows a
warning. Nothing is silently dropped, on two levels. A *row* that cannot be read (wrong number of fields, blank
line, malformed quoting) is **rejected** and listed with its line number and reason; an unclosed quote swallows
the lines after it, so the whole span of lines is reported. A *value* that does not fit its column's type (for
example `abc` in a number column) becomes missing in an otherwise good row and is counted as **unreadable**,
separately from blanks, with sample line numbers.

**From file to screen.** At upload the typed rows are stored once in SQLite, each tagged with its line number in
your original file. A report is just a list of block specs plus a filter, stored as JSON. One function,
`engine.compute_report`, turns specs into numbers. The owner's editor, the chart, the metric, and the public
share page all call that same function, and the browser only draws what the server returns, so the same number
cannot differ between places. Rows are counted in a fixed order: report filter, then rows with no group value,
then rows with a blank or unreadable value, then *used*. The four counts always add up to the file's row count
(a test checks this). The "How was this calculated?" text is built from the same spec that drove the
calculation. The query shown is the SQL equivalent, **for reading**: the numbers are actually computed in Python,
and the panel says so. Sums use `math.fsum` and are rounded to 6 decimals; an empty sum/average/min/max is shown
as "No data", not 0.

**Share links.** A link contains a random 256-bit token. Only its SHA-256 hash is stored, so a leaked database
does not leak working links, and the full link is shown once, when created. Every request to
`/api/shared/<token>` re-checks that the link exists, is not revoked, and has not expired, so revoking works on
the next request. Unknown, expired and revoked links return the identical 404, so probing teaches nothing. The
response contains computed results only: no dataset id, column profile, owner email, or raw file (the original
file is never stored). The owner API needs a session, and every query includes `AND user_id = ?` in the data
layer (`repo.py`), so another user's row cannot be read even if a route forgot to check; "not yours" and "does not
exist" both answer 404. Pages send a strict Content-Security-Policy, `no-store`, `noindex` and `no-referrer`.

**What could still go wrong.** Anyone holding a link can forward it, and a *table* block shows real rows, so don't
put a table of sensitive columns in a shared report. The public endpoint is rate limited per client address
(120 requests a minute, and 20 failed links per 5 minutes) and login is throttled, but both counters live in one
process's memory, so they reset on restart and do not work across several servers; behind a proxy, every visitor can
look like one address unless the proxy headers are configured. Cross-site request protection is the `SameSite=Lax`
cookie plus an Origin-header check, which only applies when the browser sends that header. Types are guessed, so a
small file with a bit of junk can fall back to text (1 bad value in 9 flips a column, at the 90% threshold); `North`
and `north ` are different categories; DD/MM guesses can be wrong (flagged, not fixed). Suggested charts pick the
"main number" by column name (English hint words such as amount, revenue, sales), so a file with unusual names may get
a less useful suggestion; everything can be changed by hand afterwards. Float sums can differ from an accounting
tool in the last decimals. Drag-to-reorder was tested with a real mouse, not on a real touch screen. No email
verification or password reset. Data is not encrypted at rest. SQLite allows one writer at a time.

**What breaks first at 100× larger files** (500 MB, ~10 million rows). First, every report view and every edit loads
the whole dataset into Python and decodes JSON for each row: that is seconds today and minutes plus gigabytes of
RAM at 100×. Second, the upload is read fully into memory (raw bytes, decoded text, parsed rows), and the 5 MB
limit would have to be rethought along with timeouts. Third, row-by-row inserts into SQLite. The fix is to store
columns in a columnar format (DuckDB/Parquet), compute aggregates with real parameterised SQL (identifiers from a
whitelist), stream-parse in a background job with progress, and cache results per report version.

## Decisions and trade-offs

- **Compute in Python, show the SQL equivalent.** Typed rows in SQLite plus Python aggregation avoid building SQL
  from user input at all and make the row accounting exact. Cost: it does not scale (above).
- **Plain JS, no framework or build step.** `git clone` and run; every line is readable. Cost: more manual DOM code.
  Text is only ever inserted with `textContent`/text nodes, so file contents cannot run as HTML.
- **Reordering is drag-and-drop on a ⠿ handle**, with ↑/↓ keys on the focused handle for keyboard users. I wrote it
  with pointer events (no library) instead of the browser's native drag-and-drop, because the native version cannot
  drop into empty space beside a card and does not work by touch. The card lands in the slot nearest the pointer, and
  a blue line shows where. I tested it with a real mouse; I have not tested it on a real touch screen.
- **Suggestions are rules, not AI.** I can explain every rule and the same file always gets the same suggestions.
  Cost: they are only as good as the column names and types.
- **Share links require an expiry** (max 90 days) and show the full link once.
- **404 for everything not yours**, and one shared 404 for every dead link.
- **Rejected vs unreadable**: a bad row is rejected, a bad cell is kept as missing and counted. This keeps usable
  data without hiding the damage.

## What I cut for time

PDF/image export as a real feature (only the print stylesheet); deleting accounts; password reset and email
verification; undo; reports spanning several datasets; pagination of large tables; editing a dataset after upload;
testing drag-to-reorder on real touch devices.

## Hours spent

About [N] hours over two days.

## How I used AI

I used Claude (Anthropic's AI assistant) as a pair programmer. It drafted the backend, frontend, tests and most of
this README from the assignment brief and my follow-up requests. I ran the app and the tests, uploaded files, clicked
through the flows, and sent back screenshots and bug reports. I picked the optional feature (suggested charts) from
options Claude proposed, and I asked for the light/dark toggle and the drag-to-reorder myself.

**Where the AI was wrong, and how it was caught.**

- *Parser accounting.* The first version of the CSV parser reported "2,999 rows read" for a file that actually had
  3,004 lines. Running it on my messy sample and comparing the numbers showed that an unclosed quote made Python's
  `csv` reader swallow the next five lines into one failed record, so those rows were accounted for nowhere. That broke
  my "nothing is silently dropped" rule. I fixed it so a malformed record reports the whole line span
  (`Lines 2206-2211 could not be separated into rows`) and added a test for it.
- *Type-guess threshold.* My first test file had 1 unreadable value in 9, which the 90% rule turned into a text
  column. The failing tests made me notice the threshold's effect on small files, and I documented it above.
- *Python version.* A nested f-string in `engine.py` only works on Python 3.12, but this README promises 3.10+.
  Compiling under Python 3.11 caught it, and it was rewritten.
- *Editor layout.* The first card layout used `height: 100%` inside a CSS grid, so cards overlapped in my browser.
  After that the page also jumped to the top whenever I changed a chart setting, every card replayed its fade-in after
  each edit, and the browser's native drag-and-drop could not drop a card into an empty slot. I found each of these by
  using the app, and each was fixed and re-tested (the drag-and-drop was rewritten with pointer events).

Tests do not catch everything the AI can get wrong; for example, I have not tested drag-to-reorder on a real phone.

## Project layout

```
app/
  main.py            app wiring, security headers, static files
  config.py          settings from environment
  db.py              SQLite schema and connection
  security.py        password hashing, random tokens
  deps.py            DB connection + current-user dependencies
  schemas.py         request validation (pydantic)
  ingest.py          CSV decode, parse, type inference, profile, rejected rows
  engine.py          the ONLY place numbers are computed, plus the explanations
  suggest.py         rule-based suggested blocks for a new dataset
  ratelimit.py       small in-memory rate limiter used by the share endpoint
  repo.py            all SQL; ownership is enforced here
  service.py         builds owner view and shared view from the same engine
  routes_auth.py  routes_datasets.py  routes_reports.py  routes_share.py
  static/            index.html, css/styles.css, js/ (api, dom, charts, blocks, theme, views/*)
tests/               engine, ingest, access/sharing, and extras (suggestions, delete, rate limit) tests
scripts/make_sample_csv.py    sample_data/messy_sales.csv
```