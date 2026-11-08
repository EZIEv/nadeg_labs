from decimal import Decimal as D, localcontext
from itertools import product
import json
import random
import time
from zipfile import ZipFile
from pathlib import Path

from fastapi.testclient import TestClient
import httpx
import pytest

from nadeg.engine import calculate, optimize, ModelError
from nadeg.models import Problem
from nadeg.boolean import DecisionDiagram, StructureLimit
from nadeg.main import app
from nadeg.lab3 import Analysis, Review
from nadeg import lab3_ai


def problem(expression, rates=('0.1','0.2','0.3')):
    return Problem(task=1,time=1,rate_scale='1',expression=expression,elements=[{'id':chr(65+i),'rate':rate} for i,rate in enumerate(rates)])


@pytest.mark.parametrize('expression,probability', [('A | B','0.98'), ('(A & B) | (A & C)','0.846'),
    ('A & A','0.9'), ('A | (A & B)','0.9'), ('(A | B) & (A | C)','0.956'), ('(A & B) | (B & C)','0.776')])
def test_shared_physical_elements(expression, probability):
    r=calculate(problem(expression))
    assert D(r['probability'])==D(probability)
    assert D(r['mass'])==3  # Table entries counted once, including unused entries.


def test_tiny_failure_and_boundaries():
    p=problem('A | B',('1e-30','1e-30'))
    assert D(calculate(p)['failure_probability'])==D('1e-60')
    assert D(calculate(problem('A & B',('0','1')))['probability'])==0
    assert D(calculate(problem('A | B',('0','1')))['probability'])==1


def test_random_boolean_trees_against_exhaustive_physical_states():
    rng=random.Random(28)
    with localcontext() as ctx:
        ctx.prec=60
        for _ in range(70):
            def tree(depth):
                if depth==0 or rng.random()<.25:return rng.choice('ABCD')
                return (rng.choice(['and','or']),tree(depth-1),tree(depth-1))
            t=tree(4)
            def expr(n):return n if isinstance(n,str) else f'({expr(n[1])} {"&" if n[0]=="and" else "|"} {expr(n[2])})'
            def truth(n,values):return values[n] if isinstance(n,str) else (truth(n[1],values) and truth(n[2],values) if n[0]=='and' else truth(n[1],values) or truth(n[2],values))
            p=problem(expr(t),('0.1','0.2','0.3','0.4')); expected=D(0)
            for state in product([False,True],repeat=4):
                if truth(t,dict(zip('ABCD',state))):
                    weight=D(1)
                    for i,works in enumerate(state):weight*=1-D(p.elements[i].rate) if works else D(p.elements[i].rate)
                    expected+=weight
            assert D(calculate(p)['probability'])==expected


def test_limits_and_task_separation():
    with pytest.raises(StructureLimit):DecisionDiagram('A',['A'],max_nodes=2)
    with pytest.raises(ModelError):optimize(problem('A & B'))
    p=problem('A | B');p.task=2
    with pytest.raises(ModelError):calculate(p)


def test_common_group_reserve_is_shared():
    p=problem('A | (A & B)');p.elements[0].reserves=1
    r=calculate(p)
    assert D(r['probability'])==D('.99')
    assert D(r['mass'])==4


def test_readable_field_errors_and_bad_json():
    with TestClient(app) as c:
        data=problem('A').model_dump(mode='json');data['elements'][0]['rate']='-1'
        r=c.post('/api/lab1/validate',json=data)
        issue=r.json()['errors'][0]
        assert issue['path']==['elements',0,'rate'] and 'A' in issue['label']
        assert 'Input should' not in r.text and 'не меньше' in issue['message']
        assert c.post('/api/analyze',content='{broken',headers={'Content-Type':'application/json'}).json()['errors'][0]['message']=='Запрос повреждён или не является JSON'


def test_bad_period_points_to_changed_field():
    with TestClient(app) as c:
        data={'title':'Регламент','resource':'800','flight_time':1,'flights_per_day':4,'periods':[{'id':'P1','interval':50},{'id':'P2','interval':75},{'id':'P3','interval':200}]}
        issue=c.post('/api/lab2/validate',json=data).json()['errors'][0]
        assert issue['path']==['periods',1,'interval']
        assert 'Value error' not in issue['message']


def analysis():
    return Analysis(title='Модель бака',materials=[{'id':'S1','name':'Модель','text':'При расходе топлива газовый объём увеличивается.'}],rows=[{'id':'R4','condition':'Выработка топлива при перекрытой вентиляции'}])


