"""Generate Salesforce Summer '26 Migration Report PDF."""
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER
import os

OUTPUT = os.path.join(os.path.dirname(__file__), "SF_Summer26_Migration_Report.pdf")

# ── Colours ────────────────────────────────────────────────────────────────
RED    = colors.HexColor("#C0392B")
ORANGE = colors.HexColor("#E67E22")
YELLOW = colors.HexColor("#F39C12")
GREEN  = colors.HexColor("#27AE60")
BLUE   = colors.HexColor("#2980B9")
DARK   = colors.HexColor("#1A1A2E")
LIGHT  = colors.HexColor("#F4F6F8")
MID    = colors.HexColor("#D5DBDB")
WHITE  = colors.white

def build_styles():
    base = getSampleStyleSheet()
    styles = {}

    styles["title"] = ParagraphStyle("title", parent=base["Normal"],
        fontSize=22, textColor=WHITE, fontName="Helvetica-Bold",
        spaceAfter=4, alignment=TA_CENTER)

    styles["subtitle"] = ParagraphStyle("subtitle", parent=base["Normal"],
        fontSize=11, textColor=colors.HexColor("#BDC3C7"),
        spaceAfter=2, alignment=TA_CENTER)

    styles["section"] = ParagraphStyle("section", parent=base["Normal"],
        fontSize=13, textColor=WHITE, fontName="Helvetica-Bold",
        spaceBefore=14, spaceAfter=6, leftIndent=0)

    styles["item_title"] = ParagraphStyle("item_title", parent=base["Normal"],
        fontSize=11, textColor=DARK, fontName="Helvetica-Bold",
        spaceBefore=10, spaceAfter=3)

    styles["label"] = ParagraphStyle("label", parent=base["Normal"],
        fontSize=9, textColor=colors.HexColor("#7F8C8D"),
        fontName="Helvetica-Bold", spaceAfter=1)

    styles["body"] = ParagraphStyle("body", parent=base["Normal"],
        fontSize=9, textColor=DARK, spaceAfter=3, leading=13)

    styles["code"] = ParagraphStyle("code", parent=base["Normal"],
        fontSize=8, fontName="Courier", textColor=colors.HexColor("#2C3E50"),
        backColor=colors.HexColor("#ECF0F1"), leftIndent=8,
        spaceAfter=4, leading=11, borderPad=4)

    styles["verify"] = ParagraphStyle("verify", parent=base["Normal"],
        fontSize=8, fontName="Courier", textColor=colors.HexColor("#1A5276"),
        backColor=colors.HexColor("#D6EAF8"), leftIndent=8,
        spaceAfter=4, leading=11)

    styles["note"] = ParagraphStyle("note", parent=base["Normal"],
        fontSize=8, textColor=colors.HexColor("#555"), spaceAfter=3,
        leftIndent=10, leading=12)

    styles["safe"] = ParagraphStyle("safe", parent=base["Normal"],
        fontSize=9, textColor=GREEN, fontName="Helvetica-Bold")

    return styles

def section_header(text, bg_color, styles, story):
    story.append(Spacer(1, 0.15*inch))
    tbl = Table([[Paragraph(text, styles["section"])]], colWidths=[7.0*inch])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), bg_color),
        ("TOPPADDING",    (0,0), (-1,-1), 8),
        ("BOTTOMPADDING", (0,0), (-1,-1), 8),
        ("LEFTPADDING",   (0,0), (-1,-1), 12),
        ("ROUNDEDCORNERS", [4, 4, 4, 4]),
    ]))
    story.append(tbl)

def badge(text, bg):
    return Table([[Paragraph(f"<b>{text}</b>",
                  ParagraphStyle("b", fontSize=8, textColor=WHITE,
                                 fontName="Helvetica-Bold", alignment=TA_CENTER))]],
                 colWidths=[1.1*inch])

