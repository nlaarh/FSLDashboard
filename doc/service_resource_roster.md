---
name: ServiceResource Roster — Who's Who
description: Complete breakdown of all 517 active ServiceResources. Real road drivers vs office staff vs system/placeholder/test records. Verified Mar 15, 2026 via AssignedResource dispatch data + WorkType analysis.
type: project
---

# ServiceResource Roster (Verified Mar 15, 2026)

## How to Identify Real Road Drivers
1. Query AssignedResource for dispatches in current year
2. Check WorkType — ERS types (Tow, Battery, Tire, Lockout, Winch Out, Fuel, Locksmith) = road driver
3. Non-ERS types (Travel, Insurance, Personal Lines) = office staff
4. Best query: `SELECT ServiceResource.Name, COUNT(Id) FROM AssignedResource WHERE ServiceAppointment.WorkType.Name IN ('Tow Pick-Up','Tow Drop-Off','Battery','Tire','Lockout','Winch Out','Fuel','Locksmith','EV') AND CreatedDate >= THIS_YEAR GROUP BY ServiceResource.Name HAVING COUNT(Id) > 5`

---

## Type 1: Fleet Drivers (`ERS_Driver_Type__c = 'Fleet Driver'`)
AAA employees, AAA trucks, 2 fleet garages.

**89 total records. 48 real road drivers. 41 NOT road drivers.**

### Real Road Drivers (48) — ALL have GPS, ALL syncing to STM via FSL app:
Frankie Giordano (612), Chris Bortz (610), Mike Klotz (593), Marcus Gibson (513), Christopher Reeves (508), Isaiah Carter-Faires (503), Kevin Wheeler (492), Arthur Yates Jr. (468), David Black (465), Marquan Gates (453), Mohamed Sillah (442), Jeffery Luxon Jr. (435), James Malelis (429), Stephen Rogers (420), Andrew Salvagni (419), Albert Rhodes (409), Joshua Catlin (403), Jacob Schaich (399), Allen Walrath (395), Christian Tabak (393), Isaiah Timmons (390), Jarron Wiggins (381), Lorenzo Grainger (366), Charles Gallagher Sr. (361), Christopher Mcarthur (348), Ryan Nolan (342), Jetin Huang (340), Christopher Merrill (333), Ernest Patterson (328), Nick Giachetti (309), McKenzie Happle (304), Robert Ham (299), Richard Schaad (232), Alex Cady (185), Eric Rogers (133), Dan Rivera (78), Jeff Sgarlata (75), Brian Young Jr (61), Kenneth Kirkendoll (56), Benedict Mannara (50), Rashaan Sumlin (28), Scott Swank (25), Bryan Jajkowski (18), Jawill Brown (GPS but 0 dispatches 2026)
*(numbers = dispatches in 2026)*

### Office Staff — Misclassified as Fleet Driver (NOT road drivers, NO GPS expected):
- **Emma Johnson** (162 dispatches) — TRAVEL AGENT: "Existing Trip Service", "International - Tour", "Cruise – Ocean", "Car/Hotel"
- **Denny Soliday** (93) — INSURANCE AGENT: "Personal Lines - Sales/Service"
- **Juliana Calamis** (31) — INSURANCE AGENT: "Personal Lines - Service/Sales"
- **Michael Pappa** (5) — INSURANCE/TRAVEL
- **Vanessa Quiles** (2) — INSURANCE/TRAVEL

### System/Placeholder Records (NOT humans):
- "0 SMOI Holding", "000-ROC M SPOT" (9 dispatches), "000-ST Spot" (7), "000-WNY M Spot" (20), "000-CNY/NC SPOT" (13), "100A Driver" (2), "Travel User"

### Test Records (11):
Test ERS Driver 1-10, TEST ERS - SR1

### Inactive (marked active but 0 dispatches in 2026):
Adrienne Giordano, Amy Chaudhari, Antonio Hatch Jr., Domonique Acoff, Edwin Espinal, Grace Murphy, Hannah Vought, Hayley Israel, James Fleming, Jason Eckberg, Jon Carroll, Kathy Osuch, Kory Howell, Makur Mading, Melissa McCarthy, Michael Schaefer, Paul Joseph, Sandra Dola, Tana Garcia, Ted Tomasello

---

## Type 2: On-Platform Contractor Drivers (`ERS_Driver_Type__c = 'On-Platform Contractor Driver'`)
External tow company drivers who use the FSL mobile app. Dispatched through Salesforce FSL.

**232 total records. 126 dispatched in 2026. 180 have GPS.**

