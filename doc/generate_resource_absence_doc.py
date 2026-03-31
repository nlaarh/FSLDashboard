#!/usr/bin/env python3
"""Generate Resource Absence GPS Workaround — Technical Documentation PDF."""
from fpdf import FPDF
from datetime import datetime


class Report(FPDF):
    def header(self):
        self.set_font('Helvetica', 'B', 10)
        self.set_text_color(100, 100, 100)
        self.cell(0, 8, 'AAA WCNY - Resource Absence & GPS Location Strategy', align='R')
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
        self.set_font('Helvetica', 'B', 9)
        self.set_fill_color(0, 51, 102)
        self.set_text_color(255, 255, 255)
        for i, h in enumerate(headers):
            self.cell(col_widths[i], 7, h, border=1, fill=True, align='C')
        self.ln()
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
        self.cell(5, 5.5, '-')
        self.multi_cell(175, 5.5, text)
        self.ln(1)

    def callout(self, text, color=(204, 0, 0)):
        if color[0] > 100:
            self.set_fill_color(255, 240, 240)
        else:
            self.set_fill_color(240, 250, 240)
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

    def numbered(self, number, text):
        self.set_font('Helvetica', 'B', 10)
        self.set_text_color(0, 102, 204)
        self.cell(8, 5.5, f'{number}.')
        self.set_font('Helvetica', '', 10)
        self.set_text_color(60, 60, 60)
        self.multi_cell(172, 5.5, text)
        self.ln(1)

    def diagram_box(self, text, x, y, w=50, h=14, fill_color=(240, 245, 250), border_color=(0, 102, 204)):
        self.set_fill_color(*fill_color)
        self.set_draw_color(*border_color)
        self.set_line_width(0.4)
        self.rect(x, y, w, h, 'DF')
        self.set_xy(x + 1, y + 2)
        self.set_font('Helvetica', '', 8)
        self.set_text_color(40, 40, 40)
        self.multi_cell(w - 2, 4, text, align='C')

    def arrow_down(self, x, y1, y2):
        self.set_draw_color(0, 102, 204)
        self.set_line_width(0.4)
        self.line(x, y1, x, y2)
        self.line(x - 2, y2 - 3, x, y2)
        self.line(x + 2, y2 - 3, x, y2)

    def arrow_right(self, x1, x2, y):
        self.set_draw_color(0, 102, 204)
        self.set_line_width(0.4)
        self.line(x1, y, x2, y)
        self.line(x2 - 3, y - 2, x2, y)
        self.line(x2 - 3, y + 2, x2, y)


pdf = Report()
pdf.alias_nb_pages()
pdf.set_auto_page_break(auto=True, margin=20)

# ─── COVER PAGE ──────────────────────────────────────────────────────────────
pdf.add_page()
pdf.ln(40)
pdf.set_font('Helvetica', 'B', 28)
pdf.set_text_color(0, 51, 102)
pdf.cell(0, 15, 'Resource Absence as', align='C', new_x="LMARGIN", new_y="NEXT")
pdf.cell(0, 15, 'GPS Location Proxy', align='C', new_x="LMARGIN", new_y="NEXT")
pdf.ln(5)
pdf.set_font('Helvetica', '', 14)
pdf.set_text_color(100, 100, 100)
pdf.cell(0, 10, 'How AAA WCNY Solved the FSL Scheduler Location Problem', align='C', new_x="LMARGIN", new_y="NEXT")
pdf.ln(15)
pdf.set_draw_color(0, 102, 204)
pdf.set_line_width(0.5)
pdf.line(60, pdf.get_y(), 150, pdf.get_y())
pdf.ln(15)
pdf.set_font('Helvetica', '', 11)
pdf.set_text_color(80, 80, 80)
pdf.cell(0, 8, 'AAA Western & Central New York', align='C', new_x="LMARGIN", new_y="NEXT")
pdf.cell(0, 8, 'Emergency Roadside Service (ERS)', align='C', new_x="LMARGIN", new_y="NEXT")
pdf.cell(0, 8, f'March 2026', align='C', new_x="LMARGIN", new_y="NEXT")
pdf.ln(30)

