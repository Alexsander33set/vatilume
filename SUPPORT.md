# Ajuda com o Vatilume

O Vatilume é gratuito e mantido pela APFS, com apoio voluntário. O suporte é comunitário, conforme disponibilidade, sem prazo garantido ou prioridade paga. A prévia começa pelo Ubuntu 24.04 amd64.

## Dúvidas comuns

| Situação | O que conferir |
| --- | --- |
| O endereço local pede acesso | Abra **Vatilume** pelo menu ou execute `vatilume`. Um endereço copiado não autoriza outro navegador. |
| O navegador Snap não abre | Abra o Firefox/Chromium uma vez para inicializar o perfil; depois abra Vatilume pelo menu. Não desative o confinamento ou amplie permissões. |
| Falta potência ou temperatura | Nem todo hardware expõe esses sensores. Confira Sensores e os grupos habilitados em Configurações; não substitua ausência por TDP ou zero. |
| O primeiro valor de CPU por processo está ausente | O cálculo precisa de duas varreduras; aguarde a cadência configurada. O ranking é limitado e não representa todos os processos. |
| Não aparece custo em reais | Configure uma tarifa com vigência. Leituras de componentes não cobrem toda a energia da tomada. |
| IA não prepara uma análise | É opcional: configure sua chave, habilite as chamadas e escolha limites de gasto. Os controles locais não substituem o limite/fatura do provedor. |
| Não há diálogo de autorização | É necessária uma sessão gráfica com agente polkit. Consulte os requisitos em [PACOTE-DEB.md](docs/PACOTE-DEB.md). Não execute o navegador com sudo. |

## Relatar um problema

Use a issue de problema no repositório ou contato@apfs.com.br. Informe versão do Vatilume, distribuição/versão, navegador e passos para reproduzir. Descreva o resultado esperado e o observado. Prefira um exemplo sintético e trechos curtos de erro, revisados.

Não envie bancos, backups, chave de API, cookie, arquivo de acesso ou captura que mostre uma credencial/atividade pessoal. Não há upload automático de diagnósticos. Para uma vulnerabilidade, use o canal privado indicado em [SECURITY.md](SECURITY.md), antes de abrir uma issue.

As configurações de coleta e de IA ficam no próprio PC. A remoção comum preserva esses dados; purge os apaga. Revise [PRIVACY.md](PRIVACY.md) e faça um backup privado antes de excluir algo importante.
