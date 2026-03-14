# Insurance Sales Report — Documentation

**File:** `Insurance_Sales_Report.xlsx`
**Location:** `/AAA/Insurance/Insurance_Sales_Report.xlsx`
**Generated:** March 2026
**Data Period:** January 2025 – February 2026 (14 months)

---

## 1. Data Source

**Salesforce Org:** Production (`aaawcny.my.salesforce.com`)
**API User:** `apiintegration@nyaaa.com`
**Connection:** OAuth2 via `sf_client.py` (rate limiter + circuit breaker + connection pooling)
**Cached Data:** `/tmp/insurance_opps.json` (27,611 records), `/tmp/insurance_leads.json` (34,976 records)

### Salesforce Objects Queried

#### Opportunities (Insurance)
```sql
SELECT Owner.Name, StageName, Amount, CreatedDate, CloseDate
FROM Opportunity
WHERE RecordType.DeveloperName = 'Insurance'
  AND CreatedDate >= 2025-01-01T00:00:00Z
  AND CreatedDate < 2026-03-01T00:00:00Z
```

**Fields Used:**
| Field | Object | Purpose |
|-------|--------|---------|
| `Owner.Name` | Opportunity | Agent name for attribution |
| `StageName` | Opportunity | Determines if opportunity is "Closed Won" (Invoiced) |
| `Amount` | Opportunity | Sales revenue (summed for Invoiced/Closed Won records) |
| `CreatedDate` | Opportunity | Month grouping for Opportunities count |
| `CloseDate` | Opportunity | Month grouping for Invoiced count and Sales revenue |
| `RecordType.DeveloperName` | Opportunity | Filter: must equal `'Insurance'` |

**Metric Definitions:**
- **Opportunities** = Count of all Opportunity records, grouped by `CreatedDate` month
- **Invoiced** = Count of Opportunity records where `StageName = 'Closed Won'`, grouped by `CloseDate` month
- **Sales** = SUM of `Amount` on Closed Won Opportunities, grouped by `CloseDate` month
- **Inv/Opp %** = Invoiced / Opportunities (close rate)

#### Leads (Insurance)
```sql
SELECT Owner.Name, CreatedDate
FROM Lead
WHERE RecordType.DeveloperName = 'Insurance'
  AND CreatedDate >= 2025-01-01T00:00:00Z
  AND CreatedDate < 2026-03-01T00:00:00Z
```

**Fields Used:**
| Field | Object | Purpose |
|-------|--------|---------|
| `Owner.Name` | Lead | Agent name for attribution |
| `CreatedDate` | Lead | Month grouping for Leads count |
| `RecordType.DeveloperName` | Lead | Filter: must equal `'Insurance'` |

**Metric Definitions:**
- **Leads** = Count of Lead records, grouped by `CreatedDate` month

---

## 2. Report Structure (7 Sheets)

Format is identical to the Travel Sales Report. Only the data and division name differ.

### Sheet 1: Executive Summary (114 rows x 9 columns)

#### Section A — Title (Row 1)
- Merged A1:H1
- Text: `INSURANCE DIVISION — EXECUTIVE SUMMARY`
- Font: Calibri 16pt, Bold, Color `#1F3864` (dark blue)

#### Section B — Quarterly Performance Overview (Rows 3–10)
- Section header at R3 (merged A3:H3): `QUARTERLY PERFORMANCE OVERVIEW`
  - Font: Calibri 12pt, Bold, Color `#1F3864`
- Column headers at R4: `Quarter | Leads | Opportunities | Invoiced | Inv/Opp % | Sales`
  - Font: Calibri 10pt, Bold, White (`#FFFFFF`)
  - Fill: Dark blue `#1F3864`
- Data rows R5–R9: Q1 2025 through Q1 2026
  - Zebra striping: alternating rows with light blue fill `#D6E4F0`
  - Sales column: number format `\$#,##0`
  - Inv/Opp %: number format `0.0%`
- R10: **TOTAL** row
  - Font: Calibri 10pt, Bold, White
  - Fill: Dark blue `#1F3864`
  - Sums all quarterly data

#### Section C — Year-over-Year Comparison (Rows 12–17)
- Section header at R12 (merged A12:H12): `YEAR-OVER-YEAR: JAN-FEB 2025 vs JAN-FEB 2026`
  - Font: Calibri 12pt, Bold, Color `#1F3864`
- Column headers at R13: `Metric | Jan-Feb 2025 | Jan-Feb 2026 | Change | % Change | Insight`
  - Font: Calibri 10pt, Bold, White
  - Fill: Dark blue `#1F3864`
