exec(open(__file__.rsplit('/',1)[0]+'/h.py').read())
for tag in ['GKAQ_0928','3KAA_0831']:
    ids=sorted(set(a['AssetId'] for a in load(f'ah_{tag}')))
    il=",".join(f"'{x}'" for x in ids)
    r=sf_query_all(f"SELECT Id, Name, ERS_Truck_Capabilities__c FROM Asset WHERE Id IN ({il})")
    save(f'assets_{tag}', r); print(tag, len(r), [(x['Name'][:12], x['ERS_Truck_Capabilities__c']) for x in r[:4]])