# Key stats
pdf.stat_box('Before', '0%', color=(204, 0, 0))
pdf.stat_box('After', '83%', color=(0, 153, 0))
pdf.stat_box('Metric', 'Auto-Assign %', color=(0, 102, 204))
pdf.ln(30)

# ─── TABLE OF CONTENTS ──────────────────────────────────────────────────────
pdf.add_page()
pdf.section_title('Table of Contents')
pdf.ln(4)
toc = [
    ('1.', 'Executive Summary'),
    ('2.', 'The Problem: Why the Scheduler Could Not Find Drivers'),
    ('3.', 'How the FSL Scheduler Calculates Travel'),
    ('4.', 'The Solution: Resource Absence as Location Proxy'),
    ('5.', 'How It Works: Step by Step'),
    ('6.', 'Absence Types and Their Purpose'),
    ('7.', 'The Flow: AAA_ERS_Subflow_Create_or_Update_Resource_Absence'),
    ('8.', 'Before vs After: Results'),
    ('9.', 'Why This Approach (vs Alternatives)'),
    ('10.', 'Limitations and Future Improvements'),
]
for num, title in toc:
    pdf.set_font('Helvetica', 'B', 11)
    pdf.set_text_color(0, 102, 204)
    pdf.cell(12, 8, num)
    pdf.set_font('Helvetica', '', 11)
    pdf.set_text_color(60, 60, 60)
    pdf.cell(0, 8, title, new_x="LMARGIN", new_y="NEXT")

# ─── SECTION 1: EXECUTIVE SUMMARY ───────────────────────────────────────────
pdf.add_page()
pdf.section_title('1. Executive Summary')

pdf.body_text(
    'AAA WCNY operates an Emergency Roadside Service (ERS) fleet where drivers are always on the road '
    '-- not starting from home like traditional field service technicians. The Salesforce Field Service (FSL) '
    'Enhanced Scheduler was designed for the home-based model and calculates travel from a driver\'s '
    '"home base" address stored on ServiceTerritoryMember (STM) records.'
)

pdf.body_text(
    'The problem: zero out of 501 STM records had home addresses populated, and the concept of '
    '"home base" is irrelevant for roaming ERS drivers. The scheduler had no way to determine where '
    'drivers were, resulting in 0% auto-assignment success.'
)

pdf.body_text(
    'The solution: use ResourceAbsence records as GPS location proxies. The FSL scheduler calculates '
    'travel to the next appointment from three sources in priority order: (1) prior SA location, '
    '(2) absence location, or (3) home base. By creating Resource Absence records with the driver\'s '
    'last known latitude/longitude in the absence Address field, we give the scheduler a usable location '
    'reference -- even when GPS is stale and STM is blank.'
)

pdf.callout('Result: Auto-assignment went from 0% to 83% after deploying Resource Absences.', color=(0, 128, 0))

# ─── SECTION 2: THE PROBLEM ─────────────────────────────────────────────────
pdf.add_page()
pdf.section_title('2. The Problem: Why the Scheduler Could Not Find Drivers')

pdf.sub_title('2.1 The FSL Home Base Model vs AAA Reality')
pdf.body_text(
    'The FSL Enhanced Scheduler was built for field technicians (plumbers, electricians, HVAC techs) '
    'who start each day from their home and return home at the end of the day. Travel calculations '
    'always anchor to the "home base" -- the address on the ServiceTerritoryMember (STM) record.'
)

pdf.body_text(
    'AAA ERS drivers are fundamentally different:'
)
pdf.bullet('Drivers are already on the road when a call comes in')
pdf.bullet('They move continuously between service locations throughout their shift')
pdf.bullet('There is no "home base" concept -- the driver\'s location is wherever they finished their last job')
pdf.bullet('The relevant question is "where is the driver RIGHT NOW?" not "where does the driver live?"')

pdf.sub_title('2.2 Three Compounding Data Gaps')

