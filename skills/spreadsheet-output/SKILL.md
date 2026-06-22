---
name: spreadsheet-output
description: Formatting rules for generating CSV and XLSX files that render cleanly in the Gumloop spreadsheet viewer. Activate when creating, exporting, or transforming tabular data files.
icon: table
color: Green
---

# Spreadsheet Output

Rules for producing CSV and XLSX files that render correctly in the artifact spreadsheet viewer. The viewer has specific parsing behavior that silently breaks tables when the data doesn't follow these conventions.

## When to Apply

Activate this skill when:

- Creating CSV or XLSX files for user consumption
- Transforming or reshaping data into tabular output
- Exporting query results, reports, or structured data
- Any time the output will be downloaded via `sandbox_download` as a `.csv` or `.xlsx` file

## Format Decision Framework

Choose the right format before writing any data:

| Scenario | Format | Why |
|---|---|---|
| Single homogeneous table | CSV | Simpler, smaller, universally supported |
| 2+ logical tables with different column schemas | XLSX with separate sheets | CSV has no tab/sheet support; sections get mashed into one broken table |
| Related data needing cross-reference (e.g., orders + customers) | XLSX with named sheets | Each sheet gets its own clean header row and tab in the viewer |
| Quick data dump or single query result | CSV | Minimal overhead |

**Rule of thumb:** If you would need blank rows or `=== SECTION ===` separators in a CSV, use XLSX with separate sheets instead.

## Rule Categories

| Priority | Category | Impact |
|---|---|---|
| 1 | Header Row | CRITICAL |
| 2 | Row Structure | CRITICAL |
| 3 | Multi-Table Data | HIGH |
| 4 | Cell Values | HIGH |
| 5 | Column Design | MEDIUM |
| 6 | Sorting & Search | MEDIUM |
| 7 | XLSX-Specific | MEDIUM |
| 8 | Size & Limits | LOW |

### 1. Header Row (CRITICAL)

The viewer uses `rawRows[0]` as column headers. Everything after row 0 is data. No exceptions.

- `header-row-first` -- Row 1 MUST be column headers. A title row like `=== Sales Report ===` becomes the only column header, pushing real headers into data rows.
- `header-no-duplicates` -- Duplicate column names get "(2)", "(3)" suffixes automatically. Use unique, descriptive names.
- `header-match-data-width` -- The header row must have at least as many fields as the widest data row. The viewer computes `maxCols` across ALL rows and fills missing headers with "Column N".
- `header-no-empty` -- Empty string headers become "Column N" because the fallback uses `||` (falsy check). Always provide a meaningful name.
- `header-short-descriptive` -- Headers are used as sort labels, column visibility toggles, and clipboard copy keys. Keep them short but descriptive.

```python
# BAD -- title row before headers
writer.writerow(["=== Monthly Revenue Report ==="])
writer.writerow(["Month", "Revenue", "Growth"])
writer.writerow(["Jan", "120000", "5%"])

# GOOD -- headers first, always
writer.writerow(["Month", "Revenue", "Growth"])
writer.writerow(["Jan", "120000", "5%"])
```

### 2. Row Structure (CRITICAL)

The CSV parser treats every `\n` as a row boundary. There is zero section detection or blank-row filtering.

- `row-no-blanks` -- Blank rows render as empty data rows in the grid. Never use blank lines as separators.
- `row-no-section-headers` -- Text like `=== SECTION ===` lands in cells as raw strings. Use XLSX sheets instead.
- `row-consistent-width` -- Every row should have the same number of fields as the header. Shorter rows get empty cells; wider rows force extra "Column N" headers to appear.
- `row-no-trailing-newline` -- A trailing `\n\n` creates an empty data row at the bottom. Strip trailing newlines.
- `row-sorted-default` -- Pre-sort data in a sensible default order. The viewer supports re-sorting by column, but good defaults matter.

```python
# BAD -- blank rows and section separators
writer.writerow(["Conference", "Team", "Wins"])
writer.writerow(["East", "Celtics", "64"])
writer.writerow([])  # blank row = empty data row in viewer
writer.writerow(["=== Western Conference ==="])  # lands in cells as text
writer.writerow(["West", "Thunder", "68"])

# GOOD -- flat table, no separators
writer.writerow(["Conference", "Team", "Wins"])
writer.writerow(["East", "Celtics", "64"])
writer.writerow(["West", "Thunder", "68"])
```

### 3. Multi-Table Data (HIGH)

CSV always renders as a single sheet. XLSX renders with clickable sheet tabs when there are 2+ sheets.

