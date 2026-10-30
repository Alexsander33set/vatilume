# Preparação da prévia 0.8.0

Mantenedor: APFS <contato@apfs.com.br>. Esta é a lista operacional de lançamento, separada do guia de instalação. A preparação não publica automaticamente o código ou os arquivos.

## Modelo do projeto

Software livre e open source sob GPL-3.0-or-later, gratuito, com apoio voluntário por Pix. Não há assinatura, recursos exclusivos, servidor de contas ou coleta automática de telemetria para a APFS. A IA é opcional, com chave e orçamento escolhidos pelo usuário. Não há perfil Apoia.se ou GitHub Sponsors cadastrado.

Documentação essencial: [LICENSE](../LICENSE), [avisos de terceiros](../THIRD_PARTY_NOTICES.md), [privacidade](../PRIVACY.md), [segurança](../SECURITY.md), [suporte](../SUPPORT.md) e [contribuição](../CONTRIBUTING.md). Os avisos não substituem o funcionamento concreto dessas proteções.

## Repositórios e arquivos

- `Alexsander33set/vatilume-history`: arquivo privado do histórico de desenvolvimento anterior. Não usar esse histórico para a abertura pública.
- `Alexsander33set/vatilume`: repositório novo com um commit inicial limpo, preparado para distribuição. Continua privado durante a conferência; o lançamento fica em rascunho.
- Não transportar branches, tags, releases, anexos ou relatórios pessoais do repositório histórico. Dados de execução, credenciais e backups não fazem parte da distribuição.

O conjunto da prévia contém `vatilume_0.8.0-2_amd64.deb`, `vatilume-0.8.0-source.tar.gz`, `RELEASE-MANIFEST.json` e `SHA256SUMS`. O manifesto registra commit, alvo e hashes. O bundle de fontes inclui o índice revisado, fontes upstream selecionadas pelo inventário, wheels travados, avisos e instruções de build. ZIP/tar.gz automáticos do GitHub não substituem esse conjunto.

O pacote `-2` mantém a aplicação 0.8.0 e prepara documentação/metadados para distribuição; não atualiza a instalação pessoal automaticamente. A revisão anterior `-1` foi preservada como artefato privado testado. Não alegar assinatura do editor ou compilação reproduzível bit a bit: essas propriedades ainda não foram estabelecidas.

## Conferência da versão

1. Revisar o índice e executar `scripts/check_repository.py` e scanner de segredos sobre a cópia limpa. Nunca varrer/copiar recursivamente o estado pessoal de `var` para uma publicação.
2. Rodar testes Python, build Vue/TypeScript e testes sintéticos de navegador, sem inferência paga. O CI repete essas verificações e constrói o pacote em Ubuntu 24.04.
3. Testar instalação, atualização, preservação na remoção/reinstalação, purge e continuidade da coleta em VM Ubuntu 24.04 com systemd real. A prova visual do menu é separada da prova de API.
4. Preparar o repositório limpo e o bundle de fontes; `scripts/prepare_preview.py` compara todas as entradas do bundle ao commit, inventário/wheels e fontes/avisos do pacote antes de montar os quatro arquivos de distribuição.
5. Anexar apenas esses quatro arquivos à release `v0.8.0`, marcada como **draft** e **prerelease**. Baixá-los novamente e conferir os hashes.

O inventário inclui 189 componentes (14 Python, 99 Rust e 76 npm, incluindo build/teste/plataformas opcionais), com avisos completos. Auditorias e hashes têm escopo e data; não garantem ausência de vulnerabilidades. Instruções e limites de reconstrução: [FONTES.md](FONTES.md).

## Evidências e escopo

A candidata privada 0.8.0-1 passou em 146 testes Python, build e nove testes de navegador, incluindo privacidade/orçamento com Axe. Atualização 0.7.0-2 → 0.8.0-1, remoção/reinstalação, reboot, purge e início sem chave/teto zero foram verificados na VM. A recuperação após uma falha injetada retornou ao pacote anterior e conferiu o histórico. A instalação física foi atualizada preservando dados, tarifa, chave e gastos. Esses resultados pertencem ao artefato anterior, não substituem a conferência da revisão -2.

Firefox e Chromium Snap abriram o painel pelo menu com AppArmor em `enforce`, arquivo de acesso 0600/diretório 0700 e token ausente dos argumentos de processo. O escopo exato, versões e sessão estão em [NAVEGADORES-SNAP.md](NAVEGADORES-SNAP.md). Nenhum confinamento foi desativado.

A VM não possui os sensores físicos de um PC de uso cotidiano. O suporte inicial é Ubuntu 24.04 amd64; não se promete suporte universal a distribuições, Wayland, hardware, mínimo overhead em qualquer PC ou medição total na tomada. Um piloto externo pequeno é o próximo passo de compatibilidade.

## Para abrir ao público

- Conferir a release preparada, fontes correspondentes, hashes e resultado do CI do novo repositório.
- Confirmar que contato@apfs.com.br recebe as mensagens de suporte/segurança. Nenhum e-mail de teste é enviado automaticamente.
- Com autorização do mantenedor, tornar público somente o repositório limpo e publicar a prévia. Manter o histórico privado.
- Ativar GitHub Private Vulnerability Reporting quando o repositório estiver público e ajustar SECURITY.md para refletir o canal realmente ativo.

A GPL concede direitos de uso, modificação e redistribuição e exige preservar suas condições ao distribuir. Apoio voluntário não altera a licença. A pesquisa de nome é preliminar, sem registro ou garantia de exclusividade; veja [IDENTIDADE.md](IDENTIDADE.md). Dados recebidos em suporte ou apoio continuam exigindo cuidado, mesmo em projeto gratuito. A prévia funciona localmente, sem conta de usuário ou assinatura do projeto.
