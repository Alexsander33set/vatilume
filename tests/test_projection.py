import unittest

from device_observability.ai_evidence import EvidenceSession, snapshot
from device_observability.projection import asks_monthly_projection, monthly_projection, projection_scenario
from test_ai_service import frozen_fixture


QUESTION = 'Com os dados que temos, qual seria o meu custo mensal de energia?'


def change_frozen(change):
    frozen = frozen_fixture()
    change(frozen)
    # Construct another authenticated snapshot through the same application boundary.
    return snapshot(frozen, frozen['tariffs'], frozen['experiments'], frozen['projection'])


class ProjectionTests(unittest.TestCase):
    def test_monthly_cost_has_explicit_hours_units_and_does_not_claim_whole_pc(self):
        result = monthly_projection(frozen_fixture())
        self.assertAlmostEqual(result['projected_kwh'], 57.6)
        self.assertAlmostEqual(result['projected_cost_brl'], 69.12)
        self.assertEqual(result['hours_per_day'], 24)
        self.assertFalse(result['whole_pc_measured'])
        self.assertEqual(result['missing_components'], [])
        self.assertEqual(result['window_hours'], 1)

    def test_gaps_are_not_interpreted_as_off_time_and_component_durations_are_separate(self):
        def gaps(frozen):
            frozen['components'][1].update(covered_seconds=1800, coverage_percent=50)
            frozen['projection'] = projection_scenario('', 8)
        result = monthly_projection(change_frozen(gaps))
        # 50 W CPU + 60 W GPU, for 240 h. Not 50 + 30 W; not 24 hours/day.
        self.assertAlmostEqual(result['projected_kwh'], 26.4)
        self.assertAlmostEqual(result['projected_cost_brl'], 31.68)
        self.assertEqual(result['components'][1]['observed_hours'], .5)

    def test_tariff_is_the_latest_effective_at_base_end_not_historic_cost_or_future_price(self):
        def tariffs(frozen):
            start = frozen['window']['start_ms']
            frozen['tariffs'] = [{'effective_ms':start+3_600_001,'price':'9'}, {'effective_ms':start+1_800_000,'price':'2'}, {'effective_ms':start,'price':'1'}]
            for component in frozen['components']:
                component['cost_brl'] = 999
        result = monthly_projection(change_frozen(tariffs))
        self.assertEqual(result['tariff_brl_per_kwh'], 2)
        self.assertAlmostEqual(result['projected_cost_brl'], 115.2)

    def test_missing_or_future_tariff_keeps_kwh_and_explains_missing_brl(self):
        for tariffs in ([], [{'effective_ms':frozen_fixture()['window']['end_ms']+1, 'price':'1.2'}]):
            frozen = change_frozen(lambda f: f.update(tariffs=tariffs))
            session = EvidenceSession(frozen, QUESTION)
            result = session.validate({'answer_id':'monthly_projection','fact_ids':['scope'],'recommendation_ids':[], 'answer_status':'evidence_found'})
            answer = result['answer']
            self.assertEqual(answer['values']['status'], 'needs_tariff')
            self.assertIsNone(answer['values']['projected_cost_brl'])
            self.assertIn('57,60 kWh', answer['text'])
            self.assertIn('configure o valor do kWh', answer['text'])
            self.assertEqual(result['answer_status'], 'insufficient')

    def test_missing_component_and_no_valid_readings_are_not_zero_consumption(self):
        def missing_gpu(frozen):
            frozen['components'][1].update(energy_kwh=None, covered_seconds=0, coverage_percent=0)
        frozen = change_frozen(missing_gpu)
        result = monthly_projection(frozen)
        self.assertEqual(result['missing_components'], ['gpu'])
        self.assertAlmostEqual(result['projected_cost_brl'], 43.2)
        answer = EvidenceSession(frozen, QUESTION).facts['monthly_projection']['text']
        self.assertIn('CPU projeta', answer)
        self.assertNotIn('CPU e GPU', answer)
        def missing_both(frozen):
            for component in frozen['components']:
                component.update(energy_kwh=None, covered_seconds=0, coverage_percent=0)
        result = monthly_projection(change_frozen(missing_both))
        self.assertEqual(result['status'], 'no_data')
        self.assertIsNone(result['projected_kwh'])
        self.assertIsNone(result['projected_cost_brl'])

    def test_valid_zero_energy_is_distinct_from_missing_readings(self):
        frozen = change_frozen(lambda f: [c.update(energy_kwh=0) for c in f['components']])
        self.assertEqual(monthly_projection(frozen)['projected_cost_brl'], 0)
        self.assertEqual(monthly_projection(frozen)['status'], 'projected')

    def test_daily_hours_in_question_take_precedence_and_invalid_or_ambiguous_values_are_rejected(self):
        for text in ('Usando 8 horas por dia', '8h/dia', '8 HORAS AO DIA'):
            self.assertEqual(projection_scenario(text, 24)['hours_per_day'], 8)
            self.assertEqual(projection_scenario(text, 24)['hours_origin'], 'question')
        self.assertEqual(projection_scenario('Usando 7,5 h por dia')['hours_per_day'], 7.5)
        fractional = change_frozen(lambda f: f.update(projection=projection_scenario('Usando 7,25 h por dia')))
        self.assertIn('7,25 h/dia', EvidenceSession(fractional, QUESTION).facts['monthly_projection']['text'])
        for value in (0, -1, 25, True, float('nan'), float('inf'), '8'):
            with self.assertRaises(ValueError): projection_scenario('', value)
        for question in ('25 horas por dia', '-8h/dia', '0h/dia', '8h/dia ou 24h/dia'):
            with self.assertRaises(ValueError): projection_scenario(question)

    def test_actual_monthly_question_gets_projection_but_historical_questions_do_not(self):
        for question in (QUESTION, 'Quanto gastaria por mês?', 'Qual o consumo mensal?', 'Quanto pagaria em um mês?'):
            self.assertTrue(asks_monthly_projection(question), question)
        for question in ('Quanto gastei no mês passado?', 'Qual o custo neste mês?', 'Qual a temperatura da CPU?'):
            self.assertFalse(asks_monthly_projection(question), question)

    def test_monthly_answer_is_mandatory_and_references_the_source_calculation(self):
        session = EvidenceSession(frozen_fixture(), QUESTION)
        self.assertEqual(session.output_schema()['properties']['answer_id']['enum'], ['monthly_projection'])
        response = {'answer_id':'scope','fact_ids':['cost_cpu','cost_gpu'],'recommendation_ids':[], 'answer_status':'evidence_found'}
        with self.assertRaisesRegex(ValueError, 'projeção mensal'): session.validate(response)
        response['answer_id'] = 'monthly_projection'
        report = session.validate(response)
        self.assertEqual(report['answer_status'], 'conditional_projection')
        self.assertEqual(report['claims'][0]['id'], 'monthly_projection')
        self.assertIn('R$ 69,12', report['answer']['text'])
        self.assertEqual({report['evidence'][key]['tool'] for key in report['answer']['evidence_ids']}, {'project_monthly_cost','calculate_energy_cost'})
        self.assertIn('menos de um dia', ' '.join(report['answer']['caveats']))

    def test_short_actual_history_is_warned_even_if_selected_window_spans_many_days(self):
        frozen = change_frozen(lambda f: f['window'].update(end_ms=f['window']['start_ms'] + 7*86_400_000))
        session = EvidenceSession(frozen, QUESTION)
        report = session.validate({'answer_id':'monthly_projection','fact_ids':['scope'], 'recommendation_ids':[], 'answer_status':'evidence_found'})
        self.assertEqual(report['answer']['values']['window_hours'], 168)
        self.assertIn('leituras válidas usadas cobrem menos de um dia', ' '.join(report['answer']['caveats']))


if __name__ == '__main__': unittest.main()