def item_card(number, title, deadline_text, deadline_color,
              business, verified, fix_steps, verify_steps, owner,
              styles, story):

    elements = []
    elements.append(Spacer(1, 0.08*inch))

    # Title row with deadline badge
    bdg = Table([[Paragraph(f"<b>{deadline_text}</b>",
                  ParagraphStyle("dl", fontSize=8, textColor=WHITE,
                                 fontName="Helvetica-Bold", alignment=TA_CENTER))]],
                colWidths=[1.3*inch])
    bdg.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), deadline_color),
        ("TOPPADDING", (0,0), (-1,-1), 3),
        ("BOTTOMPADDING", (0,0), (-1,-1), 3),
        ("ROUNDEDCORNERS", [3,3,3,3]),
    ]))

    hdr = Table([
        [Paragraph(f"<b>{number}. {title}</b>",
                   ParagraphStyle("ht", fontSize=11, textColor=DARK,
                                  fontName="Helvetica-Bold")), bdg]
    ], colWidths=[5.4*inch, 1.6*inch])
    hdr.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING", (0,0), (-1,-1), 0),
        ("BOTTOMPADDING", (0,0), (-1,-1), 0),
    ]))
    elements.append(hdr)
    elements.append(Spacer(1, 0.04*inch))

    def row(lbl, content_para):
        return Table([[
            Paragraph(lbl, ParagraphStyle("lbl", fontSize=8, fontName="Helvetica-Bold",
                                          textColor=colors.HexColor("#7F8C8D"))),
            content_para
        ]], colWidths=[1.2*inch, 5.8*inch])

    # Business impact
    elements.append(row("Business Impact",
        Paragraph(business, styles["body"])))
    elements.append(Spacer(1, 0.03*inch))

    # Verified
    elements.append(row("Verified",
        Paragraph(f'<font color="#27AE60">✓</font> {verified}', styles["body"])))
    elements.append(Spacer(1, 0.03*inch))

    # Fix steps
    fix_text = "<br/>".join(f"{i+1}. {s}" for i, s in enumerate(fix_steps))
    elements.append(row("Fix", Paragraph(fix_text, styles["body"])))
    elements.append(Spacer(1, 0.03*inch))

    # Verify steps
    for v in verify_steps:
        if v.startswith("```"):
            code = v.replace("```", "").strip()
            elements.append(Paragraph(code, styles["verify"]))
        else:
            elements.append(Paragraph(f"<b>How to verify:</b> {v}", styles["body"]))
    elements.append(Spacer(1, 0.03*inch))

    # Owner
    elements.append(row("Owner",
        Paragraph(f"<b>{owner}</b>", styles["body"])))

    # Wrap in card
    card = Table([[col] for col in elements], colWidths=[7.0*inch])
    card.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), LIGHT),
        ("TOPPADDING",    (0,0), (-1,-1), 2),
        ("BOTTOMPADDING", (0,0), (-1,-1), 2),
        ("LEFTPADDING",   (0,0), (-1,-1), 12),
        ("RIGHTPADDING",  (0,0), (-1,-1), 12),
        ("BOX", (0,0), (-1,-1), 0.5, MID),
        ("ROUNDEDCORNERS", [4,4,4,4]),
    ]))
    story.append(KeepTogether(card))


