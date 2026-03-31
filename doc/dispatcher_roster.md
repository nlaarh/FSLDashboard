---
name: Dispatcher Roster — Who Assigns Calls
description: Complete breakdown of who creates AssignedResource records (dispatches calls). System users vs human dispatchers vs self-assigning drivers. Verified Mar 15, 2026.
type: project
---

# Dispatcher Roster (Verified Mar 15, 2026)

## How Dispatchers Are Identified
There is NO "Dispatcher" table or role field in Salesforce. Dispatchers are identified by `AssignedResource.CreatedBy` — whoever creates the record linking a driver to a ServiceAppointment is the dispatcher.

---

## System/Integration Users (Auto-Dispatch)

These are NOT humans. They are system accounts that auto-assign calls:

| Name | Dispatches 2026 | Last Active | What It Is |
|------|----------------|-------------|-----------|
| IT System User | 37,827 | Mar 15 | Main system auto-dispatch |
| Mulesoft Integration | 32,051 | Mar 15 | Mulesoft ERS auto-scheduling (ERS_SA_AutoSchedule) |
| Replicant Integration User | 10,793 | Mar 15 | Replicant AI/IVR system |
| Platform Integration User | 1,820 | Feb 12 | Salesforce platform automation (stopped Feb 12?) |

**Total auto-dispatched: ~82,491 (78% of all dispatches)**

---

## Human Dispatchers (Manual Dispatch)

These are real people working in the dispatch center who manually assign calls to drivers.

### Top Dispatchers (>500 dispatches in 2026):
| Name | Dispatches | Last Active | Status |
|------|-----------|-------------|--------|
| Paige White | 2,487 | Mar 15 | Active — top human dispatcher |
| Danielle Derider | 2,145 | Mar 5 | May have left/transferred (last active Mar 5) |
| Corrine Roggow | 2,100 | Mar 14 | Active |
| Kateri Filippi | 2,095 | Mar 13 | Active |
| Diana Oakes | 2,087 | Mar 14 | Active |
| Lynn Pilarski | 1,044 | Mar 14 | Active |
| Aimee Perkins | 1,028 | Mar 13 | Active |
| Janice Sims | 922 | Mar 14 | Active |
| Katie Tamez | 725 | Mar 13 | Active |
| Katie Kelsey | 620 | Mar 12 | Active |
| Deonna Massey | 594 | Mar 13 | Active |
| Alex Thruston | 587 | Mar 10 | Active |
| Jay Miller | 567 | Mar 15 | Active |
| Jon Carroll | 554 | Mar 13 | Active |
| Joseph Hoefner | 533 | Mar 15 | Active |
| Jeremy Harrington | 533 | Mar 13 | Active |
| Matthew Spencer | 505 | Mar 15 | Active |

### Mid-Volume Dispatchers (200-500):
Debbie Taylor (490), Kathleen Reeve (483), Kenneth White (470), Jonathan Curry (465), Domingo Santiago (453), Kelli Ramsey (451), Jermaine Harrison (450), Jeffrey Griggs (439), Bianca Curtis (428), Maggie Woodman (414), Rosalia Avolio (413), Christina Reichel (391), Tyler LaFave (387), Paris Dillard (386), Noah Epolito (378), Ashley Lloyd (376), Aaron Jordan (375), Justine Semple (375), Tammy Johnson (365), Kyleea Baez (364), Ahsan Mahmood (363), Kristin Jackson (359), Candace Cicoria (352), Catherine Alger (346), Amanda Grover (345), Rosalind Philp (345), Shamyia Sirmons (341), Laurie Robins (341), Nkem George (335), Nasir Sykes (335), Arthur Domingos (331), Annette Eaddy (328), Megan Sullivan (302), Heather Boyd (300), Latisha Duncan (299), Sarah Shengulette (298), Samantha Hendrix (297), Antoinette King (296), Shawn Gancasz (281), Cynthia Marshall (273), Roseanne Schaefer (270), Elias Bahry (263), Jeffery Sgarlata (258), Brittany Ayers (251), Agnes Jones (248), Zannatul Fardaus (247), Kristen Hartman (245), Amanda Wrona (240), Marquis Nichols (240), Lakeshia Santos (239), Shauntavia Slaughter (233), Carol Welch (220), Nelsena Stroud (218), Jillian Tylec-Remacle (217), Richard Barrett (213), Tynan Granger (209), Gabrielle Kalinowski (206), Ashley Gielow (200)

### Lower-Volume Dispatchers (100-200):
Chantele Ross (196), Mamie Cimato (185), John DeNicola (179), Regina Appleberry (176), Yasmin Brown (170), Nigel Wedderburn (168), Elizabeth Proper (164), Gianna Felton (164), Jacqueline Nieman (158), Meghan Sheehan (157), Richard Yauger (157), Robin Mitchell (157), Stacey Turnbull (156), Kimberly Aney (153), Joyce Foglia Kellner (152), Eric Hawk (150), Grace Vesper (146), Donna Catherman (145), Michelle Szlapak (143), Bethany Steves (142), Catherine McCarthy (142), Jennie Todd (141), Marneen Carter (141), Lisa Asito (140), Tyler Buffington (138), Penny Kellner (137), Mason Saunders (136), Carmen Tang (133), Jacqueline Stephens (133), Lauren Hanvey (131), Katie Eppolito (130), Jayne Kaiser (126), Bethany Heidle (125), Joanna Voigt (122)

---

## Dual-Role: Names That Appear as BOTH Dispatcher AND Driver

These people show up in AssignedResource.CreatedBy (they assigned calls) AND also as ServiceResource (they received calls). They may be drivers who self-assign, or supervisors who also drive:

| Name | As Dispatcher | As Driver | Notes |
|------|--------------|-----------|-------|
| Matthew Bray | 370 dispatches created | 344 dispatches received | On-Platform Contractor — likely self-assigning |
| Trenton Baker | 255 created | 323 received | On-Platform Contractor |
| Joel Isaman | 195 created | 325 received | On-Platform Contractor |
| Ryan Kennerson | 168 created | 168 received | On-Platform Contractor |
| Alan Young | 158 created | 30 received | On-Platform Contractor |
| Emma Johnson | 162 created | 162 received (Travel) | Office staff — Travel agent assigning her own appointments |
| Jon Carroll | 554 created | 0 ERS received | Dispatcher only (also has a Fleet Driver SR record but 0 ERS dispatches) |
| Jeffery Sgarlata | 258 created | 75 received | Fleet Driver AND dispatcher? |

---

## Summary

| Category | Count | Dispatches 2026 | % of Total |
|----------|-------|----------------|-----------|
| System/Integration users | 4 | ~82,491 | ~78% |
| Human dispatchers | ~90+ | ~23,000+ | ~22% |
| **Total** | | **~105,000+** | |

**Key insight:** ~78% of dispatches are automated (Mulesoft + IT System User + Replicant). Human dispatchers handle ~22%, which is the manual dispatch queue.
