# Direção do Vatilume

Vatilume é software livre e open source sob GPL-3.0-or-later, mantido pela APFS. O público inicial são pessoas com PC próprio, especialmente jogadores e usuários técnicos de Linux. O produto é gratuito, com apoio voluntário, e não tem assinatura ou funcionalidades exclusivas para apoiadores.

## Produto

O foco é tornar útil o histórico de energia reportada, uso, temperatura e aplicativos, com evidências acessíveis. Uma coincidência de processos e picos serve à investigação; não prova causa nem atribui energia a um aplicativo. Sensores internos não medem o consumo total na tomada.

A experiência visível é uma aba no navegador padrão, aberta pelo menu ou comando `vatilume`. O coletor é um serviço independente e continua após fechar a aba e entre sessões de login. Não exige conta online. Uma janela desktop própria pode ser avaliada depois, se trouxer benefício concreto.

## Distribuição inicial

A prévia 0.8.0 usa pacote `.deb` para Ubuntu 24.04 amd64, Python 3.12 e systemd, com dependências Python e interface incluídas. O APT resolve dependências do sistema. Docker, Node e pip não são requisitos para o usuário final. Veja [PACOTE-DEB.md](PACOTE-DEB.md).

Outras distribuições, arquiteturas e versões precisam de testes próprios. Flatpak continua uma possibilidade futura, talvez para a interface combinada a um serviço nativo; é necessário validar acesso aos sensores/processos do host e funcionamento sem login gráfico. Docker pode ser usado no desenvolvimento, mas não será uma dependência da instalação pessoal.

O piloto deve verificar sensores disponíveis, abertura no navegador, recuperação e overhead em outros PCs antes de ampliar a matriz de suporte. Os resultados de VM não comprovam desempenho ou sensores físicos.

## IA com chave própria

O painel integra a API OpenAI com a chave do usuário. A instalação nova começa sem chave, com IA pausada e teto acumulado zero. Coleta, gráficos e cálculos locais continuam sem IA. Não existe chave mestra, saldo ou gateway do projeto.

Outros provedores, modelos configuráveis e IA local são evoluções futuras da interface. Os scripts experimentais não equivalem a essas integrações no produto. Cada integração precisa de testes de ferramentas, evidências, privacidade, erros e gastos. Os limites locais não substituem os controles ou a fatura do provedor.

## Apoio e comunidade

O apoio por [Pix](https://nubank.com.br/cobrar/mr23i/6ae37aad-7e87-48e3-be17-f4153a29130a) está configurado no README e no botão de apoio do GitHub. Não foi criado perfil Apoia.se ou GitHub Sponsors; só apontaremos a um canal depois de concluir seu cadastro. O apoio não desbloqueia recursos nem contrata suporte com prazo garantido.

O [ZapZap](https://github.com/rafatosta/zapzap) é referência de apresentação e apoio comunitário. A licença, o código e as decisões do Vatilume são próprios. Não fazemos previsão de receita com base em outro projeto.

## Código e próximos passos

O repositório de distribuição nasce com um commit inicial limpo. O histórico de desenvolvimento anterior fica em outro repositório privado. Bancos, chaves, modelos, backups e diagnósticos pessoais não acompanham o código nem os instaladores. CI usa dados sintéticos e IA simulada.

As prioridades após a prévia são acompanhar o piloto, melhorar os agrupamentos de aplicativos, controlar crescimento/retenção do histórico e ampliar a utilidade das análises. Novos sensores e provedores devem responder a perguntas que os dados atuais não resolvem.

A lista de preparação e a decisão de abertura ficam em [PUBLICACAO.md](PUBLICACAO.md); licença, privacidade, segurança e suporte estão na raiz do repositório.
