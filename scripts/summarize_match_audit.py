#!/usr/bin/env python3
import csv,json,statistics,sys
from pathlib import Path
p=Path(sys.argv[1]);rows=list(csv.DictReader(p.open()))
fields=['queries','short_knn','ratio_reject','ratio_pass','parallax','left_depth','right_depth','left_reprojection','right_reprojection','nonfinite','tiny_depth','accepted','unique_right']
for r in rows:
 for k in ['frame','filtered',*fields]:r[k]=int(r[k])
 assert r['queries']==r['short_knn']+r['ratio_reject']+r['ratio_pass'],r
 assert r['ratio_pass']==sum(r[k] for k in ['parallax','left_depth','right_depth','left_reprojection','right_reprojection','nonfinite','tiny_depth','accepted']),r

def aggregate(rr):
 if not rr:return None
 return {'frames':len(rr),'first_frame':min(r['frame'] for r in rr),'last_frame':max(r['frame'] for r in rr),**{k:sum(r[k] for r in rr) for k in fields},'accepted_mean':statistics.mean(r['accepted'] for r in rr),'accepted_median':statistics.median(r['accepted'] for r in rr),'unique_right_median':statistics.median(r['unique_right'] for r in rr),'frames_accepted_lt15':sum(r['accepted']<15 for r in rr),'frames_accepted_ge30':sum(r['accepted']>=30 for r in rr),'frames_accepted_ge50':sum(r['accepted']>=50 for r in rr)}
result={}
for filtered in [0,1]:
 for ratio in ['0.7','0.8','0.9','0.95']:
  for name,predicate in [('all',lambda r:True),('first128',lambda r:r['frame']<128),('after201',lambda r:r['frame']>=201)]:
   result[f'front_filtered{filtered}_ratio{ratio}_{name}']=aggregate([r for r in rows if r['filtered']==filtered and r['pair']=='01' and r['ratio']==ratio and predicate(r)])
for filtered in [0,1]:
 for pair in ['01','02','03','12','13','23']:
  result[f'pair{pair}_filtered{filtered}_first128']=aggregate([r for r in rows if r['filtered']==filtered and r['pair']==pair and r['ratio']=='0.8' and r['frame']<128])
print(json.dumps(result,indent=2))