def review(contradiction=False):
    return Review.model_validate({'summary':'Проверка','missing_information':[], 'suggestions':[{
      'row_id':'R4','field':'condition','status':'supported','comment': 'Разрежение при выработке невозможно.' if contradiction else 'Разрежение возможно при указанных допущениях.',
      'replacement':'При расходе без компенсации давление газа уменьшается.',
      'evidence':[{'source_id':'S1','quote':'При расходе топлива газовый объём увеличивается.'}],
      'basis':{'kind':'physical_principle','explanation':'pV=mRT; при постоянных m и T рост V уменьшает p.',
               'assumptions':['Идеальный газ','Масса газа и температура постоянны'],'check':'Сравнить p1V1=p2V2 и указать границы модели.'}}]})


@pytest.mark.parametrize('verdict,allowed', [('consistent',True),('uncertain',False),('contradictory',False),('unsupported',False)])
def test_quote_never_overrides_grounding_verdict(monkeypatch,verdict,allowed):
    settings=lab3_ai.Settings.load()
    monkeypatch.setattr(lab3_ai,'check_grounding',lambda *args:{0:{'verdict':verdict,'reason':'Согласованность проверена отдельно.'}})
    result=lab3_ai.verified_response(review(contradiction=True),analysis(),settings,time.monotonic()+120)
    assert result['suggestions'][0]['apply_allowed'] is allowed
    assert result['suggestions'][0]['evidence']  # A quote is present, still not proof.


def test_ventilation_counterexample_is_sent_for_independent_check(monkeypatch):
    original=httpx.Client
    def handler(req):
        payload=json.loads(req.content)
        assert 'pV=mRT' in payload['messages'][0]['content']
        assert 'Разрежение при выработке невозможно' in payload['messages'][1]['content'][0]['text']
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps({'assessments':[{'index':0,'verdict':'contradictory','reason':'Комментарий отрицает механизм, который используется в редакции.'}]})},'finish_reason':'stop'}]})
    monkeypatch.setattr(lab3_ai.httpx,'Client',lambda **kwargs:original(transport=httpx.MockTransport(handler),**kwargs))
    result=lab3_ai.check_grounding(review(True),analysis(),lab3_ai.Settings.load())
    assert result[0]['verdict']=='contradictory'


def test_failed_critique_preserves_review_but_blocks_application(monkeypatch):
    def fail(*args):raise lab3_ai.ReviewError('Недоступно')
    monkeypatch.setattr(lab3_ai,'check_grounding',fail)
    result=lab3_ai.verified_response(review(),analysis(),lab3_ai.Settings.load(),time.monotonic()+120)
    assert len(result['suggestions'])==1
    assert result['suggestions'][0]['apply_allowed'] is False


def test_source_basis_without_quote_stays_blocked(monkeypatch):
    r=review();r.suggestions[0].basis.kind='source';r.suggestions[0].evidence=[]
    monkeypatch.setattr(lab3_ai,'check_grounding',lambda *args:{0:{'verdict':'consistent','reason':'ok'}})
    assert lab3_ai.verified_response(r,analysis(),lab3_ai.Settings.load(),time.monotonic()+120)['suggestions'][0]['verification']['verdict']=='unsupported'


@pytest.mark.parametrize('assessments', [[], [{'index':1,'verdict':'consistent','reason':'Проверено'}], [{'index':0,'verdict':'consistent','reason':'Проверено'}]*2])
def test_grounding_requires_complete_unique_indices(monkeypatch,assessments):
    monkeypatch.setattr(lab3_ai,'request_content',lambda *args:json.dumps({'assessments':assessments}))
    with pytest.raises(lab3_ai.ReviewError):lab3_ai.check_grounding(review(),analysis(),lab3_ai.Settings.load())


def test_physical_basis_without_conditions_cannot_be_applied(monkeypatch):
    r=review();r.suggestions[0].basis.assumptions=[]
    monkeypatch.setattr(lab3_ai,'check_grounding',lambda *args:{0:{'verdict':'consistent','reason':'Согласовано'}})
    result=lab3_ai.verified_response(r,analysis(),lab3_ai.Settings.load(),time.monotonic()+120)
    assert not result['suggestions'][0]['apply_allowed']


def test_input_domain_checked_before_structure():
    data=problem('A',('2',)).model_dump(mode='json')
    with TestClient(app) as c:
        r=c.post('/api/lab1/validate',json=data)
        assert r.status_code==422
        assert r.json()['errors'][0]['path']==['elements',0,'rate']