- Data rows R14–R17: Leads, Opportunities (Created), Invoiced (Closed), Sales Revenue
  - % Change format: `+0.0%;-0.0%`
  - Conditional formatting:
    - Positive change: Green fill `#C6EFCE`, font `#006100`
    - Negative change: Red fill `#FFC7CE`, font `#9C0006`
  - Insight column: text explanation of the trend

#### Section D — Key Takeaway Banner (Row 19)
- Merged A19:H19
- Green banner: Fill `#C6EFCE`, Font `#006100`, Calibri 10pt Bold
- Text explains the overall narrative for Insurance division

#### Section E — Top 20 Performers (Rows 21–42)
- Section header at R21 (merged A21:H21): `TOP 20 PERFORMERS — 2025 FULL YEAR`
  - Font: Calibri 12pt, Bold, Color `#1F3864`
- Column headers at R22: `# | Agent | Leads | Opportunities | Invoiced | Inv/Opp % | Sales`
  - Font: Calibri 10pt, Bold, White
  - Fill: Dark blue `#1F3864`
- Data rows R23–R42: Top 20 agents ranked by total 2025 Sales
  - Zebra striping with `#D6E4F0`
  - Sales column in green fill `#E2EFDA`, format `\$#,##0`

#### Section F — Charts (embedded between sections)
1. **Bar Chart: "Sales Revenue by Quarter"** — anchored at column G, row 3
   - 1 series (Sales by quarter)
2. **Bar Chart: "Top 20 Agents — 2025 Sales"** — anchored at column H, row 27
   - 1 series (Total sales per agent)

#### Section G — Agent Productivity Dashboard (Rows 61–114)
- Section header at R61 (merged A61:I61): `AGENT PRODUCTIVITY DASHBOARD — 2025`
  - Font: Calibri 12pt, Bold, Color `#1F3864`
- Column headers at R62: `# | Agent | Avg Mo Leads | Avg Mo Opps | Avg Mo Invoiced | Close Rate | Avg Mo Sales | Total Sales | Tier`
  - Font: Calibri 10pt, Bold, White
  - Fill: Dark blue `#1F3864`
- Data rows R63–R114: ALL 52 agents ranked by Total Sales
  - Avg Mo = metric / 12 (full year 2025 = 12 months)
  - Close Rate = Total Invoiced / Total Opportunities
  - Tier system:
    - **Elite** (~top 13%): highest revenue agents
    - **High** (~top 38%): above-average performers
    - **Mid** (~top 58%): middle of the pack
    - **Developing** (~top 78%): below-average but active
    - **Low** (remaining): minimal activity
  - Zebra striping with `#D6E4F0`
  - Sales columns: green fill `#E2EFDA`, format `\$#,##0`

---

### Sheets 2–5: Quarterly Detail (Q1 2025, Q2 2025, Q3 2025, Q4 2025)

Each quarterly sheet has 22 columns covering 3 months + quarter total.

#### Layout
- **Row 1:** Title (merged across all columns)
  - Text: `Insurance Sales — Q# 2025`
  - Font: Calibri 14pt, Bold, Color `#1F3864`
- **Row 2:** Month group headers (merged per 5-column group)
  - Columns C–G: `Mon YY` (e.g., "Jan 25") — Fill: Medium blue `#2F5496`, Font: Calibri 11pt Bold White
  - Columns H–L: 2nd month — same format
  - Columns M–Q: 3rd month — same format
  - Columns R–V: `Q# 2025 Total` — Fill: **Dark blue `#1F3864`**, Font: Calibri 11pt Bold White
  - Columns A–B: `#` and `Agent` — Fill: Dark blue `#1F3864`
- **Row 3:** Sub-headers (repeated per month group)
  - `Leads | Opps | Invoiced | Inv/Opp % | Sales`
  - Font: Calibri 10pt, Bold, White
  - Fill: Dark blue `#1F3864`
- **Rows 4–N:** Agent data (ALL agents with any activity, sorted by total sales descending)
  - Zebra striping: odd rows `#D6E4F0`, even rows white
  - Sales columns (C7, C12, C17, C22): green fill `#E2EFDA`, format `\$#,##0`
  - Inv/Opp %: format `0.0%`
  - Quarter total Sales (C22): Font Calibri 10pt **Bold**
- **Last Row:** **TOTAL** row
  - Font: Calibri 10pt, Bold, White
  - Fill: Dark blue `#1F3864`
  - Sums: monthly Leads, Opps, Invoiced, Sales + quarter totals
  - Sales format: `\$#,##0`

