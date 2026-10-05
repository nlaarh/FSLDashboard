exec(open(__file__.rsplit('/',1)[0]+'/h.py').read())
import sys
TER, DAY, S, E, HS, HE = sys.argv[1:7]
tag=f"{TER[-4:]}_{DAY}"
ar=load(f'ar_{tag}')
m=sf_query_all(f"""SELECT ServiceResourceId, ServiceResource.Name, ServiceResource.ERS_Driver_Type__c, ServiceResource.IsActive, TerritoryType, EffectiveStartDate, EffectiveEndDate
  FROM ServiceTerritoryMember WHERE ServiceTerritoryId='{TER}' AND EffectiveStartDate<{E} AND (EffectiveEndDate=null OR EffectiveEndDate>{S})""")
save(f'mem_{tag}',m)
drv=sorted(set([x['ServiceResourceId'] for x in m if x['ServiceResource']['ERS_Driver_Type__c'] in ('Fleet Driver','On-Platform Contractor Driver')]+[a['ServiceResourceId'] for a in ar if a['ServiceResource']['ERS_Driver_Type__c'] in ('Fleet Driver','On-Platform Contractor Driver')]))
print('members active', len(m), 'driver ids', len(drv))
il=",".join(f"'{x}'" for x in drv)
# truck login: AssetHistory ERS_Driver__c in window (with 14h lookback)
ah=sf_query_all(f"""SELECT AssetId, Asset.Name, Field, OldValue, NewValue, CreatedDate FROM AssetHistory WHERE Field='ERS_Driver__c' AND CreatedDate>={HS} AND CreatedDate<{HE}""")
ah=[a for a in ah if (a['NewValue'] in drv) or (a['OldValue'] in drv)]
print('assethist rows for drivers', len(ah)); save(f'ah_{tag}',ah)
gd=sorted(set([a['NewValue'] for a in ah if a['NewValue'] in drv]+[a['OldValue'] for a in ah if a['OldValue'] in drv]+[a['ServiceResourceId'] for a in ar if a['ServiceResourceId'] in drv]))
print('gps drivers (logged-in or assigned)', len(gd)); il=",".join(f"'{x}'" for x in gd)
gn=sf_query(f"SELECT COUNT() FROM ServiceResourceHistory WHERE Field IN ('LastKnownLatitude','LastKnownLongitude') AND ServiceResourceId IN ({il}) AND CreatedDate>={HS} AND CreatedDate<{HE}")['totalSize']
print('gps rows', gn)
gps=sf_query_all(f"SELECT ServiceResourceId, Field, NewValue, CreatedDate FROM ServiceResourceHistory WHERE Field IN ('LastKnownLatitude','LastKnownLongitude') AND ServiceResourceId IN ({il}) AND CreatedDate>={HS} AND CreatedDate<{HE}")
print('gps pulled', len(gps)); save(f'gps_{tag}',gps)
ra=sf_query_all(f"SELECT ResourceId, Type, Start, End FROM ResourceAbsence WHERE ResourceId IN ({il}) AND Start<{E} AND End>{S}")
print('absences', len(ra)); save(f'ra_{tag}',ra)
sh=sf_query_all(f"SELECT ServiceResourceId, StartTime, EndTime, Status FROM Shift WHERE ServiceResourceId IN ({il}) AND StartTime<{E} AND EndTime>{S}")
print('shifts', len(sh))
sk=sf_query_all(f"SELECT ServiceResourceId, Skill.MasterLabel FROM ServiceResourceSkill WHERE ServiceResourceId IN ({il})")
save(f'sk_{tag}',sk); print('skills', len(sk))