pdf.table(
    ['Data Source', 'Purpose', 'Status at AAA', 'Impact'],
    [
        ['STM Address', 'Home base for travel calc', '0/501 populated', 'Scheduler has no base location'],
        ['STM Lat/Lon', 'Geocoded home base', '65/501 have coords', '87% have no geocoded base'],
        ['SR GPS', 'Real-time driver position', '~49% on any given day', 'Half of drivers invisible'],
    ],
    col_widths=[35, 45, 40, 70]
)

pdf.sub_title('2.3 GPS Coverage by Driver Type')

pdf.table(
    ['Driver Type', 'Total', 'Had GPS (Biz Hours)', '%', 'Notes'],
    [
        ['Fleet Driver', '89', '25', '28%', 'FSL mobile app required'],
        ['On-Platform Contractor', '232', '47', '20%', 'App adoption varies'],
        ['Off-Platform (Towbook)', '72', '0', '0%', 'Will NEVER have GPS'],
    ],
    col_widths=[42, 18, 38, 15, 77]
)

pdf.body_text(
    'Towbook drivers will never have GPS in Salesforce -- the Towbook integration sends status '
    'updates and timestamps but NOT driver GPS coordinates. This is by design: Towbook garages '
    'dispatch their own drivers independently.'
)

pdf.sub_title('2.4 What Happened Without Location Data')

pdf.body_text(
    'When the scheduler had no location data for a driver, two failure modes occurred:'
)
pdf.numbered(1, 'Fallback to garage address: All locationless drivers appeared to be "at the garage." '
    'Distance scoring was identical for everyone, making the closest-driver calculation meaningless.')
pdf.numbered(2, 'Random assignment: With no way to differentiate candidates by distance, the scheduler '
    'essentially picked arbitrarily. A driver 3 miles away had the same score as one 30 miles away.')

pdf.callout('Result: 0% auto-assignment success. Every call required manual dispatcher intervention.', color=(204, 0, 0))

# ─── SECTION 3: HOW THE SCHEDULER CALCULATES TRAVEL ─────────────────────────
pdf.add_page()
pdf.section_title('3. How the FSL Scheduler Calculates Travel')

pdf.sub_title('3.1 The Three Travel Sources (Priority Order)')

pdf.body_text(
    'The FSL Enhanced Scheduler calculates "Estimated Travel Distance To" -- the distance from the '
    'driver\'s current/assumed position to the next service appointment. It uses three sources in '
    'strict priority order:'
)

pdf.table(
    ['Priority', 'Source', 'When Used', 'AAA Status'],
    [
        ['1 (Best)', 'Prior SA location', 'Driver just finished a job', 'Works when SA exists'],
        ['2 (Fallback)', 'Absence location', 'No prior SA, but absence has address', 'THE WORKAROUND'],
        ['3 (Last resort)', 'Home base (STM)', 'No prior SA, no absence location', 'BLANK (0/501)'],
    ],
    col_widths=[25, 40, 55, 70]
)

pdf.callout(
    'Key insight: The scheduler uses the ResourceAbsence Address/Lat/Lon as a location source. '
    'This is documented in the Salesforce Field Service reference under AssignedResource fields.',
    color=(0, 102, 204)
)

pdf.sub_title('3.2 The Scoring Formula')

pdf.body_text(
    'The FSL scheduler scores each candidate using the Minimize Travel service objective:'
)
pdf.body_text(
    'Score = (ASAP Grade x ASAP Weight) + (Travel Grade x Travel Weight) + Priority'
)
pdf.bullet('Travel Grade 100 = closest driver (shortest travel distance)')
pdf.bullet('Travel Grade 0 = farthest driver (longest travel distance)')
pdf.bullet('Grades are distributed linearly between the closest and farthest candidate')
pdf.body_text(
    'If the scheduler does not know where a driver is, the Travel Grade becomes meaningless -- '
    'all locationless drivers get the same grade (based on garage location), defeating the purpose '
    'of the Minimize Travel objective.'
)

