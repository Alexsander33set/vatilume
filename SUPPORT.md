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

Abra o [seletor de atendimento](https://github.com/Alexsander33set/vatilume/issues/new/choose) e escolha **Relatar um problema** ou **Pedir ajuda**. Pesquise issues existentes para evitar duplicação; se for o mesmo comportamento, acrescente apenas seu ambiente e as diferenças relevantes. Não é preciso publicar seu e-mail: a conversa ocorre na própria issue.

Para investigar um problema, precisamos principalmente de:

- Versão do Vatilume/pacote e distribuição Linux com versão.
- Navegador e forma de instalação (Snap/Flatpak/nativo), desktop e X11/Wayland quando envolver painel/menu.
- Passos para reproduzir, frequência, resultado esperado e o que ocorreu, incluindo a mensagem de erro exata.
- Horário aproximado com fuso, período/filtros e suspensão/reinício quando envolver coleta/histórico.
- Tentativas anteriores e mudanças recentes; modelos de CPU/GPU/driver apenas se forem relevantes ao sensor ou desempenho.

Informe quando não souber algum dado. Não precisamos de um inventário completo do computador. Campos e anexos serão públicos. O rótulo `triagem` identifica relatos que ainda precisam ser avaliados; `bug` identifica problemas e `suporte`/`question` organizam dúvidas. Eles não prometem prazo ou confirmação prévia da causa.

## Diagnóstico opcional

Estes comandos somente consultam a instalação. Execute apenas se conseguir e se forem úteis ao problema; leia a saída antes de copiá-la. A versão também aparece em **Sobre e privacidade** e a distribuição em **Configurações do sistema → Sobre**.

```sh
# Versão instalada pelo pacote.
dpkg-query -W vatilume

# Versão do kernel, sem hostname.
uname -r

# Acesso do lançador ao painel local.
vatilume --check

# Estado dos dois componentes iniciados pelo sistema.
systemctl is-active device-observability.service device-observability-web.socket
```

Para um erro recente do serviço, um trecho curto pode ajudar:

```sh
journalctl -u device-observability.service -u device-observability-web.service --since "15 minutes ago" -n 40 --no-pager --output=cat
```

Se aparecer falta de permissão, informe isso; não amplie permissões para conseguir um log. Revise inclusive os trechos de erro: remova nomes de usuário/PC, caminhos pessoais, dados de processos e qualquer segredo. O diagnóstico não é enviado automaticamente e não é obrigatório anexar capturas.

**Não envie** bancos, backups, chave de API, cookie, arquivo de acesso, perguntas pessoais à IA ou logs completos. Para dados sensíveis indispensáveis ao suporte, combine primeiro por contato@apfs.com.br. O recebimento do contato foi testado em 30/10/2026. Para suspeitas de vulnerabilidade, use o [relato privado](https://github.com/Alexsander33set/vatilume/security/advisories/new) conforme [SECURITY.md](SECURITY.md), sem abrir issue pública com detalhes da falha.

As configurações de coleta e de IA ficam no próprio PC. A remoção comum preserva esses dados; purge os apaga. Revise [PRIVACY.md](PRIVACY.md) e faça um backup privado antes de excluir algo importante.
