"""Auditable theme discovery from the public fund directory."""
import re

def share_family(name):
    name=name.replace("人民币", "").replace("（", "(").replace("）", ")")
    name=re.sub(r"\((?:QDII(?:-LOF)?|LOF)\)", "", name, flags=re.I)
    return re.sub(r"[ABCDEFHIY](?:类)?$", "", name)

def discover(catalog, definitions, baseline=()):
    families={}; excluded=[]
    for row in catalog:
        code,_,name,category,*_=row
        if any(x in name for x in ['美元','港币','后端','人民币对冲']): continue
        if 'ETF' in name.upper() and '联接' not in name: continue
        if any(x in category.upper() for x in ['货币','FOF','REIT','债券']) or 'REIT' in name.upper() or '债' in name: continue
        if re.search('持有|定开|定期|封闭|一年|两年|三年|六个月',name): continue
        # Avoid company-name matches such as 农银行业领先 / 中信证券资管.
        subject=re.sub(r'^(农银汇理|农银|中信证券|国泰君安证券|国泰海通证券|中金公司)', '', name)
        themes=[t['id'] for t in definitions['themes'] if re.search(t['pattern'],subject,re.I)]
        if not themes: continue
        family=share_family(name)
        item={'code':code,'name':name,'category':category,'share_family':family,'themes':themes,
              'theme_basis':definitions['tag_basis'],'market':'overseas' if ('海外' in category or 'QDII' in category or 'QDII' in name or '纳斯达克' in name or '标普' in name or '道琼斯' in name) else 'domestic',
              'group':'gold' if '黄金' in name else 'overseas' if ('海外' in category or 'QDII' in category or 'QDII' in name or '纳斯达克' in name or '标普' in name or '道琼斯' in name) else 'index' if '指数' in category else 'stock' if category=='股票型' else 'mixed'}
        families.setdefault(family,[]).append(item)
    selected=[]
    for shares in families.values():
        shares.sort(key=lambda x:(0 if re.search(r'A(?:类)?(?:人民币)?$',x['name']) else 1,x['code']))
        item=shares[0];item['alternative_shares']=[s['code'] for s in shares[1:]];selected.append(item)
    bycode={f['code']:f for f in selected}
    for f in baseline:
        if f['code'] not in bycode and share_family(f['name']) not in families:
            bycode[f['code']]={**f,'share_family':share_family(f['name']),'themes':[],'theme_basis':'基础基金池','market':'domestic','alternative_shares':[]}
    funds=sorted(bycode.values(),key=lambda f:f['code'])
    return {'schema':'dqr.universe.v2','funds':funds,'themes':definitions['themes'],
            'coverage':{t['id']:{'name':t['name'],'discovered':sum(t['id'] in f['themes'] for f in funds)} for t in definitions['themes']},
            'rules':'All name-matched share families in supported categories, A preferred; retain baseline families. Current directory sampling; history availability checked separately.'}
