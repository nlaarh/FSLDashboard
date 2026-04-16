#!/usr/bin/env python3
"""Generate FSL Implementation Audit Report PDF from markdown content."""
from fpdf import FPDF
import re
import os

class AuditPDF(FPDF):
    def header(self):
        self.set_font('Helvetica', 'B', 9)
        self.set_text_color(100, 100, 100)
        self.cell(0, 8, 'AAA WCNY - FSL Implementation Audit Report', 0, 0, 'L')
        self.cell(0, 8, 'April 8, 2026', 0, 1, 'R')
        self.set_draw_color(200, 200, 200)
        self.line(10, 14, 200, 14)
        self.ln(4)

    def footer(self):
        self.set_y(-15)
        self.set_font('Helvetica', 'I', 8)
        self.set_text_color(128, 128, 128)
        self.cell(0, 10, f'Page {self.page_no()}/{{nb}}', 0, 0, 'C')

    def section_title(self, title, level=1):
        if level == 1:
            self.set_font('Helvetica', 'B', 16)
            self.set_text_color(0, 51, 102)
            self.ln(6)
        elif level == 2:
            self.set_font('Helvetica', 'B', 13)
            self.set_text_color(0, 71, 133)
            self.ln(4)
        elif level == 3:
            self.set_font('Helvetica', 'B', 11)
            self.set_text_color(51, 51, 51)
            self.ln(3)
        self.multi_cell(0, 7, title)
        if level == 1:
            self.set_draw_color(0, 51, 102)
            self.line(10, self.get_y(), 200, self.get_y())
            self.ln(3)
        else:
            self.ln(1)

    def body_text(self, text):
        self.set_font('Helvetica', '', 10)
        self.set_text_color(33, 33, 33)
        self.multi_cell(0, 5.5, text)
        self.ln(1)

    def bold_text(self, text):
        self.set_font('Helvetica', 'B', 10)
        self.set_text_color(33, 33, 33)
        self.multi_cell(0, 5.5, text)
        self.ln(1)

    def issue_box(self, text):
        self.set_fill_color(255, 243, 230)
        self.set_draw_color(230, 126, 34)
        self.set_font('Helvetica', 'B', 10)
        self.set_text_color(180, 80, 0)
        x = self.get_x()
        y = self.get_y()
        self.rect(10, y, 190, 12, 'DF')
        self.set_xy(12, y + 2)
        self.multi_cell(186, 5, text)
        self.set_y(y + 14)

    def table(self, headers, data, col_widths=None):
        if col_widths is None:
            n = len(headers)
            col_widths = [190 / n] * n
        # Header
        self.set_font('Helvetica', 'B', 9)
        self.set_fill_color(0, 51, 102)
        self.set_text_color(255, 255, 255)
        for i, h in enumerate(headers):
            self.cell(col_widths[i], 7, h, 1, 0, 'C', True)
        self.ln()
        # Data
        self.set_font('Helvetica', '', 9)
        self.set_text_color(33, 33, 33)
        fill = False
        for row in data:
            if self.get_y() > 265:
                self.add_page()
                self.set_font('Helvetica', 'B', 9)
                self.set_fill_color(0, 51, 102)
                self.set_text_color(255, 255, 255)
                for i, h in enumerate(headers):
                    self.cell(col_widths[i], 7, h, 1, 0, 'C', True)
                self.ln()
                self.set_font('Helvetica', '', 9)
                self.set_text_color(33, 33, 33)
            if fill:
                self.set_fill_color(240, 245, 250)
            else:
                self.set_fill_color(255, 255, 255)
            max_h = 7
            for i, cell in enumerate(row):
                self.cell(col_widths[i], max_h, str(cell)[:50], 1, 0, 'L', True)
            self.ln()
            fill = not fill
        self.ln(3)

    def code_block(self, text):
        self.set_font('Courier', '', 9)
        self.set_fill_color(245, 245, 245)
        self.set_text_color(50, 50, 50)
        lines = text.strip().split('\n')
        y_start = self.get_y()
        for line in lines:
            if self.get_y() > 270:
                self.add_page()
            self.cell(190, 5, line[:95], 0, 1, 'L', True)
        self.ln(2)


