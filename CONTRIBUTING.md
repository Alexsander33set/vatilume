# Contribuir com o Vatilume

O projeto é mantido pela **APFS <contato@apfs.com.br>**. O código é licenciado sob **GPL-3.0-or-later**; contribuições incorporadas ao projeto devem ser disponibilizadas sob essa mesma licença. Você mantém a titularidade de suas contribuições e deve ter direito de enviá-las. Não há cessão de direitos ou CLA adicional nesta etapa.

## Propor uma mudança

Descreva o problema, comportamento esperado e ambiente, com dados sintéticos. Discuta primeiro mudanças grandes, acesso a novos dados ou permissões. Não abra issue pública para vulnerabilidades: siga [SECURITY.md](SECURITY.md). Não há cobrança ou funcionalidade exclusiva para apoiadores.

Use branches e commits pequenos. Consulte [a direção do projeto](docs/DIRECAO.md), [PRODUCT.md](PRODUCT.md) e [DESIGN.md](DESIGN.md). Preserve o design atual, o baixo consumo do coletor e a distinção entre leitura de componentes, projeção e consumo total desconhecido. Números sem cobertura não podem virar zero, coincidência temporal não prova causa e RSS não equivale a memória exclusiva.

## Verificação

O [README](README.md) descreve dependências e comandos. Execute testes Python, build do frontend e `python3 scripts/check_repository.py` depois de preparar os arquivos no índice Git. CI usa fixtures sintéticas e IA simulada, sem chave e sem inferência paga. Faça testes de navegador quando a mudança afetar a interface e ensaios de instalação/atualização/remoção quando afetar o pacote. Use VM descartável para ensaios destrutivos, nunca o histórico pessoal como fixture.

Confira dependências a partir de instalação limpa. Atualize versões da aplicação de forma estruturada em `device_observability/__init__.py`, `pyproject.toml` e metadados raiz de `frontend/package.json`/`package-lock.json`; **não faça substituição global de versões em lockfiles**. Números iguais podem ser de dependências diferentes.

## Privacidade e distribuição

Não comite bancos, chaves, arquivos de sessão, modelos, ambientes, wheels, builds, backups ou relatórios pessoais. Não publique fotos/capturas com nomes de processos ou dados pessoais sem revisão. `.gitignore` complementa, não substitui, revisão do índice, histórico e scanner de segredos.

Novas dependências precisam de origem verificável, compatibilidade de licença, avisos completos e fontes apropriadas ao artefato distribuído. Não copie código ou marca de outro projeto apenas por ser gratuito. Veja [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

Crie tags somente após verificação. Tag privada não significa lançamento público. Mudar o checkout não atualiza o pacote instalado. Não altere a visibilidade do repositório, publique instaladores ou execute chamadas pagas sem autorização específica do mantenedor.