- `multi-table-use-xlsx` -- Multiple logical tables with different schemas MUST use XLSX with separate sheets. Never cram multiple tables into one CSV.
- `multi-table-sheet-names` -- Use meaningful sheet names. They appear as clickable tabs. The tab UI only appears when there are 2+ sheets.
- `multi-table-per-sheet-rules` -- Each sheet follows the same rules (row 1 = headers, consistent width, no blanks).

```python
# BAD -- multiple tables crammed into one CSV
writer.writerow(["=== Standings ==="])
writer.writerow(["Team", "Wins", "Losses"])
writer.writerow(["Celtics", "64", "18"])
writer.writerow([])
writer.writerow(["=== Leaders ==="])
writer.writerow(["Category", "Player", "Value"])
writer.writerow(["Points", "SGA", "32.7"])

# GOOD -- XLSX with separate sheets
import openpyxl
wb = openpyxl.Workbook()

ws1 = wb.active
ws1.title = "Standings"
ws1.append(["Team", "Wins", "Losses"])
ws1.append(["Celtics", "64", "18"])

ws2 = wb.create_sheet("Leaders")
ws2.append(["Category", "Player", "Value"])
ws2.append(["Points", "SGA", "32.7"])

wb.save("season_summary.xlsx")
```

```python
# GOOD -- pandas ExcelWriter for multiple DataFrames
with pd.ExcelWriter("report.xlsx", engine="openpyxl") as writer:
    standings_df.to_excel(writer, sheet_name="Standings", index=False)
    leaders_df.to_excel(writer, sheet_name="Leaders", index=False)
    awards_df.to_excel(writer, sheet_name="Awards", index=False)
```

### 4. Cell Values (HIGH)

All cell values are stored as strings. No type detection, no formatting.

- `cell-no-formula-prefix` -- Avoid starting cells with `=`, `+`, `-`, `@`, `\t`, `\r`. The viewer's CSV export escapes these with a leading apostrophe `'`, which shows in the exported file.
- `cell-quote-special` -- Quote fields containing commas, newlines, or double quotes per RFC 4180. Python's `csv.writer` handles this automatically.
- `cell-consistent-types` -- Don't mix sentinel strings with data in the same column. Use empty string `""` for missing values, not "N/A", "null", or "None".
- `cell-format-dates-as-strings` -- XLSX date serial numbers are NOT converted by the viewer. A date cell shows as "45306" instead of "2024-01-15". Always write dates as pre-formatted strings.
- `cell-format-numbers-as-display` -- XLSX number formatting is ignored. Percentages (0.5), currency ($1,234) show as raw values. Write the display string directly.

```python
# BAD -- datetime objects in XLSX (viewer shows serial numbers)
from datetime import datetime
ws.append([datetime(2024, 1, 15), 0.5, 1234.56])
# Viewer shows: 45306 | 0.5 | 1234.56

# GOOD -- pre-formatted strings
ws.append(["2024-01-15", "50%", "$1,234.56"])
# Viewer shows: 2024-01-15 | 50% | $1,234.56
```

```python
# BAD -- mixed missing value representations
writer.writerow(["Alice", "95", "A"])
writer.writerow(["Bob", "N/A", "null"])  # inconsistent sentinels
writer.writerow(["Carol", "None", ""])

# GOOD -- empty string for missing values
writer.writerow(["Alice", "95", "A"])
writer.writerow(["Bob", "", ""])
writer.writerow(["Carol", "", ""])
```

### 5. Column Design (MEDIUM)

Column headers are used as TanStack Table column IDs, sort keys, visibility toggle labels, and clipboard copy keys.

- `col-unique-names` -- Every column header must be unique. The viewer deduplicates with "(2)", "(3)" suffixes which look ugly.
- `col-no-index-only` -- Don't add a bare row-number column. The viewer already shows 1-indexed row numbers in a sticky leftmost gutter.
- `col-logical-order` -- Put identifying columns (name, ID, category) first, then metrics/values. Users scan left-to-right.
- `col-no-colon-in-header` -- Avoid `:` in column headers. The cell selection system uses `rowIndex:columnId` as cell keys and splits on the first `:`.

```python
# BAD -- pandas default index column
df.to_csv("output.csv")  # includes unnamed index column
# Viewer shows: "Column 1" (empty header) | Name | Score