### Top Active Road Drivers (all ERS work types, all have GPS):
Jesse Smith (564), David Schell (498), Peter Kotvis (497), Jacob Wray (494), Christopher Yager (489), Kenneth Vanduzer (474), Ryan Farrell (468), Matthew Bruenn (454), David Buscemi (454), Michael Hucks (443), Brian Cullen (437), Dorwin "Doe" Lyboult (420), Anthony Tabb Jr (414), David Camacho (404), Billy Strong (399), Andrew Lacrosse (386), Jason Harper (366), Cody Wise (361), Matthew Bray (344), Mario Santana (335), Mark Ryan (334), Cody Stone (331), Shane Presley (326), Joel Isaman (325), Dale Bruno (323), Trenton Baker (323), Scott Hogan (311), Jotham Dengal (300), Michael Strong (298), Zach Rafferty (296), Joseph Laplaca (296), Steve Chastain (284), Chris Muzer (247), Caleb Bailey (238), Craig Camp (230), Howard Strong (226), Mary Anne Lyboult (224), Brandon Barclay (205), Zachary Ried (198), Michael Patchen (192), DJ Burdick (192), Richard Badi (186), Steven Colbert (183), Ryan Kennerson (168), Nate Daggett (166), MICHAEL SCHELL (161), Chad Ellis (154), Colby Wilson (144), Hunter Woodrich (140), John Ahrens (132), Adam Alzoubi (126), Devon Sheppard (121), Jim D Olney (120), Noah Mack (118), Roger Jaczynski (113), Basel Alzoubi (107), Joshua Borelli (104), Robert Druker (95), Robert Doleman (94), Dave Tiefert (90), Kain Bennett (90), Joshua Martinez (90), David Pombert (88), Robert Annarino (86), Justin McDonald (78), Chris Reed (73), Sonny Sech (73), Kaleb Reed (66), Matthew White (65), Willie Meeks (65), David Lamphere (64), Ian Camp (62), Joshua Hartley (62), MICHAEL LATTEN (61), Colton Verstraete (60), Jayden Weston (59), Isaac McKalsen (56), Darin Bresett (53), Chelsey Losey (52), DeQuan Drake (49), Larry Wise (48), Gaige Gonyeau (45), Ross Sutton (45), ADAM SCHREIER (43), Zach Davison (43), Perry Lewis (43), Jacob Monnat (43), Christopher Ayers (42), William Hawn (35), Brian Hughes (34), Alan Young (30), Keith Snyder (28), Jamie Noyes (25), Derek Fields (25), Isaiah Tine (22), Nick Devino (20), John Davison (15), Paul Johnson (15), Robert Lawrence (14), Robert Patterson (14), Locksmith (14), Michael Cutway (12), Alan Risley (10), Dominic Derrigo (9), James Pacello (6), Bryan Christmas (6), Steven Glenn (6), Richard Myers (5), Steve Kimmich (4), Ken Skinner (4), Anthony Casner (3), Robert Price (3), Anthony Hamilton (3), Brandon Dobbs (2), Marshall Dickson (2), Andrew Pelc (2), Andrew Bartlett (2), Joseph Owen (1), Thomas Rutherford (1), Russell Dean (1), Jeffrey Race (1), James Corino (1), Ricky VanTassel (1), Ronald Straub (1), Shop . (1)

### On-Platform Contractors WITH Dispatches but NO GPS (real road drivers):
- David Spilman (90 dispatches — Tow/Battery/Tire/Lockout)
- Jacob Monnat (43 — Tow/Battery/Tire/Lockout)
- Dominic Derrigo (9 — Tow/Winch/Lockout)
- Anthony Hamilton (3 — Winch/Battery)
- Richard Myers (5 — Tow/Winch)
- Brandon Dobbs (2 — Tow)
- Ricky VanTassel (1 — Winch)
- Thomas Rutherford (1 — Battery)
- Ronald Straub (1 — Locksmith)
- Robert Price (3 — Locksmith)
- Steve Kimmich (4 — Locksmith)
- "Locksmith" (14 — placeholder name)
- "Shop ." (1 — placeholder name)

**Reason for no GPS: UNKNOWN. These are real ERS road drivers dispatched through FSL but the app is not reporting their location.**

### On-Platform Contractors NOT dispatched in 2026 (106 records):
David Wyre, Jonathan Leiter, Randall Spoor, Anthony VanTassel, Zachery VanTassel, Robert Everett, Anthony Frungillo, Richard Snell, Charles Wilke, Joseph Copeland, Justin Race, Michael Sorenson, David Wolfe, Dean Lamphere, Edward Barnes, and ~91 more.

---

## Type 3: Off-Platform Contractor Drivers (`ERS_Driver_Type__c = 'Off-Platform Contractor Driver'`)
Towbook garages. Each record = an entire garage, NOT an individual driver.

**72 total records. 63 actively dispatched. 0 GPS (expected — no FSL app).**

Top: Towbook-076DO (24,935), Towbook-420 (7,328), Towbook-053 (4,689), Towbook-641 (3,477), Towbook-4635 (3,255), Towbook-464 (3,112), Towbook-446 (3,024), Towbook-443 (2,543), Towbook-752 (2,226), Towbook-4635D (1,981)

**Will NEVER have GPS. Dispatched via Towbook system, not FSL.**

---

## Type 4: Null Driver Type (`ERS_Driver_Type__c = null`)
**124 records. 0 GPS. 0 dispatches checked.** Likely legacy/misconfigured records.

---

## Summary: Real Active Road Drivers

| Category | Count | GPS Working | GPS → STM Syncing |
|----------|-------|------------|-------------------|
| Fleet road drivers | 48 | **48 (100%)** | YES (app does it) |
| On-Platform Contractor road drivers | ~126 | ~115 (91%) | YES (app does it) |
| On-Platform Contractors, no GPS | ~11 real + 2 placeholders | NO | N/A |
| Off-Platform (Towbook garages) | 63 | 0 | NEVER |
| Office staff (Travel/Insurance) | ~5 | 0 | N/A — not drivers |
| Test/placeholder/inactive | ~175 | 0 | N/A |

**Key finding: 100% of fleet road drivers have GPS and STM sync working. ~91% of On-Platform Contractors do too. The FSL app syncs GPS → STM automatically. No custom sync job is needed.**