pdf.sub_title('3.3 The GPS-to-STM Auto-Sync Discovery')
pdf.body_text(
    'An important finding: the FSL mobile app automatically syncs ServiceResource.LastKnownLatitude/'
    'Longitude to ServiceTerritoryMember.Latitude/Longitude in the same transaction. This means that '
    'for drivers with an active FSL app, the scheduler DOES have real-time position data flowing into '
    'STM records. However, this only works for the ~28-49% of drivers whose app is actively running.'
)

# ─── SECTION 4: THE SOLUTION ────────────────────────────────────────────────
pdf.add_page()
pdf.section_title('4. The Solution: Resource Absence as Location Proxy')

pdf.sub_title('4.1 Core Concept')

pdf.body_text(
    'Resource Absence (ResourceAbsence) records have an Address field with Latitude and Longitude. '
    'When the scheduler looks for a driver\'s position and finds no prior SA and no STM address, it '
    'checks for an absence record with a location. By creating absences populated with the driver\'s '
    'last known GPS coordinates, we give the scheduler a location to calculate travel from.'
)

pdf.bold_text('The Resource Absence serves a dual purpose:')
pdf.numbered(1, 'Location proxy: The absence Address/Lat/Lon tells the scheduler "this driver was '
    'last seen HERE." The scheduler uses this as the starting point for travel calculations.')
pdf.numbered(2, 'Availability filter: Absences also mark drivers as "unavailable" during the absence '
    'window, removing them from the candidate pool if they are truly not working. This cleans up '
    'the candidate pool by excluding ghost/inactive drivers.')

pdf.sub_title('4.2 Why ResourceAbsence (Not Other Objects)')

pdf.table(
    ['Alternative', 'Why Not', 'Resource Absence Advantage'],
    [
        ['Update STM Address', 'STM = "home base," not current position', 'Absence = temporary, context-aware'],
        ['Use SR GPS directly', 'Scheduler does NOT read SR.LastKnownLat/Lon', 'Absence location IS read by scheduler'],
        ['Custom object', 'Scheduler can\'t read custom objects', 'Absence is a native scheduler input'],
        ['Flow-based bypass', 'Replaces scheduler entirely', 'Absence works WITH the scheduler'],
    ],
    col_widths=[35, 60, 95]
)

pdf.callout(
    'Resource Absence is the only standard Salesforce object (besides STM and prior SA) that the '
    'FSL scheduler reads for location data. It is the ONLY viable workaround within the native platform.',
    color=(0, 128, 0)
)

# ─── SECTION 5: STEP BY STEP ────────────────────────────────────────────────
pdf.add_page()
pdf.section_title('5. How It Works: Step by Step')

pdf.sub_title('5.1 The Lifecycle')

pdf.numbered(1, 'Driver completes a Service Appointment (SA status changes to Completed, En Route, '
    'On Location, etc.)')
pdf.numbered(2, 'The SA status change triggers the master flow: "AAA Master Service Appointment After Update"')
pdf.numbered(3, 'Subflow #3 fires: "AAA_ERS_Subflow_Create_or_Update_Resource_Absence"')
pdf.numbered(4, 'The subflow reads the SA\'s geolocation (Latitude/Longitude) -- this is the job site '
    'where the driver just was')
pdf.numbered(5, 'The subflow creates or updates a ResourceAbsence record for that driver, setting the '
    'absence Address/Lat/Lon to the SA\'s geolocation')
pdf.numbered(6, 'When a new call comes in and the scheduler evaluates candidates, it finds the '
    'absence location and uses it as the driver\'s position for travel calculation')
pdf.numbered(7, 'The scheduler scores candidates by travel distance from their known position '
    '(absence location) to the new SA -- the closest driver gets the highest Travel Grade')

pdf.sub_title('5.2 Flow Architecture')

pdf.body_text('The Resource Absence subflow is part of the SA lifecycle flow chain:')
pdf.ln(2)