# GOOD -- no index
df.to_csv("output.csv", index=False)
# Viewer shows: Name | Score
```

### 6. Sorting & Search (MEDIUM)

Sorting is string-based (TanStack Table default). Search is case-insensitive substring matching.

- `sort-aware-values` -- "9" sorts AFTER "10" alphabetically. For numeric columns that users will sort, pre-sort the data or use zero-padding.
- `search-friendly-values` -- Use human-readable values, not encoded IDs. Search checks `value.toLowerCase().includes(query)` across all visible cells.
- `sort-default-sensible` -- Pre-sort data in the most useful default order.

```python
# BAD -- numeric strings that sort wrong
# Sorted: 1, 10, 2, 20, 3
rows = [["1", "Alice"], ["2", "Bob"], ["10", "Carol"], ["3", "Dave"], ["20", "Eve"]]

# GOOD -- pre-sort the data before writing
rows.sort(key=lambda r: int(r[0]))
# Written order: 1, 2, 3, 10, 20 (correct default view)
```

### 7. XLSX-Specific (MEDIUM)

The XLSX parser extracts raw cell values from the XML. It skips styles, formulas, charts, and all non-data content.

- `xlsx-no-formulas` -- The viewer reads `<v>` element content only. Formula cells show cached values or empty strings.
- `xlsx-no-styling` -- All styling (colors, fonts, borders, conditional formatting) is completely ignored.
- `xlsx-dates-as-strings` -- Write dates as pre-formatted strings, not Excel date serial numbers. The parser has no date conversion logic.
- `xlsx-numbers-as-display` -- Write number values as display strings. Percentage formatting, currency symbols, decimal places must be in the cell value itself.
- `xlsx-use-openpyxl` -- Use openpyxl or xlsxwriter (both available in the sandbox). When writing with openpyxl, pass string values to avoid unintended type coercion.

### 8. Size & Limits (LOW)

- `size-under-50mb` -- Files over 50 MB skip inline preview and show a download prompt. Keep spreadsheet files well under this limit.
- `size-reasonable-rows` -- Very large spreadsheets (100k+ rows) work with virtualization but may be slow to parse and sort. Consider summary tables for large datasets.

## Common Mistakes

| Mistake | What Happens in Viewer | Fix |
|---|---|---|
| Title row before headers | Title becomes the only column header; real headers appear as data | Remove title, start with data headers |
| Blank rows between sections | Empty data rows in the grid | Use XLSX sheets for sections |
| Duplicate column names | "(2)", "(3)" suffixes on headers | Use unique names |
| Jagged row widths | Extra "Column N" fallback names appear | Pad all rows to consistent width |
| Empty string header | Becomes "Column N" | Always provide meaningful header names |
| Formula-prefix characters (`=`, `+`, `-`, `@`) | Escaped with `'` on CSV export | Restructure data or prefix with space |
| `to_csv(index=True)` | Unlabeled first column (empty header becomes "Column 1") | Use `index=False` |
| Styling/formatting in XLSX | Completely ignored | Don't bother with styling |
| Section separators in CSV | Raw text in data cells | Use XLSX with named sheets |
| Excel date serial numbers in XLSX | Shows "45306" instead of "2024-01-15" | Format dates as strings before writing |
| Unformatted numbers in XLSX | Shows "0.5" instead of "50%" | Write display strings: "50%", "$1,234" |
| Trailing blank line in CSV | Empty data row at the bottom of the grid | Strip trailing newlines from output |
| Colon `:` in column header | Can break cell selection keyboard nav | Avoid colons in header names |
| Numeric columns without pre-sorting | "9" sorts after "10" (string sort) | Pre-sort data before writing |

## Review Checklist

```
Before exporting any CSV/XLSX:
- [ ] Row 1 is column headers (no title rows, no metadata, no blank rows above)
- [ ] All headers are non-empty strings (no "" headers)
- [ ] All headers are unique (no duplicates)
- [ ] All headers avoid colons (:)
- [ ] All rows have the same number of fields as the header row
- [ ] No blank rows anywhere in the data
- [ ] No section separator rows (=== TITLE === etc.)
- [ ] No trailing blank lines
- [ ] No unnecessary index/row-number column (viewer provides one)
- [ ] Data sorted in a sensible default order
- [ ] If multiple tables: using XLSX with separate sheets
- [ ] If XLSX: sheet names are meaningful
- [ ] If XLSX: dates written as formatted strings, not serial numbers
- [ ] If XLSX: numbers include display formatting ("50%" not 0.5)
- [ ] No cells starting with = + - @ unless intentional
- [ ] Using UTF-8 encoding, no BOM
- [ ] File size well under 50 MB
```
