#!/usr/bin/env python3
"""AAA ERS Dispatch Algorithm -- Decision Tree PDF  |  run: python3 doc/generate_dispatch_algorithm.py"""
from fpdf import FPDF
from datetime import datetime
import math

NAVY=(0,51,102);BLUE=(0,102,204);LBLUE=(225,238,255);DBLUE=(0,70,140)
GREEN=(0,110,55);LGREEN=(220,248,232);RED=(180,25,25);LRED=(255,230,230)
ORANGE=(190,85,0);LORNG=(255,238,215);PURPLE=(100,0,170);LPURP=(238,220,255)
GRAY=(110,110,110);LGRAY=(245,245,248);DGRAY=(45,45,45);WHITE=(255,255,255)
GOLD=(160,120,0);LGOLD=(255,248,200)

class PDF(FPDF):
    def header(self):
        if self.page_no()==1: return
        self.set_font('Helvetica','B',8); self.set_text_color(*GRAY)
        self.cell(150,5,'AAA WCNY -- FSL Dispatch Algorithm  |  Confidential')
        self.set_font('Helvetica','',8)
        self.cell(0,5,f'Page {self.page_no()}',align='R',new_x='LMARGIN',new_y='NEXT')
        self.set_draw_color(*BLUE); self.set_line_width(0.3)
        self.line(10,self.get_y(),200,self.get_y()); self.ln(3)
    def footer(self):
        self.set_y(-11); self.set_font('Helvetica','I',7); self.set_text_color(*GRAY)
        self.cell(0,5,f'Generated {datetime.now().strftime("%B %d, %Y")}  |  Verified from 662 Fleet AR records, March 2026',align='C')
    def h1(self,txt,color=NAVY):
        self.set_font('Helvetica','B',13); self.set_text_color(*color)
        self.cell(0,8,txt,new_x='LMARGIN',new_y='NEXT')
        self.set_draw_color(*BLUE); self.set_line_width(0.4)
        self.line(10,self.get_y(),200,self.get_y()); self.ln(4)
    def h2(self,txt,color=NAVY):
        self.set_font('Helvetica','B',10); self.set_text_color(*color)
        self.cell(0,7,txt,new_x='LMARGIN',new_y='NEXT'); self.ln(1)
    def body(self,txt,w=0):
        self.set_font('Helvetica','',9.5); self.set_text_color(*DGRAY)
        self.multi_cell(w or (self.w-self.l_margin-self.r_margin),5.2,txt); self.ln(2)
    def callout(self,txt,bg=LBLUE,fg=NAVY):
        W=self.w-self.l_margin-self.r_margin; x,y=self.get_x(),self.get_y()
        lines=(len(txt)//90)+1; h=6+lines*5.2
        self.set_fill_color(*bg); self.rect(x,y,W,h,'F')
        self.set_draw_color(*fg); self.set_line_width(0.8); self.line(x,y,x,y+h)
        self.set_xy(x+4,y+2); self.set_font('Helvetica','B',9); self.set_text_color(*fg)
        self.multi_cell(W-6,5.2,txt); self.ln(4)
    def table(self,headers,rows,widths):
        self.set_font('Helvetica','B',8); self.set_fill_color(*NAVY); self.set_text_color(*WHITE)
        for i,h in enumerate(headers): self.cell(widths[i],6.5,h,border=1,fill=True,align='C')
        self.ln(); self.set_font('Helvetica','',8.5); alt=False
        for row in rows:
            self.set_fill_color(*(LBLUE if alt else WHITE)); self.set_text_color(*DGRAY)
            for i,c in enumerate(row): self.cell(widths[i],6,str(c),border=1,fill=True)
            self.ln(); alt=not alt
        self.ln(3)
    def fpill(self,label,field,bg=LBLUE,fg=NAVY,w=92):
        x,y=self.get_x(),self.get_y()
        self.set_fill_color(*bg); self.set_draw_color(*fg); self.set_line_width(0.2)
        self.rect(x,y,w,13,'FD')
        self.set_xy(x+2,y+1); self.set_font('Helvetica','',7); self.set_text_color(*GRAY); self.cell(w-4,4,label)
        self.set_xy(x+2,y+5.5); self.set_font('Courier','B',8); self.set_text_color(*fg); self.cell(w-4,5,field)
        self.set_xy(x+w+3,y)

def rbox(p,x,y,w,h,text,bg,fg=NAVY,fs=8,bold=True):
    p.set_fill_color(*bg); p.set_draw_color(*fg); p.set_line_width(0.35); p.rect(x,y,w,h,'FD')
    p.set_font('Helvetica','B' if bold else '',fs); p.set_text_color(*fg)
    lines=text.split('\n'); lh=fs*0.44; ty=y+(h-len(lines)*lh)/2
    for ln in lines: p.set_xy(x,ty); p.cell(w,lh,ln,align='C'); ty+=lh

def diamond(p,cx,cy,hw,hh,text,bg,fg=NAVY,fs=7.5):
    corners=[(cx,cy-hh),(cx+hw,cy),(cx,cy+hh),(cx-hw,cy)]
    # fill
    p.set_draw_color(*bg); p.set_line_width(0.5)
    for dy in range(-int(hh)+1,int(hh)):
        frac=1-abs(dy)/hh; lx=cx-hw*frac; rx=cx+hw*frac; p.line(lx,cy+dy,rx,cy+dy)
    # border
    p.set_draw_color(*fg); p.set_line_width(0.35)
    for i in range(4): p.line(*corners[i],*corners[(i+1)%4])
    # text
    lines=text.split('\n'); lh=fs*0.43; ty=cy-len(lines)*lh/2
    for ln in lines:
        p.set_font('Helvetica','B',fs); p.set_text_color(*fg)
        p.set_xy(cx-hw+1,ty); p.cell(hw*2-2,lh,ln,align='C'); ty+=lh

def arw(p,x1,y1,x2,y2,col=GRAY,lw=0.4):
    p.set_draw_color(*col); p.set_line_width(lw); p.line(x1,y1,x2,y2)
    angle=math.atan2(y2-y1,x2-x1); s=2.2
    for da in(0.5,-0.5):
        p.line(x2,y2,x2-s*math.cos(angle-da),y2-s*math.sin(angle-da))

def lbl(p,x,y,txt,fs=7,col=GRAY):
    p.set_font('Helvetica','I',fs); p.set_text_color(*col); p.set_xy(x,y); p.cell(35,4,txt)

def elim(p,x,y,txt='Eliminate\ndriver',bg=LRED,fg=RED):
    rbox(p,x,y,30,10,txt,bg,fg,fs=6.5)

# ==============================================================================
# PAGE 1 -- Decision tree (LEFT) + Algorithm formulas (RIGHT)
# ==============================================================================
def page1(pdf):
    pdf.add_page()
    # title bar
    pdf.set_fill_color(*NAVY); pdf.rect(0,0,210,14,'F')
    pdf.set_xy(10,2); pdf.set_font('Helvetica','B',12); pdf.set_text_color(*WHITE)
    pdf.cell(140,10,'AAA ERS Fleet Dispatch -- Decision Tree & Algorithm')
    pdf.set_font('Helvetica','',8); pdf.set_text_color(180,205,235)
    pdf.cell(0,10,'Verified  |  Mar 2026  |  662 AR records',align='R')

    LX=8; LW=106; RX=LX+LW+4; RW=210-RX-8; TOP=17
    cx=LX+52  # centre of main flow in left col
    bw=62; bh=9; dw=39; dh=7

    y=TOP

    # [SA Created]
    rbox(pdf,cx-bw//2,y,bw,bh,'SA Created in Salesforce',NAVY,WHITE,fs=7.5)
    lbl(pdf,cx+bw//2+1,y+2,'SA.Lat/Lon, WorkType\nERS_PTA__c',fs=6)
    y+=bh; arw(pdf,cx,y,cx,y+4); y+=4

    # [Priority Matrix]
    rbox(pdf,cx-bw//2,y,bw,bh,'Priority Matrix Lookup',LORNG,ORANGE,fs=7.5)
    lbl(pdf,cx+bw//2+1,y+2,'Zone+WorkType\n->P2...P10',fs=6)
    y+=bh; arw(pdf,cx,y,cx,y+4); y+=4

    # [Try garage]
    cascade_y=y
    rbox(pdf,cx-bw//2,y,bw,8,'Try Next Priority Garage  (P2 first)',LGRAY,DGRAY,fs=7)
    y+=8; arw(pdf,cx,y,cx,y+4); y+=4

    # DEC A: drivers in territory?
    diamond(pdf,cx,y+dh,dw,dh,'Any drivers\nin territory?',LGREEN,GREEN)
    arw(pdf,cx-dw,y+dh,LX,y+dh,RED)
    arw(pdf,LX,y+dh,LX,cascade_y+4,RED)
    arw(pdf,LX,cascade_y+4,cx-bw//2,cascade_y+4,RED)
    lbl(pdf,LX+1,y+dh-4,'NO: try P3,P4...',fs=5.8,col=RED)
    y+=dh*2; arw(pdf,cx,y,cx,y+3); lbl(pdf,cx+2,y-1,'YES',fs=6,col=GREEN); y+=3

    # DEC B: skill match
    diamond(pdf,cx,y+dh,dw,dh,'Driver has\nrequired skill?',LGREEN,GREEN)
    elim(pdf,cx+dw+2,y+dh-5)
    arw(pdf,cx+dw,y+dh,cx+dw+2,y+dh,RED); lbl(pdf,cx+dw+1,y+dh-7,'NO',fs=6,col=RED)
    y+=dh*2; arw(pdf,cx,y,cx,y+3); lbl(pdf,cx+2,y-1,'YES',fs=6,col=GREEN); y+=3

    # DEC C: ResourceAbsence?
    diamond(pdf,cx,y+dh,dw,dh,'ResourceAbsence\nactive now?',LRED,RED)
    elim(pdf,cx+dw+2,y+dh-5,'Skip\ndriver')
    arw(pdf,cx+dw,y+dh,cx+dw+2,y+dh,RED); lbl(pdf,cx+dw+1,y+dh-7,'YES',fs=6,col=RED)
    y+=dh*2; arw(pdf,cx,y,cx,y+3); lbl(pdf,cx+2,y-1,'NO',fs=6,col=GREEN); y+=3

    # DEC D: GPS? (CRITICAL -- highlighted)
    gps_y=y
    pdf.set_draw_color(*RED); pdf.set_line_width(0.6)
    pdf.rect(cx-dw-4,y-1,dw*2+8,dh*2+9,'D')
    pdf.set_font('Helvetica','B',6); pdf.set_text_color(*RED)
    pdf.set_xy(cx-dw-3,y); pdf.cell(20,3.5,'!! CRITICAL')
    diamond(pdf,cx,y+dh+2,dw,dh,'Driver has GPS?\n(STM.Lat/Lon set)',LGOLD,GOLD,fs=7)
    y+=dh*2+4

    # YES -> left branch
    ygx=cx-dw-2
    arw(pdf,cx-dw,gps_y+dh+2,ygx,gps_y+dh+2,GREEN)
    rbox(pdf,ygx-30,gps_y+dh-2,30,9,'Use live GPS\nSTM.Lat/Lon',LGREEN,GREEN,fs=6.5)
    arw(pdf,ygx,gps_y+dh+2,ygx,y+2,GREEN); arw(pdf,ygx,y+2,cx,y+2,GREEN)
    lbl(pdf,ygx-34,gps_y+dh-4,'YES',fs=6,col=GREEN)

    # NO -> right branch (the problem)
    ngx=cx+dw+2
    arw(pdf,cx+dw,gps_y+dh+2,ngx,gps_y+dh+2,RED)
    rbox(pdf,ngx,gps_y+dh-2,31,9,'Fallback:\nGarage addr (WRONG!)',LRED,RED,fs=6.5)
    arw(pdf,ngx+15,gps_y+dh+7,ngx+15,y+2,RED); arw(pdf,ngx+15,y+2,cx,y+2,RED)
    lbl(pdf,ngx+1,gps_y+dh-4,'NO',fs=6,col=RED)

    arw(pdf,cx,y+2,cx,y+5); y+=5

    # [Calc distance]
    rbox(pdf,cx-bw//2,y,bw,8,'FSL road distance: location->SA',LBLUE,BLUE,fs=7)
    lbl(pdf,cx+bw//2+1,y+1,'AR.FSL__Estimated\nTravelDistanceFrom__c\n(road mi, NOT aerial)',fs=6)
    y+=8; arw(pdf,cx,y,cx,y+3); y+=3

    # DEC E: Max Travel From Home
    diamond(pdf,cx,y+dh,dw,dh,'Distance <=\nMax Travel rule?',LBLUE,BLUE)
    elim(pdf,cx+dw+2,y+dh-5)
    arw(pdf,cx+dw,y+dh,cx+dw+2,y+dh,RED); lbl(pdf,cx+dw+1,y+dh-7,'NO',fs=6,col=RED)
    y+=dh*2; arw(pdf,cx,y,cx,y+3); lbl(pdf,cx+2,y-1,'YES',fs=6,col=GREEN); y+=3

    # [Score candidates]
    rbox(pdf,cx-bw//2,y,bw,8,'Score by Travel (dist) or ASAP (time)',LPURP,PURPLE,fs=6.5)
    y+=8; arw(pdf,cx,y,cx,y+3); y+=3

    # DEC F: any candidates?
    diamond(pdf,cx,y+dh,dw,dh,'Any candidates\nqualify?',LGREEN,GREEN)
    arw(pdf,cx-dw,y+dh,LX+3,y+dh,RED)
    arw(pdf,LX+3,y+dh,LX+3,cascade_y+6,RED)
    arw(pdf,LX+3,cascade_y+6,cx-bw//2,cascade_y+6,RED)
    lbl(pdf,LX+4,y+dh-3,'NO: next P\nor manual',fs=5.5,col=RED)
    y+=dh*2; arw(pdf,cx,y,cx,y+3); lbl(pdf,cx+2,y-1,'YES',fs=6,col=GREEN); y+=3

    # [Assign]
    rbox(pdf,cx-bw//2,y,bw,9,'ASSIGN CLOSEST DRIVER\nAR created  |  SchedStartTime set',GREEN,WHITE,fs=7.5)
    y+=9; arw(pdf,cx,y,cx,y+3); y+=3

    # [Optimizer]
    diamond(pdf,cx,y+6,dw,6,'Optimizer ran?\n(every 15 min)',LPURP,PURPLE,fs=6.5)
    arw(pdf,cx+dw,y+6,cx+dw+10,y+6,GRAY); lbl(pdf,cx+dw+1,y+3,'NO: done',fs=6)
    y+=12; arw(pdf,cx,y,cx,y+3); lbl(pdf,cx+2,y-1,'YES',fs=6,col=PURPLE); y+=3

    rbox(pdf,cx-bw//2,y,bw,8,'ASAP recalc: reassign if\nSchedStartTime earlier',LPURP,PURPLE,fs=7)
    y+=8; arw(pdf,cx,y,cx,y+3); y+=3

    rbox(pdf,cx-bw//2,y,bw,9,'DRIVER DISPATCHED',DBLUE,WHITE,fs=9,bold=True)

    # ---- RIGHT: Formulas + algorithm in English ----------------------------
    def W(): return RW
    def rx(txt,bold=False,fs=8.5,col=DGRAY):
        pdf.set_font('Helvetica','B' if bold else '',fs); pdf.set_text_color(*col)
        pdf.set_x(RX); pdf.multi_cell(RW,4.5,txt)
    def rline(col=BLUE):
        pdf.set_draw_color(*col); pdf.set_line_width(0.25)
        pdf.line(RX,pdf.get_y(),RX+RW,pdf.get_y()); pdf.ln(2)
    def code(lines,bg=LGRAY,fg=NAVY):
        x,yy=RX,pdf.get_y(); h=len(lines)*4.8+4
        pdf.set_fill_color(*bg); pdf.set_draw_color(*fg); pdf.set_line_width(0.2)
        pdf.rect(x,yy,RW,h,'FD')
        for i,ln in enumerate(lines):
            pdf.set_xy(x+2,yy+2+i*4.8); pdf.set_font('Courier','',7.5)
            pdf.set_text_color(*fg); pdf.cell(RW-4,4.8,ln)
        pdf.ln(h+3)

    pdf.set_left_margin(RX); pdf.set_right_margin(210-RX-RW); pdf.set_xy(RX,TOP)

    rx('INITIAL DISPATCH -- Closest Driver',bold=True,fs=9,col=NAVY); rline()
    rx('Step 1: Get driver location',bold=True,fs=8,col=DBLUE)
    code(['IF STM.Latitude != null:','   location = STM.Lat/Lon  (live GPS)','ELSE:','   location = Garage.Lat/Lon  !! WRONG !!'],LGOLD,GOLD)
    rx('Step 2: Road distance (NOT Haversine)',bold=True,fs=8,col=DBLUE)
    code(['road_dist = FSL_road_routing(location, SA.Lat/Lon)','road_time = road_dist / speed  (0-56 mph varies)','# Haversine gives aerial only -- FSL uses real roads'],LBLUE,BLUE)
    rx('Step 3: Score and pick winner',bold=True,fs=8,col=DBLUE)
    code(['"Closest Driver" policy:','   Total = 0*ASAP + 100*road_dist','   Winner = LOWEST road_dist (after all filters)'],LBLUE,BLUE)

    pdf.ln(2); rx('OPTIMIZER -- ASAP Policy (every 15 min)',bold=True,fs=9,col=PURPLE); rline(PURPLE)
    code(['ASAP = max(SA.EarliestStartTime,','           driverLastJobEnd + road_time)','"Copy of Highest Priority" policy:','   Total = 1000*ASAP + 10*road_dist','   Winner = EARLIEST ASAP (can start soonest)'],LPURP,PURPLE)

    pdf.ln(2); rx('WHY DRIVERS CROSS',bold=True,fs=9,col=RED); rline(RED)
    rx('1. Driver has no GPS -> FSL uses garage address.\n   Garage != driver real position -> wrong "closest".',fs=8,col=DGRAY)
    rx('2. Optimizer ran 0 reassignments (7 days observed).\n   Initial suboptimal assignment was never corrected.',fs=8,col=DGRAY)
    rx('3. Skill filter forces longer route.\n   Tow call can only go to Tow-skilled driver.',fs=8,col=DGRAY)
    pdf.ln(1)
    rx('VERIFIED NUMBERS',bold=True,fs=9,col=NAVY); rline()
    facts=[('Mean road speed','24.9 mph  (0-56 mph range)'),
           ('Road vs aerial','1.21x median -- FSL road > Haversine'),
           ('ASAP gap median','36.8 min = workload + travel'),
           ('Fleet drivers with GPS','14/38 (37%) have STM coords'),
           ('Optimizer rewrites','0 of 662 in 7 days observed'),
           ('Cascade max retries','2  (AAA_ERS_Services__mdt)')]
    for k,v in facts:
        pdf.set_x(RX); pdf.set_font('Helvetica','B',7.5); pdf.set_text_color(*NAVY)
        pdf.cell(40,5,k+':')
        pdf.set_font('Helvetica','',7.5); pdf.set_text_color(*DGRAY)
        pdf.cell(0,5,v,new_x='LMARGIN',new_y='NEXT')

    pdf.set_left_margin(10); pdf.set_right_margin(10)

# ==============================================================================
# PAGE 2 -- Travel Score deep dive
# ==============================================================================
def page2(pdf):
    pdf.add_page()
    pdf.h1('Chapter 1 -- Travel Score: Distance, Speed, and the GPS Problem')
    pdf.callout('KEY: FSL uses ROAD-NETWORK routing (like Google Maps), NOT Haversine aerial formula. '
                'Our FSLAPP code uses Haversine as a fast approximation. '
                'FSL road distance is typically 1.2-1.5x larger than Haversine.',LRED,RED)
    pdf.h2('What Haversine Is (Our Code Only)')
    pdf.body('Haversine = straight-line aerial distance between two GPS points on a sphere.\n'
             '"How far if you could fly in a straight line?"\n\n'
             'Formula:  d = 2 x R x arcsin( sqrt( sin2(dLat/2) + cos(lat1)xcos(lat2)xsin2(dLon/2) ) )\n'
             '          R = 3,958.8 miles\n\n'
             'Used in: dispatch.py haversine()  |  simulator.py haversine()\n'
             'Speed assumption: 25 mph fixed  ->  travel_min = haversine_miles / 25 x 60')
    pdf.h2('What FSL Uses (Road-Network Routing)')
    pdf.body('Salesforce FSL calls a routing engine that calculates the actual road path.\n'
             'Result stored on AssignedResource record:\n\n'
             '  FSL__EstimatedTravelDistanceFrom__c  -- road miles from driver GPS to SA\n'
             '  FSL__EstimatedTravelTimeFrom__c      -- road travel minutes\n\n'
             'Verified: FSL road dist / Haversine = median 1.21x  (range 0.01x to 12.5x)\n'
             'Wide range because driver GPS is NOT at the previous job location -- driver is moving.')
    pdf.h2('Speed Varies With Route Type (NOT a Fixed Number)')
    pdf.body('Inferred from 110 measured trips (FSL road dist / travel time):')
    pdf.table(['Speed Range','% of Trips','Typical Scenario'],
              [['0-10 mph','17%','Very short trip, city traffic, driver mid-motion'],
               ['10-20 mph','13%','Urban intersections, lights'],
               ['20-30 mph','23%','Suburban roads -- most common AAA scenario'],
               ['30-45 mph','32%','Mixed suburban/county roads'],
               ['45-60 mph','13%','I-90, I-190, I-86 highway segments']],[28,22,140])
    pdf.body('Mean = 24.9 mph  |  Median = 26.9 mph\nOur 25 mph assumption matches the verified mean. Individual trips vary 10x.')
    pdf.h2('Critical: Where Driver Location Comes From')
    pdf.callout('FSL reads ServiceTerritoryMember.Latitude/Longitude.\n'
                'FSL mobile app syncs phone GPS -> STM.Lat/Lon automatically.\n'
                'Verified identical to ServiceResource.LastKnownLatitude/Longitude to 7 decimal places.',LGREEN,GREEN)
    pdf.fpill('Live GPS source','STM.Latitude / STM.Longitude',LGREEN,GREEN)
    pdf.fpill('Same mirrored field','SR.LastKnownLatitude / SR.LastKnownLongitude',LGREEN,GREEN); pdf.ln(15)
    pdf.fpill('Fallback (no GPS)','ServiceTerritory.Latitude/Longitude  (GARAGE)',LRED,RED)
    pdf.fpill('SA job location','ServiceAppointment.Latitude / .Longitude',LBLUE,BLUE); pdf.ln(15)
    pdf.fpill('FSL result dist','AR.FSL__EstimatedTravelDistanceFrom__c',LBLUE,BLUE)
    pdf.fpill('FSL result time','AR.FSL__EstimatedTravelTimeFrom__c',LBLUE,BLUE); pdf.ln(15)
    pdf.h2('Travel Score Formula (Closest Driver Policy)')
    x,y=10,pdf.get_y()
    pdf.set_fill_color(*LGRAY); pdf.set_draw_color(*NAVY); pdf.set_line_width(0.4)
    pdf.rect(x,y,190,30,'FD')
    for i,ln in enumerate(['FOR each candidate driver (already passed skill + availability filters):',
                            '   1. location = STM.Lat/Lon  IF GPS set  ELSE  Garage.Lat/Lon',
                            '   2. road_dist = road_routing_engine(location, SA.Lat/Lon)  # miles',
                            '   3. Travel_Score = road_dist                                # lower = better',
                            '   4. Total_Score  = 0 x ASAP + 100 x Travel_Score           # Closest Driver',
                            'ASSIGN driver with LOWEST Total_Score']):
        pdf.set_xy(x+3,y+2+i*4.7); pdf.set_font('Courier','B' if i in(0,5) else '',8)
        pdf.set_text_color(*NAVY if i in(0,5) else DGRAY); pdf.cell(184,4.7,ln)
    pdf.ln(34)
    pdf.callout('Haversine vs FSL: For typical 5-30 mile AAA trips, road distance is 1.2-1.5x aerial. '
                'A 10-mile Haversine call is actually 12-15 road miles. '
                'Our 25 mph Haversine estimate overstates speed slightly -- still accurate for UI recommendations.',LBLUE,NAVY)

# ==============================================================================
# PAGE 3 -- ASAP Score deep dive
# ==============================================================================
def page3(pdf):
    pdf.add_page()
    pdf.h1('Chapter 2 -- ASAP Score: Who Can Get There Soonest?')
    pdf.callout('ASAP is NOT about distance. It is about TIME. '
                '"Given everything this driver is doing right now, when is the EARLIEST they can START this job?" '
                'A free driver 8 miles away can beat a busy driver 2 miles away.',LPURP,PURPLE)
    pdf.h2('The ASAP Formula')
    x,y=10,pdf.get_y()
    pdf.set_fill_color(*LGRAY); pdf.set_draw_color(*PURPLE); pdf.set_line_width(0.5)
    pdf.rect(x,y,190,32,'FD')
    for i,ln in enumerate(['FOR each candidate driver:',
                            '   1. lastJobEnd = SchedEndTime of last job in driver queue',
                            '   2. road_time  = road_routing(STM.Lat/Lon, SA.Lat/Lon)  # minutes',
                            '   3. ASAP_time  = max(SA.EarliestStartTime, lastJobEnd + road_time)',
                            '   4. ASAP_Score = ASAP_time   (earlier = better)',
                            '   -- "Copy of Highest Priority" policy:',
                            '      Total = 1000 x ASAP_Score + 10 x Travel_Score',
                            '   -- Winner = driver with EARLIEST ASAP (can start soonest)',
                            'SchedStartTime on AssignedResource record = the computed ASAP value']):
        pdf.set_xy(x+3,y+2+i*3.3); bold=i in(0,8)
        pdf.set_font('Courier','B' if bold else '',7.8)
        pdf.set_text_color(*PURPLE if bold else DGRAY); pdf.cell(184,3.3,ln)
    pdf.ln(36)
    pdf.h2('Why ASAP Matters -- The Crossing-Driver Scenario')
    pdf.body('Two Fleet calls arrive 5 min apart in adjacent zones:\n\n'
             '  Driver A: 2 miles from Call-1  BUT  has 3 jobs queued (finishes in 70 min)\n'
             '  Driver B: 8 miles from Call-1  AND  completely free\n\n'
             'WITHOUT optimizer (Closest Driver only):\n'
             '  Driver A -> Call-1 (closest by distance)  |  Driver B -> Call-2\n'
             '  Driver A must cross town, passes Driver B on the road.\n\n'
             'WITH optimizer (ASAP scoring):\n'
             '  ASAP(A for Call-1) = 70 min queue + 3 min travel = 73 min\n'
             '  ASAP(B for Call-1) = 0 min queue + 10 min travel = 10 min\n'
             '  Optimizer picks B for Call-1  -->  no crossing, member gets help in 10 min vs 73 min.')
    pdf.callout('Observed from data: 0 of 662 AR records in 7 days had FSL__UpdatedByOptimization__c=true. '
                'Every assignment was initial Mulesoft dispatch (Closest Driver, ASAP=0). '
                'The optimizer ran zero corrections -- so suboptimal assignments were never fixed.',LRED,RED)
    pdf.h2('Real Timing Data (662 Fleet AR Records, Mar 2026)')
    pdf.table(['What we measured','Value','What it means'],
              [['SchedStartTime gap (median)','36.8 min','Assignment -> scheduled start: workload + travel'],
               ['SchedStartTime gap (mean)','60.8 min','Mean higher due to heavily-loaded drivers'],
               ['Travel-only portion (median)','~7 min','From FSL__EstimatedTravelTimeFrom__c'],
               ['Queue/workload (median)','~30 min','Driver finishing current job(s) before free']],[55,28,107])
    pdf.h2('Policy Weights: Closest Driver vs Optimizer')
    pdf.table(['Policy','ASAP Weight','Travel Weight','Ratio','Used When'],
              [['Closest Driver','0','100','Travel only','Mulesoft initial dispatch'],
               ['Copy of Highest Priority','1000','10','100:1 ASAP','FSL Optimizer (every 15 min)'],
               ['Highest Priority','9000','1000','9:1 ASAP','Not actively used'],
               ['Emergency','700','300','2.3:1 ASAP','Emergency override']],[52,28,28,22,60])

# ==============================================================================
# PAGE 4 -- Why drivers cross each other
# ==============================================================================
def page4(pdf):
    pdf.add_page()
    pdf.h1('Chapter 3 -- Why Drivers Cross Each Other: Root Cause Analysis')
    pdf.callout('Drivers crossing = Driver A sent to a call closer to Driver B, and vice versa. '
                'This means the algorithm received wrong driver positions or skipped better candidates. '
                'Four root causes below, ranked by frequency and impact.',LRED,RED)
    causes=[
        ('#1 -- GPS Missing (63% of WNY Fleet drivers have no STM coords)',RED,LRED,
         'When STM.Latitude/Longitude is null, FSL falls back to the GARAGE address '
         '(ServiceTerritory.Latitude/Longitude). Garage address is fixed and never moves.\n\n'
         'If Driver A is 20 miles east of their garage, FSL thinks they are AT the garage. '
         'FSL assigns them to calls near the garage -- even if Driver B is physically closer '
         'to that call and Driver A would have to drive right past Driver B.\n\n'
         'Fix: Require FSL mobile app login at shift start. '
         'GPS auto-syncs: Phone GPS -> SR.LastKnownLat/Lon -> STM.Lat/Lon.\n'
         'Verified: 14/38 WNY Fleet (37%) have STM coords. 24/38 (63%) cause this every shift.'),
        ('#2 -- Optimizer Ran Zero Corrections in 7 Days Observed',ORANGE,LORNG,
         'The optimizer (runs every 15 min, ASAP=1000 policy) is supposed to fix suboptimal '
         'initial assignments by recalculating who can arrive soonest.\n\n'
         'Data shows 0 of 662 AR records had FSL__UpdatedByOptimization__c=true in 7 days. '
         'Possible reasons: optimizer is off, or it IS running but GPS is wrong so '
         'it also calculates from wrong positions and finds no improvement.\n\n'
         'Fix: Confirm "Closest Drv. Optimization" job is active and running. '
         'But note: optimizer also needs GPS to work correctly -- fixing GPS is prerequisite.'),
        ('#3 -- Priority Matrix Sends Call to Non-Nearest Garage',GOLD,LGOLD,
         'The cascade (P2->P10) tries the home territory first. But if P2 has no available '
         'drivers (all busy, absent, or wrong shift), Mulesoft tries P3 -- which may be '
         'a different garage that is farther away.\n\n'
         'A driver from Garage B may be assigned to a call in Garage A territory '
         'even if a Garage A driver finishes their current job 3 minutes later. '
         'The cascade does not wait -- it assigns immediately to the next available.\n\n'
         'This is by design for reliability, but creates apparent crossing when garages are close.'),
        ('#4 -- Skill Requirement Forces Longer Assignment',GREEN,LGREEN,
         'Only drivers with the matching skill are candidates:\n'
         '  Tow Pick-Up/Drop-Off -> requires Tow skill (heavy truck)\n'
         '  Battery/Tire/Lockout -> Light service skill\n\n'
         'The nearest driver may be a light-service driver, but the call is a Tow. '
         'They are eliminated before scoring. The nearest TOW driver may be across town. '
         'This creates physical crossing between skill types -- unavoidable given equipment requirements.'),
    ]
    for title,fg,bg,detail in causes:
        x,yy=10,pdf.get_y()
        pdf.set_fill_color(*bg); pdf.set_draw_color(*fg); pdf.set_line_width(0.4)
        pdf.rect(x,yy,190,7,'FD')
        pdf.set_xy(x+3,yy+1); pdf.set_font('Helvetica','B',9.5); pdf.set_text_color(*fg)
        pdf.cell(184,5,title); pdf.ln(9); pdf.body(detail); pdf.ln(1)
    pdf.h2('GPS Status vs Crossing Risk')
    pdf.table(['Driver GPS Status','FSL Uses','Score Accuracy','Crossing Risk'],
              [['STM.Lat/Lon set (live GPS)','Live GPS position','High -- real road distance','Low'],
               ['No GPS (STM null)','Garage address (static)','Low -- distance from wrong point','HIGH'],
               ['GPS stale (>4 hrs)','Last known position','Medium -- hours-old position','Medium']],
              [55,42,50,43])

# ==============================================================================
# PAGE 5 -- Verified numbers + field reference
# ==============================================================================
def page5(pdf):
    pdf.add_page()
    pdf.h1('Chapter 4 -- All Verified Numbers & Field Reference')
    pdf.h2('Verified Numbers (Production Salesforce Org, March 2026)')
    pdf.table(['Metric','Value','Data Source'],
              [['AR records analyzed (Fleet, 7 days)','662','Bulk query Mar 11-18 2026'],
               ['FSL__UpdatedByOptimization=true','0 / 662  (0%)','AR.FSL__UpdatedByOptimization__c'],
               ['Mean road speed','24.9 mph','110 non-zero dist/time records'],
               ['Median road speed','26.9 mph','Same dataset'],
               ['Road dist / Haversine ratio (median)','1.21x','80 consecutive-trip pairs'],
               ['SchedStartTime gap (median)','36.8 min','662 AR records'],
               ['SchedStartTime gap (mean)','60.8 min','Same'],
               ['Max road distance observed','53.4 miles','AR.FSL__EstimatedTravelDistanceFrom__c'],
               ['Priority Matrix records','1,100','ERS_Territory_Priority_Matrix__c'],
               ['Max cascade retries','2','AAA_ERS_Services__mdt.Max_Retry__c'],
               ['Active optimizer job','1 (WNY Fleet only)','"Closest Drv. Optimization", every 15 min'],
               ['Optimizer policy weights','ASAP=1000, Travel=10','Copy of Highest Priority'],
               ['Initial dispatch policy weights','ASAP=0, Travel=100','Closest Driver'],
               ['Drivers with GPS (WNY Fleet)','14/38 (37%)','STM.Latitude not null, Mar 2026'],
               ['GPS source verified identical','STM == SR.LastKnownLat/Lon','3 drivers, 7 decimal places']],
              [88,42,60])
    pdf.h2('Salesforce Field Reference')
    pdf.table(['Object','Field','What It Is'],
              [['ServiceAppointment','Latitude / Longitude','Job location -- where member needs help'],
               ['ServiceAppointment','ERS_PTA__c','Promised arrival time (minutes)'],
               ['ServiceAppointment','WorkType.Name','Service type -> determines required skill'],
               ['ServiceTerritoryMember','Latitude / Longitude','Driver position (live GPS or garage fallback)'],
               ['ServiceResource','LastKnownLatitude/Longitude','Same as STM -- synced by FSL mobile app'],
               ['AssignedResource','FSL__EstimatedTravelDistanceFrom__c','FSL road distance (miles)'],
               ['AssignedResource','FSL__EstimatedTravelTimeFrom__c','FSL road travel time (minutes)'],
               ['AssignedResource','FSL__UpdatedByOptimization__c','True if optimizer reassigned this AR'],
               ['AssignedResource','SchedStartTime','ASAP-calculated scheduled arrival time'],
               ['ERS_Territory_Priority_Matrix__c','ERS_Spotted_Territory__c','Member zone (where the call is)'],
               ['ERS_Territory_Priority_Matrix__c','ERS_Priority__c','Cascade rank (P2=first, P10=last)'],
               ['AAA_ERS_Services__mdt','ERS_Auto_Schedule__c','Master dispatch on/off kill switch'],
               ['AAA_ERS_Services__mdt','Max_Retry__c','Cascade retry limit (=2)'],
               ['AAA_ERS_Services__mdt','Tow_Drop_off_Assign__c','Drop-off SAs always assigned (=true)']],
              [52,64,74])
    pdf.callout('FSL__Automator_Config__c does NOT exist in this org (verified via sf_describe). '
                'Scheduling policy used per SA is NOT logged -- FSL__Scheduling_Policy_Used__c = 0 records. '
                'Policy weights were reverse-engineered from FSL__Scheduling_Policy_Goal__c.',LRED,RED)

# ==============================================================================
# BUILD
# ==============================================================================
pdf=PDF(); pdf.alias_nb_pages(); pdf.set_auto_page_break(auto=True,margin=14)
page1(pdf); page2(pdf); page3(pdf); page4(pdf); page5(pdf)
out='/Users/abdennourlaaroubi/Library/CloudStorage/OneDrive-EnProIndustriesInc/AAA/Dev/FSL/FSL/apidev/FSLAPP/doc/AAA_ERS_Dispatch_Algorithm.pdf'
pdf.output(out); print(f'Saved: {out}')
