# Vatilume

## Context and theme

Uma ferramenta pessoal consultada entre outras tarefas no desktop: leitura rápida de números e investigação por filtros. Superfícies claras, texto escuro e cor restrita às ações, seleção e séries. A paleta, a tipografia e o layout atuais foram aprovados pelo proprietário e devem ser preservados.

## Palette

Tokens em OKLCH, ancorados na semente 248.2°: primária `oklch(0.50 0.14 248)`, fundo `oklch(1 0 0)`, superfície secundária `oklch(0.975 0.004 248)`, texto `oklch(0.24 0.025 248)`, texto secundário `oklch(0.46 0.025 248)`, borda `oklch(0.88 0.012 248)`. GPU/estado positivo `oklch(0.44 0.11 165)`, aviso `oklch(0.43 0.10 65)`, erro `oklch(0.45 0.17 25)`.

## Typography and layout

Família `system-ui`, números tabulares, escala fixa em rem. Navegação lateral discreta no desktop, barra compacta no mobile; conteúdo até 1440 px. Blocos delimitados por divisórias, sem grades decorativas de cards ou sombras difusas.

## Components and states

Resumo com filtros de período, tabela de energia/custo por componente, gráfico de histórico e leituras atuais. Sensores e Eventos oferecem aprofundamento. Configurações tem formulários independentes para coletor e tarifa. Ícones informativos abrem explicações por hover, clique e foco; Escape fecha. Estados de carregamento, acesso local, dados ausentes, erros, alterações pendentes e confirmação de aplicação são explícitos.

Análises com IA reutilizam os filtros. A coluna principal contém pergunta, cenário diário ajustável, prévia de dados/gasto, resposta principal e evidências expansíveis. Projeções mensais já aparecem na prévia com cálculo local sem chamada ao modelo. Os dados de apoio ficam recolhidos; a resposta deixa visíveis o cenário e o alcance parcial, com premissas e limitações expansíveis. Uma coluna auxiliar mostra orçamento, pausa e histórico; em telas menores ela fica abaixo. Afirmações usam texto numérico validado, sem decoração de chat. Tabelas com rolagem recebem foco por teclado; abrir uma evidência move foco para a seção e respeita movimento reduzido.

## Motion

Transições de estado de 160 ms, sem animação decorativa de entrada. Movimento reduzido desativa transições.

## Identity

Vatilume combina watt e lume. O monograma V forma uma trilha entre dois pontos de leitura; ele é próprio da aplicação e usa o azul existente. Marca e favicon compartilham o símbolo. O descritor é “Energia e sinais do seu PC”; na navegação compacta, “Energia e sinais do PC”. Não usar selos de marca registrada nem alterar identificadores internos de banco, serviço ou diretório. O comando do desktop é `vatilume`.

## Processos

Página de varreduras e coincidências, com rankings limitados, período compartilhado e detalhes progressivos. CPU em capacidade total da máquina e RSS com páginas compartilhadas explícitos. A interface abre por aplicativo, com nomes amigáveis por regras locais, membros e origem da identificação expansíveis; Processos técnicos mantém nomes curtos/PIDs. Desconhecidos ficam separados. Somas usam apenas membros retidos, com CPU sem referência explícita e RSS compartilhada. Nas evidências também aparece o apelido do grupo usado pela IA. Uma coincidência tem badge próprio e não é apresentada como causa. Configuração mantém cadência e ranking separados do ciclo térmico.