pdf.body_text(
    'AAA Master Service Appointment After Update (15 subflows, sequential):\n'
    '  1. Notification to Driver (On Location Tow Drop-off)\n'
    '  2. Share Asset Data with Driver\n'
    '  3. >>> Create or Update Resource Absence <<<  [THIS IS THE KEY FLOW]\n'
    '  4. Cancel/update WOLI/WO when SA cancelled\n'
    '  5. Update WOLI/WO when SA status changes\n'
    '  ... (10 more subflows)'
)

pdf.body_text(
    'The flow is #3 in the execution chain -- it runs early in the SA update lifecycle to ensure '
    'the absence record is current before the next scheduling decision.'
)

# ─── SECTION 6: ABSENCE TYPES ───────────────────────────────────────────────
pdf.add_page()
pdf.section_title('6. Absence Types and Their Purpose')

pdf.table(
    ['Absence Type', 'Count', 'Purpose', 'Has Location?'],
    [
        ['Real-Time Location', '435', 'Flags drivers without active GPS', 'Yes'],
        ['Last assigned Service Location', '233', 'Stores last known driver position', 'Yes'],
        ['Break', '4,344', 'Standard break tracking', 'Varies'],
        ['Call out', '102', 'Driver called out sick', 'No'],
        ['PTO / Vacation', '81', 'Planned time off', 'No'],
    ],
    col_widths=[50, 20, 70, 50]
)

pdf.sub_title('6.1 "Real-Time Location" Absences')
pdf.body_text(
    'These absences are created for drivers whose GPS is not currently active. The absence includes '
    'the driver\'s last known coordinates, giving the scheduler something to work with even when '
    'the FSL mobile app is not sending updates. The absence also marks the driver as potentially '
    'unavailable, preventing the scheduler from assigning calls to drivers it cannot locate.'
)

pdf.sub_title('6.2 "Last Assigned Service Location" Absences')
pdf.body_text(
    'These absences are updated each time a driver completes a job. The SA\'s geolocation is copied '
    'into the absence Address field, so the scheduler always knows where the driver was most recently. '
    'This is the primary mechanism that makes closest-driver assignment work -- the scheduler reads '
    'this location and calculates travel distance from it.'
)

pdf.sub_title('6.3 How the Two Types Work Together')
pdf.bullet('"Last assigned Service Location" = "I know where this driver was last"')
pdf.bullet('"Real-Time Location" = "This driver\'s GPS is stale, but here\'s their last position"')
pdf.body_text(
    'Together, they ensure the scheduler always has a location reference for Fleet drivers, '
    'whether or not their FSL mobile app is actively transmitting GPS.'
)

# ─── SECTION 7: THE FLOW ────────────────────────────────────────────────────
pdf.add_page()
pdf.section_title('7. The Flow: AAA_ERS_Subflow_Create_or_Update_Resource_Absence')

pdf.sub_title('7.1 Trigger')
pdf.body_text(
    'Fired by: "AAA Master Service Appointment After Update" (Record-Triggered Flow, After Update)\n'
    'Position in chain: Subflow #3 of 15\n'
    'Trigger object: ServiceAppointment'
)

pdf.sub_title('7.2 Logic Summary')
pdf.numbered(1, 'Reads the updated SA\'s AssignedResource (driver) and geolocation (Lat/Lon)')
pdf.numbered(2, 'Checks if a ResourceAbsence already exists for this driver with type "Last assigned '
    'Service Location"')
pdf.numbered(3, 'If YES: Updates the existing absence\'s Address/Lat/Lon with the SA\'s geolocation')
pdf.numbered(4, 'If NO: Creates a new ResourceAbsence record with the SA\'s geolocation')
pdf.numbered(5, 'Sets the absence Start/End times appropriately')

pdf.sub_title('7.3 Key Fields Written')
pdf.table(
    ['ResourceAbsence Field', 'Value Source', 'Purpose'],
    [
        ['ResourceId', 'SA.AssignedResource.ServiceResourceId', 'Links absence to the driver'],
        ['Type', '"Last assigned Service Location"', 'Identifies the absence purpose'],
        ['Latitude', 'SA.Latitude', 'Job site latitude (driver\'s last position)'],
        ['Longitude', 'SA.Longitude', 'Job site longitude (driver\'s last position)'],
        ['Street/City/State', 'SA address fields', 'Human-readable location reference'],
        ['Start / End', 'Based on SA timing', 'Absence time window'],
    ],
    col_widths=[45, 65, 80]
)

