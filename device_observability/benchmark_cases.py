"""Synthetic, repeatable analysis cases; no data from the owner's computer."""
from copy import deepcopy
from .ai_evidence import snapshot


def cases():
    start=1793188800000
    view={'window':{'start_ms':start,'end_ms':start+3600000},'scope':'reported_components_only',
          'sample_count':360,'quality':{'reading_errors':0,'adapter_errors':0,'rejected_intervals':0},
          'series':[{'time_ms':start+i*60000,'cpu_w':40 if i<30 else 80,'gpu_w':20 if i<30 else 60,
                     'cpu_percent':10 if i<30 else 65,'gpu_percent':15 if i<30 else 85} for i in range(60)],
          'components':[{'id':name,'energy_kwh':energy,'cost_brl':energy*1.2,'covered_seconds':3600,
                         'coverage_percent':100,'priced_seconds':3600,'average_w':energy*1000,'peak_w':peak,
                         'energy_domain':'cpu_package' if name=='cpu' else 'discrete_gpu'}
                        for name,energy,peak in [('cpu',.06,80),('gpu',.04,60)]]}
    for name,question,tariffs in [
        ('monthly','Qual seria o custo mensal de energia considerando 18 horas por dia?',[{'effective_ms':start,'price':'1.20'}]),
        ('comparison','Compare a potência da CPU entre as metades do período.',[]),
        ('coverage','Quanto destes dados mede o consumo total do gabinete?',[]),
        ('missing_tariff','Qual seria meu custo mensal de energia considerando 18 horas por dia?',[]),
    ]:
        case_view=deepcopy(view)
        if not tariffs:
            for component in case_view['components']:
                component.update(cost_brl=None,priced_seconds=0)
        yield name,question,snapshot(case_view,tariffs,projection={'hours_per_day':18,'days':30,'hours_origin':'question'})
