#!/usr/bin/env python3
"""Generate Fleet Optimization Findings PDF report."""
from fpdf import FPDF
from datetime import datetime

class Report(FPDF):
    def header(self):
        self.set_font('Helvetica', 'B', 10)
        self.set_text_color(100, 100, 100)
        self.cell(0, 8, 'AAA WCNY - Fleet Optimization Report', align='R')
        self.ln(4)
        self.set_draw_color(0, 102, 204)
        self.set_line_width(0.5)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(6)

    def footer(self):
        self.set_y(-15)
        self.set_font('Helvetica', 'I', 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 10, f'Page {self.page_no()}/{{nb}}  |  Generated {datetime.now().strftime("%B %d, %Y")}  |  Confidential', align='C')

    def section_title(self, title):
        self.set_font('Helvetica', 'B', 14)
        self.set_text_color(0, 51, 102)
        self.cell(0, 10, title, new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(0, 102, 204)
        self.set_line_width(0.3)
        self.line(10, self.get_y(), 100, self.get_y())
        self.ln(4)

    def sub_title(self, title):
        self.set_font('Helvetica', 'B', 11)
        self.set_text_color(51, 51, 51)
        self.cell(0, 8, title, new_x="LMARGIN", new_y="NEXT")
        self.ln(1)

    def body_text(self, text):
        self.set_font('Helvetica', '', 10)
        self.set_text_color(60, 60, 60)
        self.multi_cell(0, 5.5, text)
        self.ln(2)

    def bold_text(self, text):
        self.set_font('Helvetica', 'B', 10)
        self.set_text_color(60, 60, 60)
        self.multi_cell(0, 5.5, text)
        self.ln(1)

    def stat_box(self, label, value, color=(0, 102, 204)):
        x, y = self.get_x(), self.get_y()
        self.set_fill_color(240, 245, 250)
        self.rect(x, y, 58, 22, 'F')
        self.set_xy(x + 2, y + 2)
        self.set_font('Helvetica', '', 8)
        self.set_text_color(100, 100, 100)
        self.cell(54, 5, label)
        self.set_xy(x + 2, y + 9)
        self.set_font('Helvetica', 'B', 14)
        self.set_text_color(*color)
        self.cell(54, 10, str(value))
        self.set_xy(x + 60, y)

    def table(self, headers, rows, col_widths=None):
        if not col_widths:
            col_widths = [190 / len(headers)] * len(headers)
        # Header
        self.set_font('Helvetica', 'B', 9)
        self.set_fill_color(0, 51, 102)
        self.set_text_color(255, 255, 255)
        for i, h in enumerate(headers):
            self.cell(col_widths[i], 7, h, border=1, fill=True, align='C')
        self.ln()
        # Rows
        self.set_font('Helvetica', '', 9)
        self.set_text_color(60, 60, 60)
        fill = False
        for row in rows:
            if fill:
                self.set_fill_color(245, 248, 252)
            else:
                self.set_fill_color(255, 255, 255)
            for i, cell in enumerate(row):
                self.cell(col_widths[i], 6.5, str(cell), border=1, fill=True, align='C')
            self.ln()
            fill = not fill
        self.ln(3)

    def bullet(self, text):
        self.set_font('Helvetica', '', 10)
        self.set_text_color(60, 60, 60)
        x = self.get_x()
        self.cell(5, 5.5, '-')
        self.multi_cell(175, 5.5, text)
        self.ln(1)

    def callout(self, text, color=(204, 0, 0)):
        self.set_fill_color(255, 240, 240) if color[0] > 100 else self.set_fill_color(240, 250, 240)
        x = self.get_x()
        y = self.get_y()
        self.rect(x, y, 190, 14, 'F')
        self.set_draw_color(*color)
        self.set_line_width(0.8)
        self.line(x, y, x, y + 14)
        self.set_xy(x + 4, y + 2)
        self.set_font('Helvetica', 'B', 10)
        self.set_text_color(*color)
        self.multi_cell(182, 5, text)
        self.ln(4)


pdf = Report()
pdf.alias_nb_pages()
pdf.set_auto_page_break(auto=True, margin=20)

# ─── COVER PAGE ───────────────────────────────────────────────────────────────
pdf.add_page()
pdf.ln(40)
pdf.set_font('Helvetica', 'B', 28)
pdf.set_text_color(0, 51, 102)
pdf.cell(0, 15, 'Fleet Optimization', align='C', new_x="LMARGIN", new_y="NEXT")
pdf.set_font('Helvetica', 'B', 20)
pdf.set_text_color(100, 100, 100)
pdf.cell(0, 12, 'Findings & Recommendations', align='C', new_x="LMARGIN", new_y="NEXT")
pdf.ln(10)
pdf.set_draw_color(0, 102, 204)
pdf.set_line_width(1)
pdf.line(60, pdf.get_y(), 150, pdf.get_y())
pdf.ln(10)
pdf.set_font('Helvetica', '', 12)
pdf.set_text_color(80, 80, 80)
pdf.cell(0, 8, 'AAA Western & Central New York', align='C', new_x="LMARGIN", new_y="NEXT")
pdf.cell(0, 8, f'Report Date: {datetime.now().strftime("%B %d, %Y")}', align='C', new_x="LMARGIN", new_y="NEXT")
pdf.cell(0, 8, 'Data Source: Salesforce FSL (Production)', align='C', new_x="LMARGIN", new_y="NEXT")
pdf.ln(20)
pdf.set_font('Helvetica', 'I', 10)
pdf.set_text_color(150, 150, 150)
pdf.cell(0, 8, 'Prepared by FSL App Analytics', align='C', new_x="LMARGIN", new_y="NEXT")

# ─── EXECUTIVE SUMMARY ───────────────────────────────────────────────────────
pdf.add_page()
pdf.section_title('1. Executive Summary')
pdf.body_text(
    'AAA WCNY is struggling to automatically assign the closest available driver to roadside calls. '
    'The FSL Enhanced Scheduler - designed for technicians who start from home (plumbers, electricians) - '
    'does not fit AAA\'s model where drivers are always on the road moving between calls.'
)
pdf.body_text(
    'This report presents data-backed findings on three interconnected problems: '
    '(1) the Scheduler uses home addresses that don\'t exist, '
    '(2) GPS coverage gaps leave many drivers invisible, and '
    '(3) Resource Absences - the current workaround - are only partially deployed. '
    'Each finding includes real numbers from the production Salesforce org.'
)
pdf.ln(2)

# Key stats boxes
pdf.stat_box('STM With Address', '0 / 689', (204, 0, 0))
pdf.stat_box('Fleet Without GPS', '41 / 89', (204, 102, 0))
pdf.stat_box('Towbook GPS', '0%', (204, 0, 0))
pdf.ln(28)

pdf.callout('BOTTOM LINE: The Scheduler cannot assign the closest driver because it has no driver locations to calculate from.')

# ─── THE HOME ADDRESS PROBLEM ────────────────────────────────────────────────
pdf.add_page()
pdf.section_title('2. The Home Address Problem')
pdf.body_text(
    'The FSL Enhanced Scheduler calculates travel distance from the driver\'s "home base" - '
    'the address on their ServiceTerritoryMember (STM) record. This is the record that links a driver to a garage. '
    'For plumbers and electricians, this would be their home address. For AAA, it should be the garage address.'
)

pdf.sub_title('ServiceTerritoryMember Address Data (Production)')
pdf.table(
    ['Field', 'Records With Data', 'Out of Total', 'Percentage'],
    [
        ['Street Address', '0', '689', '0%'],
        ['City', '0', '689', '0%'],
        ['Postal Code', '0', '689', '0%'],
        ['Latitude/Longitude', '65', '689', '9.4%'],
    ],
    [50, 40, 35, 35]
)

pdf.callout('Zero street addresses populated. The Scheduler has no starting location for 90% of drivers.')

pdf.sub_title('How This Fails - Real Example')
pdf.body_text(
    'A flat tire is reported at Exit 42, I-90 near Syracuse.\n\n'
    'Driver A (Mike): Currently 3 miles away (just finished a job). Home address: Watertown, 75 miles north.\n'
    'Driver B (Lisa): Currently 35 miles away (in Utica). Home address: Syracuse, 5 miles away.\n\n'
    'The Scheduler checks "Maximum Travel From Home" work rules:\n'
    '  - Mike: 75 miles from home -> EXCLUDED (exceeds 60-min rule)\n'
    '  - Lisa: 5 miles from home -> ASSIGNED\n\n'
    'Result: Lisa drives 35 miles. Mike was 3 miles away doing nothing. '
    'The customer waits 40 extra minutes. AAA pays for 32 extra miles of fuel.'
)

# ─── GPS COVERAGE ─────────────────────────────────────────────────────────────
pdf.add_page()
pdf.section_title('3. GPS Coverage Gap')
pdf.body_text(
    'Even if the Scheduler used GPS (it doesn\'t), many drivers are invisible. '
    'GPS data comes from the FSL mobile app - drivers must be logged in for the system to know where they are.'
)

pdf.sub_title('GPS Coverage by Driver Type (Production)')
pdf.table(
    ['Driver Type', 'Total', 'Has GPS', 'No GPS', 'Coverage'],
    [
        ['Fleet Driver', '89', '48', '41', '54%'],
        ['On-Platform Contractor', '232', '180', '52', '78%'],
        ['Off-Platform (Towbook)', '72', '1', '71', '1%'],
        ['Office/Dispatch Staff', '124', '0', '124', 'N/A'],
    ],
    [55, 25, 25, 25, 30]
)

pdf.sub_title('Why Towbook Has Zero GPS')
pdf.body_text(
    'The Towbook integration sends status updates ("job started", "job done") and timestamps to Salesforce - '
    'but NEVER sends driver GPS coordinates. This is a limitation of the Towbook system, not a configuration issue. '
    'Towbook drivers will never have GPS unless Towbook changes their integration.'
)

pdf.sub_title('Key Insight: Business Hours vs Off-Hours')
pdf.body_text(
    'GPS numbers look worse than reality because many drivers are off-shift. '
    'During business hours on a work day, approximately 83% of FSL app drivers who actually worked had usable GPS. '
    'The problem is concentrated in:\n'
    '  - 41 fleet drivers who are not logging into the FSL app\n'
    '  - 52 on-platform contractors not using the app\n'
    '  - All 72 Towbook drivers (will never have GPS)'
)

# ─── FLEET VS TOWBOOK ────────────────────────────────────────────────────────
pdf.add_page()
pdf.section_title('4. Fleet vs Towbook: Two Different Problems')

pdf.sub_title('Fleet Drivers (89 drivers)')
pdf.body_text(
    'Fleet drivers use the FSL mobile app. When logged in, they have real-time GPS updated every ~5 minutes. '
    'The problem is operational: 41 out of 89 (46%) are not logging into the app. '
    'This is fixable - it\'s an enforcement and compliance issue, not a technology issue.'
)

pdf.sub_title('Towbook Drivers (72 drivers)')
pdf.body_text(
    'Towbook (Off-Platform Contractors) are dispatched by their own facility. '
    'AAA does not control which Towbook driver gets assigned - the Towbook facility makes that decision. '
    'We have no GPS for these drivers and no way to get it without Towbook changing their integration.\n\n'
    'However, we CAN track whether Towbook facilities are sending the closest available driver '
    'by using the last completed job location as a GPS estimate. This gives AAA visibility into '
    'Towbook dispatch quality for performance reviews and contract conversations.'
)

pdf.table(
    ['', 'Fleet Drivers', 'Towbook Drivers'],
    [
        ['Who Assigns', 'FSL Scheduler + AAA Dispatchers', 'Towbook Facility'],
        ['Our Control', 'Full', 'None'],
        ['GPS Source', 'FSL Mobile App', 'None (last job estimate)'],
        ['Our Focus', 'Fix assignment quality', 'Track their performance'],
        ['Quick Win', 'Get 41 drivers on app', 'Use last job location'],
    ],
    [40, 75, 75]
)

pdf.callout('Towbook driver assignment is Towbook\'s responsibility. Our operational focus should be on the 89 Fleet drivers.', (0, 102, 0))

# ─── RESOURCE ABSENCES ────────────────────────────────────────────────────────
pdf.add_page()
pdf.section_title('5. Resource Absences: Current Workaround')
pdf.body_text(
    'Resource Absences remove drivers from the Scheduler\'s candidate pool. '
    'When a driver has an active absence, the Scheduler pretends they don\'t exist. '
    'This shrinks the pool from 689 records (mostly ghosts) to a smaller, cleaner set of actually-working drivers.'
)

pdf.sub_title('How It Works (Step by Step)')
pdf.bullet('Without absences: Scheduler sees 689 drivers. 624 have no address data. Scheduler can\'t calculate. Result: 0% auto-assignment.')
pdf.bullet('With absences: Drivers not working are marked absent. Pool shrinks to ~50-80 real drivers. Scheduler picks from a clean list. Result: 83% auto-assignment (UAT test, March 13).')
pdf.bullet('Resource Absences do NOT fix the home address problem. They just remove ghost drivers so the Scheduler has fewer bad options.')

pdf.sub_title('Resource Absences in Production (March 2026)')
pdf.table(
    ['Absence Type', 'Count', 'Created By'],
    [
        ['Break', '167', 'Dispatchers & Drivers'],
        ['Out - Short-Term', '37', 'Dispatchers'],
        ['Call Out', '27', 'Dispatchers'],
        ['Training', '16', 'Dispatchers'],
        ['PTO / Vacation', '14', 'Dispatchers'],
        ['Out - Long-Term', '13', 'Dispatchers'],
        ['Shift Mod - Early Out', '5', 'Dispatchers'],
        ['Last Assigned Service Location', '1', 'System'],
    ],
    [65, 30, 65]
)

pdf.callout(
    'CRITICAL: Production has ZERO automated "Real-Time Location" absences. '
    'The automated system that drove 0% -> 83% in UAT has NOT been deployed to Production yet.',
    (204, 0, 0)
)

pdf.sub_title('Top Absence Creators (March)')
pdf.table(
    ['Name', 'Absences Created', 'Role'],
    [
        ['Jeremy Harrington', '59', 'Dispatcher/Manager'],
        ['Debbie Taylor', '17', 'Dispatcher'],
        ['Diana Oakes', '14', 'Dispatcher'],
        ['Richard Yauger', '13', 'Dispatcher'],
        ['Chris Bortz', '11', 'Driver'],
    ],
    [65, 40, 55]
)
pdf.body_text('All absences are created manually by dispatchers and drivers. There is no automation in production.')

# ─── KEY DISCOVERY ────────────────────────────────────────────────────────────
pdf.add_page()
pdf.section_title('6. Key Discovery: 4.25 Million GPS History Records')
pdf.body_text(
    'ServiceResourceHistory contains 4.25 million records tracking every GPS position change for FSL app drivers. '
    'This is a complete historical trail - we can reconstruct exactly where any driver was at any point in time.'
)
pdf.body_text(
    'This enables a capability that doesn\'t exist today: calculating which driver was truly closest '
    'at the exact moment a call was assigned. Current metrics use the driver\'s current GPS position '
    '(which changes by the minute). Historical GPS gives us the accurate answer.'
)
pdf.body_text(
    'Note: Towbook drivers have zero entries in ServiceResourceHistory. This data source only covers '
    'Fleet and On-Platform Contractor drivers who use the FSL mobile app.'
)

# ─── OVER CAPACITY ────────────────────────────────────────────────────────────
pdf.section_title('7. Garage Over-Capacity Detection')
pdf.body_text(
    'The FSL App now detects garages that have more open calls than available drivers. '
    'Available drivers = active drivers in the territory with fresh GPS (updated within 4 hours). '
    'The capacity ratio is: Open Calls / Available Drivers.'
)
pdf.table(
    ['Ratio', 'Status', 'Badge', 'Meaning'],
    [
        ['< 1', 'Normal', 'None', 'More drivers than calls'],
        ['1 - 2', 'Busy', 'Yellow', 'Every driver has a call'],
        ['2+ or 0 drivers', 'Over Capacity', 'Red (pulsing)', 'Calls stacking up'],
    ],
    [30, 35, 40, 85]
)
pdf.body_text(
    'This is visible in both the Garage Operations dashboard (badge next to garage name + driver count) '
    'and the Command Center (territory cards + top summary bar).'
)

# ─── RECOMMENDATIONS ─────────────────────────────────────────────────────────
pdf.add_page()
pdf.section_title('8. Recommendations')

pdf.sub_title('Immediate (This Week)')
pdf.bullet(
    'Deploy automated Resource Absences to Production. The UAT test on March 13 proved this works - '
    'auto-assignment went from 0% to 83%. Production still only has manual absences. '
    'This is the single highest-impact change available.'
)
pdf.bullet(
    'Get 41 fleet drivers logged into the FSL mobile app. These drivers are invisible to the system. '
    'This is an operational enforcement issue - require app login at shift start and monitor compliance '
    'via the GPS Health metric in Command Center.'
)

pdf.sub_title('Short-Term (This Month)')
pdf.bullet(
    'Fill garage addresses on ServiceTerritoryMember records for all 89 fleet drivers. '
    'Put the garage/shop address (not home). This gives the Scheduler a real starting point '
    'instead of blank. Only 689 records need updating - a data entry task, not a dev project.'
)
pdf.bullet(
    'Monitor Towbook closest-driver metric. Track whether Towbook facilities are sending the closest '
    'available driver. Use this data in performance reviews and contract conversations. '
    'The FSL App now shows this in the Dispatch Insights panel.'
)

pdf.sub_title('Medium-Term (Next Quarter)')
pdf.bullet(
    'Build a smart recommendation engine using the 4.25 million GPS history records. '
    'Calculate the true closest driver at time of assignment using historical positions + Haversine distance. '
    'Apply the 25-minute threshold rule (send closest unless 25+ min slower than a faster driver). '
    'Surface recommendations to dispatchers before they assign.'
)
pdf.bullet(
    'Investigate FSL "Book Appointment" API. This may use a different location source than the batch Scheduler. '
    'If it uses GPS instead of home address, it could be a zero-code fix for fleet driver assignment.'
)

# ─── ACTION PLAN TABLE ────────────────────────────────────────────────────────
pdf.ln(5)
pdf.sub_title('Action Plan Summary')
pdf.table(
    ['When', 'What', 'Owner', 'Impact'],
    [
        ['This Week', 'Deploy automated absences to PROD', 'SF Admin', '0% -> 83% auto-assign'],
        ['This Week', 'Get 41 fleet drivers on FSL app', 'Fleet Managers', '+46% GPS coverage'],
        ['This Month', 'Fill 689 STM garage addresses', 'Data Team', 'Scheduler has locations'],
        ['This Month', 'Monitor Towbook closest-driver %', 'Operations', 'Contract accountability'],
        ['Next Quarter', 'Build GPS recommendation engine', 'Dev Team', 'True closest driver'],
        ['Next Quarter', 'Test Book Appointment API', 'SF Admin', 'Possible zero-code fix'],
    ],
    [30, 55, 35, 50]
)

# ─── APPENDIX ─────────────────────────────────────────────────────────────────
pdf.add_page()
pdf.section_title('Appendix: Data Sources & Methodology')

pdf.sub_title('Salesforce Objects Used')
pdf.bullet('ServiceResource - Driver records (name, type, GPS coordinates)')
pdf.bullet('ServiceTerritory - Garage/territory records')
pdf.bullet('ServiceTerritoryMember - Links drivers to garages (has the address fields)')
pdf.bullet('ServiceAppointment - Roadside call records')
pdf.bullet('ServiceAppointmentHistory - Status change audit trail')
pdf.bullet('ServiceResourceHistory - GPS position change history (4.25M records)')
pdf.bullet('ResourceAbsence - Driver unavailability records')
pdf.bullet('AssignedResource - Links drivers to specific calls')

pdf.sub_title('Key Field Definitions')
pdf.bullet('ERS_Driver_Type__c - Distinguishes: Fleet Driver, On-Platform Contractor, Off-Platform Contractor (Towbook)')
pdf.bullet('ERS_Dispatch_Method__c - "Field Services" (fleet) vs "Towbook" (contractor)')
pdf.bullet('LastKnownLatitude/Longitude - Real-time GPS from FSL mobile app, updates every ~5 min')
pdf.bullet('LastKnownLocationDate - Timestamp of last GPS update (used to determine freshness)')

pdf.sub_title('Calculations')
pdf.bullet('Closest Driver: Haversine distance from SA location to each available driver\'s GPS in the same territory. If assigned driver = shortest distance, counted as "closest".')
pdf.bullet('GPS Freshness: Fresh (<4h), Recent (4-24h), Stale (>24h), No GPS (never had coordinates)')
pdf.bullet('Over Capacity: Open calls / Available drivers with fresh GPS. Normal (<1), Busy (1-2), Over (2+)')

pdf.sub_title('System Users in This Org')
pdf.bullet('IT System User - Runs the FSL Scheduler (NOT Optimizer)')
pdf.bullet('Mulesoft Integration - Creates Service Appointments from external sources')
pdf.bullet('Replicant Integration User - IVR/voice system')
pdf.bullet('Integrations Towbook - Towbook system (sends status updates only, never GPS)')

# Save
out = '/Users/abdennourlaaroubi/Library/CloudStorage/OneDrive-EnProIndustriesInc/AAA/Dev/FSL/FSL/apidev/FSLAPP/doc/Fleet_Optimization_Report.pdf'
pdf.output(out)
print(f'PDF saved: {out}')