pdf.sub_title('7.4 Managed by Flows, Not Apex')
pdf.body_text(
    'Resource Absence records at AAA are managed entirely by Salesforce Flows -- no Apex code '
    'touches them directly. This is by design: Flows are declarative, easier to maintain, and '
    'visible to SF admins without developer tools. The ResourceAbsence object fields are not '
    'referenced in any Apex trigger handler in the org.'
)

# ─── SECTION 8: RESULTS ─────────────────────────────────────────────────────
pdf.add_page()
pdf.section_title('8. Before vs After: Results')

pdf.sub_title('8.1 Key Metrics')
pdf.ln(2)

pdf.stat_box('Before (Auto-Assign)', '0%', color=(204, 0, 0))
pdf.stat_box('After (Auto-Assign)', '83%', color=(0, 153, 0))
pdf.stat_box('Improvement', '+83 pts', color=(0, 102, 204))
pdf.ln(28)

pdf.sub_title('8.2 What Changed')

pdf.table(
    ['Metric', 'Before Absences', 'After Absences'],
    [
        ['Candidate pool', '689 drivers (624 no address)', '~50-80 real, located drivers'],
        ['Travel scoring', 'Meaningless (all at garage)', 'Accurate (real positions)'],
        ['Auto-assignment', '0% success', '83% success'],
        ['Dispatcher workload', 'Every call manual', 'Only 17% need intervention'],
        ['Closest driver %', 'Random', '34% rank-1, 69% top-3'],
    ],
    col_widths=[40, 75, 75]
)

pdf.sub_title('8.3 Why 83%, Not 100%')
pdf.body_text('The remaining 17% that still require manual assignment are due to:')
pdf.bullet('Skill-constrained situations: Only 1-2 drivers have the required skill (e.g., specialized tow), '
    'so distance barely matters -- whoever is qualified gets the call')
pdf.bullet('Stale absence locations: If a driver has been idle for hours, their absence location may be '
    'outdated, leading to a suboptimal distance score')
pdf.bullet('Towbook resources: Off-platform drivers are excluded from FSL scheduling entirely -- '
    'Towbook handles its own dispatch')
pdf.bullet('First job of day with no prior SA and no absence: Fresh drivers with no history '
    'still have no location reference until they complete their first job')

# ─── SECTION 9: WHY THIS APPROACH ───────────────────────────────────────────
pdf.add_page()
pdf.section_title('9. Why This Approach (vs Alternatives)')

pdf.sub_title('9.1 Alternatives Considered')

pdf.table(
    ['Option', 'Description', 'Pros', 'Cons', 'Verdict'],
    [
        ['A', 'Fix GPS coverage', 'Real-time accuracy', 'Requires all drivers on app', 'Complementary'],
        ['B', 'Populate STM addresses', 'Uses native scheduler', 'Static, not real position', 'Partial fix'],
        ['C', 'Custom assignment logic', 'Full control, real GPS', 'Bypasses scheduler entirely', 'Future phase'],
        ['D', 'Book Appointment API', 'May use different source', 'Needs investigation', 'Unknown'],
        ['E', 'Flow-based auto-assign', 'Full control, real GPS', 'Must handle all edge cases', 'Future phase'],
        ['RA', 'Resource Absence proxy', 'Works WITH scheduler', 'Not real-time GPS', 'DEPLOYED'],
    ],
    col_widths=[16, 38, 34, 44, 58]
)

pdf.sub_title('9.2 Why Resource Absence Won')

pdf.numbered(1, 'Works within the native platform: No custom code, no external integrations, no '
    'scheduler bypass. Uses standard FSL behavior as documented by Salesforce.')
pdf.numbered(2, 'Declarative (Flow-based): Maintainable by SF admins. No Apex development or '
    'deployment required. Changes are visible in Setup.')