def build_pdf():
    pdf = AuditPDF()
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=20)

    # Title page
    pdf.add_page()
    pdf.ln(40)
    pdf.set_font('Helvetica', 'B', 28)
    pdf.set_text_color(0, 51, 102)
    pdf.cell(0, 15, 'FSL Implementation', 0, 1, 'C')
    pdf.cell(0, 15, 'Audit Report', 0, 1, 'C')
    pdf.ln(10)
    pdf.set_font('Helvetica', '', 14)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 8, 'AAA Western & Central New York', 0, 1, 'C')
    pdf.cell(0, 8, 'Emergency Roadside Service (ERS)', 0, 1, 'C')
    pdf.ln(15)
    pdf.set_draw_color(0, 51, 102)
    pdf.line(60, pdf.get_y(), 150, pdf.get_y())
    pdf.ln(15)
    pdf.set_font('Helvetica', '', 11)
    pdf.cell(0, 7, 'Prepared: April 8, 2026', 0, 1, 'C')
    pdf.cell(0, 7, 'Purpose: Auditor review of FSL scheduling implementation', 0, 1, 'C')
    pdf.cell(0, 7, 'Data Source: Live Salesforce org queries', 0, 1, 'C')

    # Section 1: Executive Summary
    pdf.add_page()
    pdf.section_title('1. Executive Summary')
    pdf.body_text('AAA WCNY operates an Emergency Roadside Service (ERS) program using Salesforce Field Service Lightning (FSL) to manage dispatch of tow trucks and service vehicles across Western and Central New York. The implementation uses a two-channel dispatch model: Fleet drivers dispatched via the FSL Scheduler, and external contractors dispatched via Towbook (a third-party towing dispatch platform).')
    pdf.ln(2)
    pdf.bold_text('Key Findings:')
    findings = [
        '- 406 active Service Territories organized in a regional hierarchy',
        '- 519 active Service Resources (drivers) across 4 driver types',
        '- 5 Scheduling Policies exist, all focused on proximity - none include workload balancing',
        '- On-Platform Contractor facilities lack shifts, operating hours, and capacity configuration',
        '- Auto-assignment creates "hot driver" patterns requiring manual dispatcher intervention',
    ]
    for f in findings:
        pdf.body_text(f)

    # Section 2: Territory Architecture
    pdf.add_page()
    pdf.section_title('2. Territory Architecture')
    pdf.section_title('2.1 Territory Hierarchy', 2)
    pdf.body_text('The org uses a two-level territory hierarchy with parent territories (regions) containing child territories (facilities).')
    pdf.table(
        ['Region Code', 'Region', 'Child Facilities'],
        [
            ['WNY M', 'Western New York Metro', '22'],
            ['ROC M', 'Rochester Metro', '23'],
            ['CNYM', 'Central New York Metro', '41'],
            ['ST', 'Southern Tier', '38'],
            ['WM', 'Western Market', '62'],
            ['CR', 'Central Region', '61'],
            ['RR', 'Rochester Region', '35'],
            ['RM', 'Rochester Market', '31'],
            ['WR', 'Western Region', '23'],
        ],
        [30, 80, 80]
    )
    pdf.body_text('Total: 406 active territories (44 inactive), organized under ~16 parent regions.')

    pdf.section_title('2.2 Territory Types', 2)
    pdf.body_text('Each facility is a child Service Territory under its regional parent:')
    pdf.table(
        ['Type', 'Description', 'Example'],
        [
            ['Fleet', 'AAA-owned trucks and drivers', '100 - WESTERN NEW YORK FLEET'],
            ['On-Platform Contractor', 'External garages on FSL platform', '076DO - TRANSIT AUTO DETAIL'],
            ['Off-Platform (Towbook)', 'External garages via Towbook', 'Various Towbook facilities'],
            ['Spot', 'Temporary coverage areas', '000- WNY M SPOT'],
        ],
        [45, 75, 70]
    )

    pdf.section_title('2.3 Operating Hours', 2)
    pdf.table(
        ['Operating Hours', 'Usage'],
        [
            ['AAA 24/7/365', 'Most common - majority of facilities'],
            ['Sun-Sat, 7a-11p', 'Fleet territories, some contractors'],
            ['Sun-Sat, 7a-10p', 'Several contractor facilities'],
            ['Mon-Fri, 8a-5p', 'Limited weekday-only facilities'],
            ['Mon-Sat, 7a-10p', 'Some contractor facilities'],
        ],
        [70, 120]
    )
    pdf.issue_box('ISSUE: Individual drivers at contractor facilities have NO operating hours or shifts configured.')

    # Section 3: Service Resources
    pdf.add_page()
    pdf.section_title('3. Service Resources (Drivers)')
    pdf.section_title('3.1 Driver Population', 2)
    pdf.table(
        ['Driver Type', 'Active Count'],
        [
            ['On-Platform Contractor Driver', '240'],
            ['(null - not classified)', '123'],
            ['Fleet Driver', '85'],
            ['Off-Platform Contractor Driver', '71'],
            ['TOTAL', '519'],
        ],
        [110, 80]
    )

    pdf.section_title('3.2 Resource Configuration Fields', 2)
    pdf.table(
        ['Field', 'Purpose', 'Current State'],
        [
            ['IsOptimizationCapable', 'Include in optimization', 'Mostly true'],
            ['FSL__Efficiency__c', 'Efficiency rating', 'NULL for all drivers'],
            ['FSL__Priority__c', 'Priority ranking', 'NULL for all drivers'],
            ['FSL__Travel_Speed__c', 'Custom travel speed', 'NULL for all drivers'],
            ['Schedule_Type__c', 'On/Off Schedule', '271 On, 117 Off, 131 null'],
            ['MaxTravelDuration', 'Max travel to call', 'Unlimited for most'],
            ['LastKnownLat/Long', 'Real-time GPS', 'Updated via mobile app'],
        ],
        [50, 55, 85]
    )
    pdf.issue_box('ISSUE: Efficiency, Priority, and Travel Speed are null for ALL drivers - no differentiation.')

    pdf.section_title('3.3 Territory Membership', 2)
    pdf.table(
        ['Membership Type', 'Count'],
        [['Primary (P)', '764'], ['Secondary (S)', '233']],
        [95, 95]
    )
    pdf.body_text('STM homebase coordinates were null in original setup (Dec 2024). Corrected April 2026 with GPS-derived coordinates. Street addresses remain null.')

    # Section 4: Skills Framework
    pdf.add_page()
    pdf.section_title('4. Skills Framework')
    pdf.section_title('4.1 Dynamic Skill Assignment', 2)
    pdf.body_text('Skills are DYNAMICALLY assigned based on the truck a driver logs into. When a driver starts their shift and logs into a specific vehicle, the system assigns the skills associated with that truck. When they log out, skills are removed. This means a driver\'s skill set changes throughout the day.')

    pdf.section_title('4.2 Skill Inventory (ERS)', 2)
    pdf.table(
        ['Skill', 'Active Assignments', 'Category'],
        [
            ['EV', '365', 'Base (all drivers)'],
            ['Driver Tire', '362', 'Base (all drivers)'],
            ['Tow', '170', 'Tow truck'],
            ['Flat Bed', '155', 'Tow truck (flatbed)'],
            ['Extrication - Driveway', '170', 'Tow truck'],
            ['Extrication - Highway', '155', 'Tow truck'],
            ['Wheel Lift Truck', '102', 'Tow truck'],
            ['Low clearance', '96', 'Tow truck (specialty)'],
            ['Motorcycle Tow', '86', 'Tow truck (specialty)'],
            ['Long Tow', '82', 'Tow truck (long distance)'],
            ['Battery Certified', '159', 'Service truck'],
            ['Battery Service', '125', 'Service truck'],
            ['Jumpstart', '125', 'Service truck'],
            ['Lockout', '187', 'Service truck'],
            ['Fuel - Gasoline', '187', 'Service truck'],
            ['Fuel - Diesel', '185', 'Service truck'],
            ['Tire', '185', 'Service truck'],
            ['Miscellaneous', '193', 'Service truck'],
        ],
        [55, 55, 80]
    )

    pdf.section_title('4.3 Truck Type Skill Groups', 2)
    pdf.bold_text('Base skills (all logged-in drivers): EV, Driver Tire')
    pdf.bold_text('Tow Truck: Tow, Flat Bed, Extrication-D/H, Low clearance, Motorcycle Tow, Wheel Lift, Long Tow')
    pdf.bold_text('Service Truck: Battery, Jumpstart, Fuel-Gas/Diesel, Lockout, Tire, Miscellaneous')

    pdf.issue_box('ISSUE: At 076DO, only 13/50 drivers (26%) were on tow trucks. 30/50 (60%) had base skills only.')

    # Section 5: Work Types
    pdf.add_page()
    pdf.section_title('5. Work Types')
    pdf.table(
        ['Work Type', 'Description'],
        [
            ['Tow Pick-Up', 'Pick up member vehicle (always paired with Drop-Off)'],
            ['Tow Drop-Off', 'Deliver vehicle to destination'],
            ['Battery', 'Battery testing and replacement'],
            ['Lockout', 'Vehicle lockout service'],
            ['Tow', 'Generic tow (legacy)'],
        ],
        [60, 130]
    )
    pdf.body_text('Tow Pick-Up and Tow Drop-Off are always created in pairs and assigned to the same driver.')

    # Section 6: Dispatch Architecture
    pdf.section_title('6. Dispatch Architecture')
    pdf.section_title('6.1 Two-Channel Model', 2)
    pdf.code_block(
        'Incoming ERS Call\n'
        '       |\n'
        '  Mulesoft Routing Engine\n'
        '       |\n'
        '       +-- Fleet Territory? --> FSL Scheduler (Closest Driver policy)\n'
        '       |\n'
        '       +-- On-Platform Contractor? --> IT System User (Flow/Apex)\n'
        '       |                                 Auto-assign closest skill-matched driver\n'
        '       |\n'
        '       +-- Off-Platform? --> Towbook Integration\n'
        '                              Facility manages own dispatch'
    )

    pdf.section_title('6.2 Assignment Sources', 2)
    pdf.table(
        ['Assigner', 'Type', 'Description'],
        [
            ['IT System User', 'System', 'Flow/Apex automation - primary auto-assigner'],
            ['Mulesoft Integration', 'System', 'Mulesoft dispatch routing'],
            ['Platform Integration', 'System', 'Platform-level integration'],
            ['Replicant Integration', 'System', 'AI/IVR call handling'],
            ['Daniel Fisher et al.', 'Human', 'Contact center dispatchers - manual'],
        ],
        [50, 30, 110]
    )
    pdf.body_text('At On-Platform facilities: ~78% system-assigned, ~22% human-assigned. Human dispatchers frequently reassign to redistribute workload.')

    pdf.section_title('6.3 The "Hot Driver" Problem', 2)
    pdf.body_text('When automation assigns purely on proximity, a feedback loop occurs:')
    pdf.code_block(
        '1. Driver A finishes job -> GPS updates to job location\n'
        '2. New SA arrives nearby\n'
        '3. System: "Who is closest with matching skills?"\n'
        '4. Driver A is closest (just finished nearby)\n'
        '5. Driver A assigned again -> repeat\n'
        '6. Other qualified idle drivers are skipped\n'
        '7. Dispatcher manually intervenes to redistribute'
    )
    pdf.issue_box('ISSUE: Thomas Shultz got 4 consecutive auto-assignments in 81 min while others got 0-1.')

    # Section 7: Scheduling Policies
    pdf.add_page()
    pdf.section_title('7. Scheduling Policies')
    pdf.section_title('7.1 Policy Inventory', 2)
    pdf.table(
        ['Policy', 'Objectives', 'Workload Balance?'],
        [
            ['Closest Driver', 'Minimize Travel (100)', 'NO'],
            ['Emergency', 'ASAP (700) + Min Travel (300)', 'NO'],
            ['Highest Priority', 'ASAP (9000) + Min Travel (1000)', 'NO'],
            ['Copy of Highest Priority', 'ASAP (1500) + Min Travel (10)', 'NO'],
            ['DF TEST - Closest Driver', 'Minimize Travel (100)', 'NO'],
        ],
        [55, 85, 50]
    )
    pdf.issue_box('CRITICAL: Every policy optimizes only for proximity/speed. Zero workload distribution.')

    pdf.section_title('7.2 Work Rules on "Closest Driver"', 2)
    pdf.table(
        ['Work Rule', 'Purpose'],
        [
            ['Match Skills', 'Only candidates with required skills'],
            ['Working Territories', 'Only candidates in the territory'],
            ['Active Resources', 'Only active service resources'],
            ['Resource Availability', 'Only available (not busy) resources'],
            ['On/Off Schedule Contractor Avail.', 'Contractor availability rules'],
            ['Max Travel From Home (10-60 min)', 'Travel time limits (cascading)'],
            ['PTA Window Work Rule', 'Respect Promised Time of Arrival'],
            ['Match Passenger Space', 'Truck capacity for passenger tows'],
            ['Earliest Start / Due Date', 'Time boundary rules'],
            ['Required / Excluded Resources', 'Resource preferences'],
        ],
        [75, 115]
    )

    pdf.section_title('7.3 Available But Unused Service Objectives', 2)
    pdf.table(
        ['Objective', 'What It Does', 'Used?'],
        [
            ['ASAP', 'Schedule at earliest time', 'YES'],
            ['Minimize Travel', 'Nearest driver', 'YES'],
            ['Minimize Overtime', 'Prefer within standard hours', 'NO'],
            ['Resource Priority', 'Use driver priority ranking', 'NO'],
            ['Preferred Resource', 'Prefer specific driver', 'NO'],
            ['Skill Level', 'Prefer higher-skilled driver', 'NO'],
        ],
        [50, 85, 55]
    )
    pdf.issue_box('GAP: Minimize Overtime and Resource Priority are standard FSL workload tools - neither is used.')

    # Section 8: Challenges
    pdf.add_page()
    pdf.section_title('8. Identified Challenges and Issues')

    challenges = [
        ('8.1 No Workload Balancing', 'HIGH',
         'All policies optimize exclusively for proximity/speed. No mechanism distributes work evenly. Creates "hot driver" pattern. Human dispatchers manually redistribute 20-30% of auto-assigned SAs.'),
        ('8.2 Missing Driver Availability Config', 'HIGH',
         'On-Platform Contractor drivers lack: shifts (zero records), operating hours on STM (all null), efficiency ratings (all null), priority rankings (all null), capacity records (none). System treats all drivers as "always available."'),
        ('8.3 STM Homebase Coordinates', 'MEDIUM',
         'Originally null for all drivers (Dec 2024). Corrected April 2026 with GPS-derived coordinates. Street addresses still null. Coordinates may not reflect verified home locations.'),
        ('8.4 Drivers Not Logged Into Trucks', 'MEDIUM',
         'At any facility, 60%+ of rostered drivers may only have base skills (not logged into a truck), making them invisible to dispatch. Unclear if these are off-duty or missing truck login.'),
        ('8.5 FSL Scheduler Not Used for Contractors', 'HIGH',
         'FSL__Scheduling_Policy_Used__c is null on all On-Platform Contractor SAs. Custom Flow/Apex (IT System User) handles assignment instead of FSL Scheduler. Cannot benefit from policy objectives.'),
        ('8.6 Towbook ActualStartTime Unreliable', 'MEDIUM',
         'For Off-Platform SAs, ActualStartTime is bulk-updated at midnight. True arrival must be sourced from ServiceAppointmentHistory "On Location" status change.'),
        ('8.7 Duplicate Service Resources', 'LOW',
         'Some drivers have old (inactive) and new (active) ServiceResource records from facility migration. Old records retain historical data.'),
    ]

    for title, severity, desc in challenges:
        pdf.section_title(title, 2)
        color = {'HIGH': (220, 50, 50), 'MEDIUM': (230, 126, 34), 'LOW': (100, 100, 100)}[severity]
        pdf.set_font('Helvetica', 'B', 10)
        pdf.set_text_color(*color)
        pdf.cell(0, 6, f'Severity: {severity}', 0, 1)
        pdf.body_text(desc)

    # Section 9: Recommendations
    pdf.add_page()
    pdf.section_title('9. Recommendations')

    pdf.section_title('9.1 Immediate - Add Workload Balancing', 2)
    pdf.body_text('1. Add "Resource Priority" service objective to the "Closest Driver" policy (weight 30-50 alongside Minimize Travel at 100)')
    pdf.body_text('2. Set FSL__Priority__c equally on all drivers to enable round-robin when travel times are similar')
    pdf.body_text('3. No shift/hours setup required - provides immediate improvement')

    pdf.section_title('9.2 Short-term - Driver Availability', 2)
    pdf.body_text('1. Define shifts or operating hours for each driver at On-Platform Contractor facilities')
    pdf.body_text('2. This enables the "Minimize Overtime" service objective')
    pdf.body_text('3. Allows system to distinguish on-duty vs off-duty drivers')

    pdf.section_title('9.3 Medium-term - Migrate to FSL Scheduler', 2)
    pdf.body_text('1. Move On-Platform Contractor facilities from custom automation to FSL Scheduler')
    pdf.body_text('2. Enables all scheduling policy objectives and work rules')
    pdf.body_text('3. Provides auditable dispatch decision trail via FSL__Scheduling_Policy_Used__c')

    pdf.section_title('9.4 Long-term - Full Configuration', 2)
    pdf.body_text('1. Populate FSL__Efficiency__c on drivers based on performance data')
    pdf.body_text('2. Configure ServiceResourceCapacity for shift-based capacity management')
    pdf.body_text('3. Add verified home addresses to STM records')
    pdf.body_text('4. Implement Minimize Overtime + Resource Priority objectives together')
    pdf.body_text('5. Consider FSL Enhanced Scheduling and Optimization (ESO) engine')

    # Section 10: References
    pdf.add_page()
    pdf.section_title('10. Reference: Salesforce Documentation')
    refs = [
        'Scheduling Policies Overview:',
        '  trailhead.salesforce.com/content/learn/modules/field-service-lightning-scheduling-basics/examine-scheduling-policies',
        '',
        'Customize Scheduling Policies:',
        '  trailhead.salesforce.com/content/learn/modules/field-service-lightning-scheduling-basics/customize-a-scheduling-policy',
        '',
        'Understanding Optimization:',
        '  trailhead.salesforce.com/content/learn/modules/field-service-lightning-optimization/explore-optimization',
        '',
        'Service Objectives:',
        '  help.salesforce.com/s/articleView?id=service.pfs_optimization_theory_service_objectives.htm',
        '',
        'Scheduling Policies:',
        '  help.salesforce.com/s/articleView?id=service.pfs_scheduling.htm',
        '',
        'Policy Tuning:',
        '  help.salesforce.com/s/articleView?id=service.pfs_scheduling_policy_tuning.htm',
        '',
        'Optimization:',
        '  help.salesforce.com/s/articleView?id=service.pfs_optimization.htm',
        '',
        'Priority Optimization:',
        '  help.salesforce.com/s/articleView?id=service.pfs_scheduling_priority_optimization.htm',
    ]
    self = pdf
    pdf.set_font('Helvetica', '', 10)
    pdf.set_text_color(33, 33, 33)
    for line in refs:
        if line.startswith('  '):
            pdf.set_font('Courier', '', 8)
            pdf.set_text_color(0, 80, 160)
            pdf.cell(0, 5, line.strip(), 0, 1)
            pdf.set_font('Helvetica', '', 10)
            pdf.set_text_color(33, 33, 33)
        elif line == '':
            pdf.ln(2)
        else:
            pdf.set_font('Helvetica', 'B', 10)
            pdf.cell(0, 6, line, 0, 1)

    pdf.ln(10)
    pdf.set_draw_color(0, 51, 102)
    pdf.line(60, pdf.get_y(), 150, pdf.get_y())
    pdf.ln(5)
    pdf.set_font('Helvetica', 'I', 9)
    pdf.set_text_color(128, 128, 128)
    pdf.cell(0, 6, 'Report generated from live Salesforce org data on April 8, 2026.', 0, 1, 'C')

    # Save
    out_path = os.path.join(os.path.dirname(__file__), 'FSL_Implementation_Audit_Report.pdf')
    pdf.output(out_path)
    print(f'PDF saved to: {out_path}')
    return out_path

if __name__ == '__main__':
    build_pdf()
