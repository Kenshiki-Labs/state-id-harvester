"""Descriptive full-raster separation; no fitting, pixel sampling or boundary edits."""
import numpy as np
from evidence import require

def stats(values):
    if not values.size:
        return dict(count=0,mean=None,quantiles=None)
    return dict(count=int(values.size),mean=float(values.mean(dtype=np.float64)),
                quantiles=dict(zip(['p05','p25','median','p75','p95'],
                                   np.quantile(values,[.05,.25,.5,.75,.95]).tolist())))

def measure(scores, labels, regions, inside, sm):
    require(inside.ndim == labels.ndim == regions.ndim == 2 and regions.dtype == np.uint8, 'Expected 2D uint8 regions')
    require([b['index'] for b in sm['bands']] == list(range(len(sm['bands']))) and all(isinstance(b['name'],str) and b['name'] for b in sm['bands']), 'Invalid band identity')
    require(len({b['taxonomy_id'] for b in sm['bands']}) == len(sm['bands']), 'Duplicate taxonomy IDs')
    require(inside.dtype == np.bool_ and inside.any() and (~inside).any(), 'Both inside and outside must be present')
    require(labels.shape == regions.shape == inside.shape, 'Raster shape mismatch')
    require(scores.dtype == np.float32 and scores.shape == (len(sm['bands']), *inside.shape), 'Score shape or dtype mismatch')
    require(labels.dtype == np.uint8 and int(labels.max()) < len(sm['bands']), 'Invalid label indices')
    require(set(np.unique(regions)) <= {0,1,2,3}, 'Invalid working region labels')
    for y in range(inside.shape[0]):
        require(np.isfinite(scores[:,y,:]).all(), 'Nonfinite scores')
        require(np.array_equal(scores[:,y,:].argmax(axis=0),labels[y]), 'Scores and winner labels disagree')
    masks={'working_inside':inside,'working_outside':~inside,'clear_interior':regions==1,
           'surroundings':regions==0,'edge_unresolved':regions==2,'shadow':regions==3}
    counts={k:np.bincount(labels[v],minlength=len(sm['bands'])) for k,v in masks.items()}
    target=int(counts['working_inside'].argmax());other=int(counts['working_outside'].argmax())
    contrast=scores[target]-scores[other]
    require(np.isfinite(contrast).all(), 'Nonfinite score contrast')
    target_map=labels==target
    tp=int((target_map&inside).sum());fp=int((target_map&~inside).sum());fn=int((~target_map&inside).sum())
    summary={}
    for name,mask in masks.items():
        c=counts[name];n=int(c.sum());top=np.argsort(-c)[:5] if n else []
        summary[name]=dict(pixels=n,dominant_index=int(c.argmax()) if n else None,dominant_fraction=float(c.max()/n) if n else None,
                           target_winner_fraction=float(c[target]/n) if n else None,
                           contrast=stats(contrast[mask]),target_beats_exterior_fraction=float((contrast[mask]>0).mean()) if n else None,
                           top_patterns=[dict(index=int(i),name=sm['bands'][i]['name'],fraction=float(c[i]/n)) for i in top])
    pi=counts['working_inside']/inside.sum();po=counts['working_outside']/(~inside).sum()
    # All 4-connected pixel adjacencies crossing the existing mask; no sampling.
    changes=[];winner_changes=[]
    for dimension in [0,1]:
        first=[slice(None),slice(None)];second=first.copy()
        first[dimension]=slice(None,-1);second[dimension]=slice(1,None)
        f,s=tuple(first),tuple(second);cross=inside[f]!=inside[s]
        orientation=np.where(inside[f][cross],1,-1)
        changes.append((contrast[f][cross].astype(np.float64)-contrast[s][cross].astype(np.float64))*orientation)
        winner_changes.append(labels[f][cross]!=labels[s][cross])
    delta=np.concatenate(changes)
    report=dict(schema='license_surface_separation_v1',source_sha256=sm['source_sha256'],
                distinct_dominant_patterns=target!=other,
                target_pattern=sm['bands'][target],exterior_pattern=sm['bands'][other],
                selection='regional_argmax_frequency',regions=summary,
                distribution_total_variation=float(np.abs(pi-po).sum()/2),
                target_map=dict(inside_coverage=tp/(tp+fn),precision_inside=tp/(tp+fp),iou=tp/(tp+fp+fn)),
                boundary_adjacent_pairs=dict(contrast_inside_minus_outside=stats(delta),
                    fraction_inward_increase=float((delta>0).mean()),
                    fraction_winner_changes=float(np.concatenate(winner_changes).mean())))
    return report, contrast, target_map