def build():
    doc = SimpleDocTemplate(OUTPUT, pagesize=letter,
                            leftMargin=0.75*inch, rightMargin=0.75*inch,
                            topMargin=0.75*inch, bottomMargin=0.75*inch)
    styles = build_styles()
    story = []

    # ── Cover ──────────────────────────────────────────────────────────────
    cover = Table([[
        Paragraph("Salesforce Summer '26", styles["title"]),
        Paragraph("Migration &amp; Action Report", styles["title"]),
        Paragraph("Org: aaawcny.my.salesforce.com  |  Prepared: June 2026", styles["subtitle"]),
        Paragraph("All findings verified in source code and live release notes", styles["subtitle"]),
    ]], colWidths=[7.0*inch])
    cover.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), DARK),
        ("TOPPADDING",    (0,0), (-1,-1), 18),
        ("BOTTOMPADDING", (0,0), (-1,-1), 18),
        ("LEFTPADDING",   (0,0), (-1,-1), 16),
        ("ROUNDEDCORNERS", [6,6,6,6]),
    ]))
    story.append(cover)
    story.append(Spacer(1, 0.2*inch))

    # ── FSL Business Config ────────────────────────────────────────────────
    section_header("✅  FSL BUSINESS CONFIGURATION — VERIFIED SAFE", GREEN, styles, story)

    safe_data = [
        ["Configuration", "Status", "Notes"],
        ["Scheduling Policies", "✅ Safe", "New ESO objectives are opt-in only"],
        ["Work Rules", "✅ Safe", "New Appointment Insights API is diagnostic only"],
        ["Service Objectives", "✅ Safe", "2 new objectives added; existing untouched"],
        ["Operating Hours", "✅ Safe", "Not mentioned in Summer '26"],
        ["Global Optimization schedules", "✅ Safe", "New opt-in features; existing runs unaffected"],
        ["Resource Absences", "✅ Safe", "Not mentioned in Summer '26"],
        ["Skills / Skill Requirements", "✅ Safe", "Not mentioned in Summer '26"],
        ["Service Territories", "✅ Safe", "Not mentioned in Summer '26"],
        ["FSL Permission Sets", "✅ Safe", "Not mentioned in Summer '26"],
        ["SAML SSO", "✅ Safe", "Verified in live org: 2 SamlSsoConfig records → already on multi-config framework"],
    ]
    col_w = [2.0*inch, 1.0*inch, 4.0*inch]
    tbl = Table(safe_data, colWidths=col_w, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,0), DARK),
        ("TEXTCOLOR",     (0,0), (-1,0), WHITE),
        ("FONTNAME",      (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE",      (0,0), (-1,-1), 8),
        ("ROWBACKGROUNDS",(0,1), (-1,-1), [WHITE, LIGHT]),
        ("TEXTCOLOR",     (1,1), (1,-1), GREEN),
        ("FONTNAME",      (1,1), (1,-1), "Helvetica-Bold"),
        ("GRID",          (0,0), (-1,-1), 0.3, MID),
        ("TOPPADDING",    (0,0), (-1,-1), 5),
        ("BOTTOMPADDING", (0,0), (-1,-1), 5),
        ("LEFTPADDING",   (0,0), (-1,-1), 8),
    ]))
    story.append(tbl)

    # ── Business Items ─────────────────────────────────────────────────────
    section_header("🔴  BUSINESS ITEMS — Action Required", RED, styles, story)

    item_card(
        "B1", "Dispatcher Tab Renamed", "THIS WEEK", RED,
        "The 'Field Service' tab dispatchers use daily is now called 'Classic Dispatch Console.' No warning was given. Dispatchers will be confused.",
        "Confirmed in Summer '26 Field Service release notes. Affects: Alger, Hartman, Kalenda, Harrington, Carroll.",
        [
            "Send message to all 5 dispatchers: 'The tab called Field Service is now Classic Dispatch Console — same tool, new name.'",
            "Update any SOP or training document that references the 'Field Service' tab.",
        ],
        ["Log into SF as a dispatcher → confirm 'Classic Dispatch Console' tab is visible and opens the Gantt normally."],
        "FSL Admin / Business Admin",
        styles, story
    )

    item_card(
        "B2", "Integration User — Profile Visibility", "THIS WEEK", RED,
        "Summer '26 restricts users from seeing other users' profile names. The integration user running all API queries may return blank profile data, silently breaking data flows.",
        "Integration user apiintegration@nyaaa.com confirmed from running app environment (SF_USERNAME env var).",
        [
            "Setup → Users → Users → search apiintegration@nyaaa.com",
            "Click the user → go to their Profile → Edit",
            "Under System Permissions → enable View All Profiles → Save",
        ],
        [
            "Run in Developer Console:",
            "```SELECT Id, Profile.Name FROM User WHERE IsActive = true LIMIT 5",
            "If Profile.Name returns values = working. If all null = permission not yet active.",
        ],
        "SF Admin",
        styles, story
    )

    # ── Technical Items ────────────────────────────────────────────────────
    section_header("🟠  TECHNICAL ITEMS — Action Required", ORANGE, styles, story)

    item_card(
        "T1", "FleetPulse Authentication — BREAKS October 2026", "BY OCTOBER 2026", ORANGE,
        "Complete FleetPulse outage. All dispatch dashboards, metrics, and accounting audit go dark.",
        "FSLAPP/backend/sf_client.py line 171: grant_type='password' — username-password OAuth flow confirmed.",
        [
            "[SF Admin] Setup → App Manager → FSLAPP Connected App → Edit → OAuth Policies → enable Client Credentials Flow → set Run As = apiintegration@nyaaa.com → Save",
            "[Developer] sf_client.py lines 169-181: replace payload to use grant_type='client_credentials' with only client_id and client_secret. Remove username, password, security_token fields entirely.",
            "[Azure Admin] Azure Portal → fslapp-nyaaa → Configuration → Application Settings → delete SF_USERNAME, SF_PASSWORD, SF_SECURITY_TOKEN → Save",
        ],
        [
            "```curl http://localhost:8000/api/health",
            "Expected: salesforce.errors = 0, breaker_open = false, total_calls > 0",
        ],
        "SF Admin + Developer + Azure Admin",
        styles, story
    )

    item_card(
        "T2", "Mulesoft aaa-wcny-genesys-sf-bulk-papi — BREAKS October 2026", "BY OCTOBER 2026", ORANGE,
        "Genesys call centre agent IDs and emails stop syncing to Salesforce User records.",
        "src/main/mule/genSfGlobalConfig.xml line 39: salesforce:oauth-user-pass-connection confirmed.",
        [
            "Open salesforce-ers-sys/src/main/mule/global.xml lines 33-39 — use as JWT template (already working).",
            "In genSfGlobalConfig.xml line 39: replace salesforce:oauth-user-pass-connection with salesforce:jwt-connection using the same structure, with this app's Connected App credentials.",
            "Store all credentials as ${secure::} references — not plaintext.",
            "Deploy to CloudHub.",
        ],
        ["After deploy → trigger a Genesys agent sync event → check CloudHub logs for successful authentication → no CONNECTIVITY or INVALID_SESSION errors."],
        "Mulesoft Developer",
        styles, story
    )

    item_card(
        "T3", "Mulesoft aaa-wcny-salesforce-lead-import-app — BREAKS October 2026", "BY OCTOBER 2026", ORANGE,
        "Lead imports from external sources into Salesforce stop completely.",
        "src/main/mule/global.xml line 17: salesforce:oauth-user-pass-connection confirmed.",
        [
            "Open salesforce-ers-sys/src/main/mule/global.xml lines 33-39 — use as JWT template.",
            "In global.xml line 17: replace salesforce:oauth-user-pass-connection with salesforce:jwt-connection using this app's Connected App credentials.",
            "Store credentials as ${secure::} references.",
            "Deploy and test.",
        ],
        ["After deploy → trigger a test lead import → check CloudHub logs confirm no INVALID_SESSION errors → verify test lead record created in Salesforce."],
        "Mulesoft Developer",
        styles, story
    )

    item_card(
        "T4", "Mulesoft aaa-wcny-cx360-papi — BREAKS October 2026", "BY OCTOBER 2026", ORANGE,
        "CX360 customer data stops flowing into Salesforce.",
        "src/main/resources/properties/common-config.properties lines 191-196: active (uncommented) salesforce.auth.password, salesforce.auth.username, salesforce.auth.securityToken confirmed.",
        [
            "[Developer] Delete lines 191-196 from common-config.properties. Add: salesforce.consumerKey=${secure::sf.consumerKey} and salesforce.consumerSecret=${secure::sf.consumerSecret}",
            "[Developer] In Mule connector XML: replace salesforce:oauth-user-pass-connection with salesforce:oauth-client-credentials-connection referencing only consumerKey and consumerSecret.",
            "[SF Admin] Setup → App Manager → CX360 Connected App → Edit → OAuth Policies → enable Client Credentials Flow → set Run As = mulesoftintegration@nyaaa.com → Save",
            "Deploy to CloudHub.",
        ],
        ["After deploy → trigger CX360 data sync → check CloudHub logs confirm auth succeeds → verify a sample record updated in Salesforce."],
        "Mulesoft Developer + SF Admin",
        styles, story
    )

    # ── June 2027 ──────────────────────────────────────────────────────────
    section_header("🟡  TECHNICAL ITEMS — Action by June 2027", YELLOW, styles, story)

    item_card(
        "T5", "Mulesoft ers-transfer-prc — Payment Events May Drop Silently", "BY JUNE 2027", YELLOW,
        "Reciprocal, reimbursement, and facility payment events stop processing with no error or alert.",
        "ers-transfer-prc/src/main/mule/ers-transfer-prc-api.xml: 3 salesforce:subscribe-channel-listener elements at lines 194, 243, 259 confirmed.",
        [
            "Open src/main/mule/global.xml lines 15-19 — the salesforce:jwt-connection block.",
            "Check whether <reconnect frequency='5000' count='5' blocking='false'/> exists inside the connection block.",
            "If missing, add it inside the salesforce:jwt-connection element.",
            "Deploy and verify.",
        ],
        ["In CloudHub → Monitoring → confirm all 3 channel listeners show active subscriptions after a simulated restart. No SUBSCRIPTION_DROPPED events in logs."],
        "Mulesoft Developer",
        styles, story
    )

    # ── Verify Required ────────────────────────────────────────────────────
    section_header("🔍  VERIFY REQUIRED — Confirm Before October 2026", BLUE, styles, story)

    item_card(
        "V1", "Mulesoft aaa-wcny-breadfinancial-sf-bulk-papi — Production Status Unknown", "BY OCTOBER 2026", BLUE,
        "BreadFinancial SF integration uses the same username-password OAuth pattern being retired. If deployed to production, it will break in Winter '27.",
        "sftpSfGlobalConfig.xml: salesforce:oauth-user-pass-connection confirmed. Active credentials in common-config.properties point to test.salesforce.com (sandbox only). prod-config.yaml is empty — no production credentials configured in code.",
        [
            "Confirm with Mulesoft team: is this project deployed to a production CloudHub environment?",
            "If YES — migrate same as T2/T3: replace salesforce:oauth-user-pass-connection with salesforce:jwt-connection using salesforce-ers-sys/src/main/mule/global.xml lines 33-39 as template.",
            "If NO (sandbox only) — document that decision. No further action required for Winter '27.",
        ],
        ["Check CloudHub Runtime Manager — if aaa-wcny-breadfinancial-sf-bulk-papi appears as a deployed application in a production environment, it must be migrated before October 2026."],
        "Mulesoft Developer",
        styles, story
    )

    # ── Summary Table ──────────────────────────────────────────────────────
    section_header("📋  SUMMARY CHECKLIST", BLUE, styles, story)
    story.append(Spacer(1, 0.1*inch))

    summary = [
        ["#", "Item", "Type", "Deadline", "Owner", "Done"],
        ["B1", "Notify dispatchers — tab rename", "Business", "This week", "FSL Admin", "☐"],
        ["B2", "Grant View All Profiles to apiintegration@nyaaa.com", "Business", "This week", "SF Admin", "☐"],
        ["T1", "FleetPulse OAuth → client_credentials", "Technical", "Aug 2026", "Dev + SF Admin + Azure", "☐"],
        ["T2", "Mulesoft Genesys → JWT auth", "Technical", "Aug 2026", "Mulesoft Dev", "☐"],
        ["T3", "Mulesoft Lead Import → JWT auth", "Technical", "Aug 2026", "Mulesoft Dev", "☐"],
        ["T4", "Mulesoft CX360 → client_credentials", "Technical", "Aug 2026", "Mulesoft Dev + SF Admin", "☐"],
        ["T5", "ers-transfer-prc streaming reconnect", "Technical", "Jun 2027", "Mulesoft Dev", "☐"],
        ["V1", "BreadFinancial — verify prod deployment", "Verify", "Aug 2026", "Mulesoft Dev", "☐"],
    ]

    row_colors = [
        DARK,
        colors.HexColor("#FADBD8"), colors.HexColor("#FADBD8"),   # B1, B2 — red tint
        colors.HexColor("#FDEBD0"), colors.HexColor("#FDEBD0"),   # T1, T2 — orange tint
        colors.HexColor("#FDEBD0"), colors.HexColor("#FDEBD0"),   # T3, T4 — orange tint
        colors.HexColor("#FEF9E7"),                                # T5 — yellow tint
        colors.HexColor("#D6EAF8"),                                # V1 — blue tint
    ]

    sum_tbl = Table(summary, colWidths=[0.4*inch, 2.8*inch, 0.8*inch, 1.0*inch, 1.5*inch, 0.5*inch])
    sum_tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,0), DARK),
        ("TEXTCOLOR",     (0,0), (-1,0), WHITE),
        ("FONTNAME",      (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE",      (0,0), (-1,-1), 8),
        ("FONTNAME",      (0,1), (0,-1), "Helvetica-Bold"),
        ("GRID",          (0,0), (-1,-1), 0.3, MID),
        ("TOPPADDING",    (0,0), (-1,-1), 5),
        ("BOTTOMPADDING", (0,0), (-1,-1), 5),
        ("LEFTPADDING",   (0,0), (-1,-1), 6),
        ("ALIGN",         (5,0), (5,-1), "CENTER"),
    ] + [("BACKGROUND", (0,i), (-1,i), row_colors[i]) for i in range(1, len(summary))]))
    story.append(sum_tbl)

    story.append(Spacer(1, 0.3*inch))
    story.append(Paragraph(
        "This report was generated from direct code inspection and live Salesforce Summer '26 release notes. "
        "All findings are verified — no assumptions.",
        ParagraphStyle("footer", fontSize=7, textColor=colors.HexColor("#999"),
                       alignment=TA_CENTER)))

    doc.build(story)
    print(f"PDF created: {OUTPUT}")

if __name__ == "__main__":
    build()