pdf.numbered(3, 'Dual benefit: Not only provides location data but also cleans up the candidate '
    'pool by removing ghost/inactive drivers.')
pdf.numbered(4, 'Immediate impact: Went from 0% to 83% auto-assignment with a single Flow deployment. '
    'No infrastructure changes, no retraining, no app rollout needed.')
pdf.numbered(5, 'Complementary to future improvements: Resource Absences work alongside GPS coverage '
    'improvements (Option A) and STM address population (Option B). They are additive, not exclusive.')

pdf.sub_title('9.3 Why Not Just Populate STM Addresses?')
pdf.body_text(
    'Setting STM addresses to the garage location (Option B) would give the scheduler a starting point, '
    'but it would treat ALL drivers as "at the garage" -- the same failure mode we had before. '
    'The key advantage of Resource Absences is that they store the LAST KNOWN POSITION, which is '
    'unique to each driver and changes with every completed job. This gives the scheduler true '
    'per-driver location differentiation.'
)

# ─── SECTION 10: LIMITATIONS AND FUTURE ─────────────────────────────────────
pdf.add_page()
pdf.section_title('10. Limitations and Future Improvements')

pdf.sub_title('10.1 Current Limitations')

pdf.numbered(1, 'Not real-time: The absence location is the driver\'s position at their LAST JOB, not '
    'their current position. If a driver drove 20 miles since their last job, the scheduler '
    'thinks they\'re still at the old location.')
pdf.numbered(2, 'First job of day gap: A driver who just started their shift has no prior SA and '
    'potentially no absence location -- the scheduler still has nothing to work with until the '
    'driver completes their first call.')
pdf.numbered(3, 'Towbook excluded: This workaround only benefits Fleet and On-Platform Contractor '
    'drivers. Towbook drivers are dispatched by Towbook\'s own system.')
pdf.numbered(4, 'Absence window management: The absence Start/End times must be carefully managed '
    'to avoid accidentally marking working drivers as "unavailable" when they should be candidates.')

pdf.sub_title('10.2 Complementary Improvements')

pdf.table(
    ['Improvement', 'Impact', 'Status'],
    [
        ['Increase FSL app adoption', 'More drivers with real-time GPS', 'Ongoing'],
        ['GPS-to-STM auto-sync', 'App users get STM coords automatically', 'Working (discovered Mar 15)'],
        ['Populate garage as STM fallback', 'Better than blank for non-app drivers', 'Recommended'],
        ['Custom closest-driver engine', 'Use ServiceResourceHistory for true GPS', 'Future phase'],
        ['ServiceResourceHistory analysis', '4.25M records = full movement history', 'Data available'],
    ],
    col_widths=[55, 75, 60]
)

pdf.sub_title('10.3 The GPS-to-STM Auto-Sync')
pdf.body_text(
    'A key discovery (March 15, 2026): The FSL mobile app automatically syncs '
    'ServiceResource.LastKnownLatitude/Longitude to ServiceTerritoryMember.Latitude/Longitude in the '
    'same transaction. This means drivers with an active app already have their real-time position '
    'flowing to the STM record -- the scheduler\'s Priority 3 location source. For these drivers, '
    'Resource Absences provide a secondary backup, but the STM sync is the primary location mechanism.'
)

pdf.sub_title('10.4 The Full Picture')
pdf.body_text(
    'Resource Absences are one layer in a multi-layered location strategy:\n\n'
    '  Layer 1: GPS auto-sync to STM (real-time, for app users)\n'
    '  Layer 2: Resource Absence location (last job site, for all drivers)\n'
    '  Layer 3: Garage address on STM (static fallback, not yet deployed)\n\n'
    'Together, these layers ensure the scheduler always has SOME location data for every '
    'driver, with increasing accuracy based on the driver\'s technology adoption level.'
)

# ─── OUTPUT ──────────────────────────────────────────────────────────────────
output_path = 'doc/AAA_Resource_Absence_GPS_Workaround.pdf'
pdf.output(output_path)
print(f'PDF generated: {output_path}')