#### Agent Counts per Quarter
| Sheet | Agents | TOTAL Row |
|-------|--------|-----------|
| Q1 2025 | 59 | Row 63 |
| Q2 2025 | 66 | Row 70 |
| Q3 2025 | 58 | Row 62 |
| Q4 2025 | 54 | Row 58 |
| Q1 2026 | 48 | Row 52 |

#### Column Structure (22 columns)
| Col | Header | Content |
|-----|--------|---------|
| A | # | Rank number |
| B | Agent | Agent name |
| C | Leads | Month 1 lead count |
| D | Opps | Month 1 opportunity count |
| E | Invoiced | Month 1 closed won count |
| F | Inv/Opp % | Month 1 close rate |
| G | Sales | Month 1 revenue |
| H–L | | Month 2 (same 5 metrics) |
| M–Q | | Month 3 (same 5 metrics) |
| R–V | | Quarter Total (same 5 metrics) |

---

### Sheet 6: Q1 2026 (Partial Quarter)

Same format as quarterly sheets but only **2 months** (Jan 26, Feb 26) + Quarter Total.
- 17 columns (not 22) since only 2 months of data
- Merged headers: C–G (Jan 26), H–L (Feb 26), M–Q (Q1 2026 Total)

---

### Sheet 7: Trends (16 rows + 2 charts)

#### Data Table (Rows 1–16)
- **Row 1:** Title: `Monthly Trends — Jan 2025 to Feb 2026`
  - Font: Calibri 14pt, Bold, Color `#1F3864`
- **Row 2:** Headers: `Month | Leads | Opportunities | Invoiced | Inv/Opp % | Sales`
  - Font: Calibri 10pt, Bold, White
  - Fill: Dark blue `#1F3864`
- **Rows 3–16:** Monthly data (14 months)
  - Zebra striping with `#D6E4F0`
  - Sales: format `\$#,##0`, green fill `#E2EFDA`
  - Inv/Opp %: format `0.0%`

#### Charts
1. **Line Chart: "Volume: Leads -> Opps -> Invoiced"** — anchored at row 17
   - 3 series: Leads, Opportunities, Invoiced over 14 months
2. **Line Chart: "Monthly Sales Revenue"** — anchored at row 34
   - 1 series: Sales revenue over 14 months

---

## 3. Formatting Reference

### Color Palette
| Name | Hex | Usage |
|------|-----|-------|
| Dark Blue | `#1F3864` | Headers, TOTAL rows, section titles |
| Medium Blue | `#2F5496` | Monthly group headers (Row 2 on quarterly sheets) |
| Zebra Blue | `#D6E4F0` | Alternating data row background |
| Sales Green | `#E2EFDA` | Sales/revenue column background |
| Conditional Green | `#C6EFCE` fill / `#006100` font | Positive YoY change, Key Takeaway banner |
| Conditional Red | `#FFC7CE` fill / `#9C0006` font | Negative YoY change |
| White | `#FFFFFF` | Header text, TOTAL row text |

### Number Formats
| Format | Usage |
|--------|-------|
| `\$#,##0` | All dollar amounts (Sales columns) |
| `0.0%` | Inv/Opp %, Close Rate |
| `+0.0%;-0.0%` | YoY % Change column |
| `General` | Counts (Leads, Opps, Invoiced), rank numbers |

### Fonts
| Context | Font | Size | Bold | Color |
|---------|------|------|------|-------|
| Sheet title (R1) | Calibri | 14–16pt | Yes | `#1F3864` |
| Section headers | Calibri | 12pt | Yes | `#1F3864` |
| Column headers | Calibri | 10pt | Yes | White |
| Month group headers | Calibri | 11pt | Yes | White |
| Data cells | Calibri | 11pt | No | Default |
| TOTAL row | Calibri | 10pt | Yes | White |
| Quarter total Sales | Calibri | 10pt | Yes | Default |

---

## 4. Key Data Points

- **Total Agents:** 52 (all with at least one Opportunity in 2025)
- **Total Opportunity Records:** 27,611
- **Total Lead Records:** 34,976
- **Date Range:** Jan 2025 – Feb 2026
- **Total 2025 Sales:** ~$13.9M
- **Top Agent (2025):** Karl Osterman
- **YoY Trend (Jan-Feb):**
  - Leads: decreased (fewer leads coming in Jan-Feb 2026 vs 2025)
  - Opportunities: decreased
  - Invoiced: +30% increase — more deals closing
  - Revenue: +120% increase — significantly higher revenue per closed deal
- **Key Insight:** Insurance division is closing MORE deals at HIGHER values despite fewer leads/opportunities, indicating improved sales quality and higher-value policies
