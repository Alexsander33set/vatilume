# Dependências e avisos de terceiros

Vatilume: Copyright (C) 2026 APFS <contato@apfs.com.br>, GPL-3.0-or-later. A licença do projeto não substitui as licenças de seus componentes. Veja [LICENSE](LICENSE) e [NOTICE](NOTICE).

A distribuição usa Vue e Lucide no frontend; FastAPI, Starlette, Uvicorn, Pydantic e outras bibliotecas no backend. O componente nativo pydantic-core inclui dependências Rust que têm seus próprios avisos e exceções. As licenças declaradas incluem MIT, Apache-2.0, BSD, Unicode, Zlib e alternativas com exceções; nomes de famílias de licença não substituem os textos completos.

- Inventário detalhado: `third_party/inventory.json`, com versões, hashes, origens, escopo e caminho de cada aviso.
- Textos completos coletados dos arquivos upstream: `third_party/licenses/`.
- O pacote instalado mantém esses arquivos em `/usr/share/doc/vatilume/third_party/`, além dos avisos Python em `/usr/lib/vatilume/vendor/*.dist-info/`.
- O builder também preserva avisos das dependências npm instaladas. Alguns componentes servem ao build/teste e não ficam no JavaScript final; o inventário é deliberadamente conservador.
- `scripts/prepare_third_party.py` verifica hashes de wheels/sdists contra o lock Python, integridade dos arquivos npm contra o lock e arquivos Rust contra o SBOM incluído no wheel. Os downloads não são executados.

Python, GLib/GIO, systemd, bibliotecas do sistema, navegador e pacotes obtidos pelo APT são dependências do sistema operacional; suas licenças/fontes são fornecidas por seus respectivos distribuidores. Modelos de IA não são incorporados ao `.deb`; a API opcional está sujeita aos termos externos do provedor.

## Código-fonte para distribuição

O cache local `var/distribution/upstream/` contém fontes/arquivos de registro dos upstreams, fica fora do Git e não contém o estado do usuário. Arquivos npm podem conter JavaScript gerado. Esse cache, isoladamente, **não é uma declaração de código-fonte correspondente completo** da interface compilada.

As fontes Vue/Lucide estão fixadas por commit/hash em `third_party/source-pins.json` e incluídas no bundle preparado por `scripts/build_source_bundle.py`; veja [reconstrução](docs/FONTES.md). Antes de uma publicação binária, confira as fontes preferidas para modificação, e fornecer junto com o binário a versão exata do código do projeto, fontes necessárias das dependências, lockfiles e instruções de build. Não publique só o `.deb` ou apenas links para branches que podem mudar. Registre hashes do conjunto e a origem do build. A revisão de prontidão documenta o que foi efetivamente preparado/testado e o que ainda falta.
