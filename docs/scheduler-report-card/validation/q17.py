exec(open(__file__.rsplit('/',1)[0]+'/h.py').read())
from collections import Counter
sas=load('sa_GKAQ_0928')
woli=[s['ParentRecordId'] for s in sas]
il=",".join(f"'{x}'" for x in woli)
sr=sf_query_all(f"SELECT RelatedRecordId, Skill.MasterLabel, SkillLevel FROM SkillRequirement WHERE RelatedRecordId IN ({il})")
print('WOLI skill reqs', len(sr), Counter(x['Skill']['MasterLabel'] for x in sr))
save('woliskill_GKAQ_0928', sr)
print('SkillRequirement total RelatedRecord prefixes', sf_query_all("SELECT COUNT(Id) n FROM SkillRequirement WHERE CreatedDate>=2026-09-28T00:00:00Z"))
