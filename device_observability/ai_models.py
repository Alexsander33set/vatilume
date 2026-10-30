"""Explicitly supported Responses models; no discovery or automatic fallback."""
DEFAULT_MODEL = 'gpt-5.4-mini-2026-03-17'
MODELS = {
    DEFAULT_MODEL: {'id': DEFAULT_MODEL, 'label': 'GPT-5.4 mini', 'input': .75, 'output': 4.5, 'reserve_input': .75},
    'gpt-6-luna': {'id': 'gpt-6-luna', 'label': 'GPT-6 Luna', 'input': .10, 'output': .50, 'reserve_input': .125},
    'gpt-6.1-terra': {'id': 'gpt-6.1-terra', 'label': 'GPT-6.1 Terra', 'input': 1., 'output': 5., 'reserve_input': 1.25},
}
PRICE_DATE = '2026-10-30'


def model_info(identity):
    if identity not in MODELS:
        raise ValueError('Modelo não suportado. Escolha um dos modelos disponíveis em Configurações.')
    return MODELS[identity]
