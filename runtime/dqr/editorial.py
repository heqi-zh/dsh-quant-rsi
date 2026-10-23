"""Reader-facing copy rules shared by model submissions and report rendering."""
import re

CONTRAST = re.compile(r'不是|并非|而非|而是|不代表|不等于|不意味着')


def validate_copy(text):
    match=CONTRAST.search(text)
    if match:
        raise ValueError('请直接陈述数据、含义和适用范围，删除对照否定句式：'+match.group())
    return text


def validate_fund_percentages(analysis, picks, categories=None):
    """Check quoted percentages against that fund's own observed input fields."""
    fields=('return_20','return_60','daily_volatility_20','downside_volatility','drawdown_60','ema_gap')
    lines=analysis.splitlines()
    if len(lines)!=len(picks):raise ValueError('one reader judgment per fund required')
    for line,pick in zip(lines,picks):
        for match in re.finditer(r'(?<![\d.])([+-]?\d+(?:\.\d+)?)[%％]',line):
            token=match[1];places=len(token.partition('.')[2]);quoted=float(token)
            values=[100*pick['values'][key] for key in fields if pick['values'].get(key) is not None]
            if '中位' in line:
                median=(categories or {}).get(pick.get('group'),{}).get('median_return_20')
                if median is not None:values.append(100*median)
            if token[0] not in '+-':values=[abs(v) for v in values]
            if not any(abs(quoted-float(f'{value:.{places}f}'))<1e-9 for value in values):
                raise ValueError(f'{pick["code"]} 的百分比 {token}% 缺少该基金的数据依据；请从其收益、波动、均线差或距高点数值中准确引用。')
    return analysis


def validate_weekly_prose(analysis, proposals):
    """Keep implementation expressions in their dedicated proposal fields."""
    text='\n'.join([analysis]+[p.get('reason','') for p in proposals])
    validate_copy(text)
    if re.search(r'\d+\.\d{3,}',text):
        raise ValueError('周报正文和建议理由最多保留两位小数；收益、波动和替换比例请写成百分比，原始精度放入 evidence_json。')
    if re.search(r'(?<![a-zA-Z0-9_])[a-zA-Z]+_[a-zA-Z0-9_]+(?![a-zA-Z0-9_])',analysis):
        raise ValueError('周报正文请用中文因子名解释，变量和函数表达式只写在 proposals_json 的 expression 字段。')
    return analysis
