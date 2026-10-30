"""Curated explanations; never return provider payloads, credentials or raw logs."""
def provider_error(status, code=None):
    if status==401:
        return 'A chave foi recusada pela OpenAI. Confira ou substitua a credencial em Configurações → IA.'
    if status==403:
        return 'A conta não tem permissão para esta operação. Confira o projeto e as permissões da chave na OpenAI.'
    if status==404:
        return 'O modelo não está disponível para esta chave. Escolha outro modelo em Configurações → IA.'
    if status==429 and code in ('insufficient_quota','billing_hard_limit_reached','billing_not_active'):
        return 'A OpenAI informou falta de créditos ou limite de faturamento. Confira o faturamento da conta; os limites locais não adicionam saldo.'
    if status==429:
        return 'A OpenAI limitou temporariamente as requisições. Aguarde antes de solicitar outra análise.'
    if status>=500:
        return 'O provedor está temporariamente indisponível. Tente novamente mais tarde.'
    return 'A OpenAI recusou a solicitação. Confira o modelo e as permissões da conta; use o diagnóstico nas Configurações.'
