# Fontes e reconstrução do pacote

A distribuição pública deve acompanhar cada `.deb` com o bundle de fontes da mesma versão, avisos e hashes. A candidatura fica privada até aprovação. O bundle não contém `.git`, histórico do PC ou segredos.

## Conteúdo

- Código original Vatilume, testes sintéticos, frontend Vue/TypeScript, assets SVG, configuração de exemplo e scripts de build/empacotamento.
- Lockfiles completos e 14 wheels CPython 3.12/amd64 usados pelo builder, para reconstruir o runtime sem buscar dependências Python.
- Arquivos-fonte PyPI (`sdist`), pacotes npm e crates Rust apontados pelo inventário, com hashes conferidos.
- Fontes Vue e Lucide de commits exatos registrados em `third_party/source-pins.json`, além dos arquivos npm que podem conter código gerado. Avisos adicionais wit-bindgen vêm do commit registrado pelo crate.
- `SOURCE-MANIFEST.json`, com SHA-256 de cada entrada, e checksum externo do bundle. O manifesto não se inclui a si próprio.

`upstream/` contém arquivos originais dos fornecedores, sem modificações do Vatilume. Inspecione os arquivos antes de extrair e execute builds em ambiente isolado. Os tarballs npm podem conter scripts upstream: os testes de build devem usar ambiente descartável sem chaves, e não a conta de serviço do coletor.

## Reconstruir a aplicação

Alvo validado: Ubuntu 24.04 amd64, Python 3.12 e Node.js 24, npm, `dpkg-deb`. Use ambiente limpo, sem estado de produção. Depois de extrair o bundle:

```sh
cd vatilume
python3 -m venv backend/.venv
backend/.venv/bin/python -m pip install --no-index --find-links scripts/wheels --require-hashes -r backend/requirements.lock
npm --prefix frontend ci
npm --prefix frontend run build
python3 scripts/build_deb.py
```

APT provê as ferramentas de sistema; `npm ci` consulta o registry de acordo com o lockfile. Arquivos npm também estão no bundle para inspeção/preparação de cache offline; não há promessa de build inteiramente offline. O builder não exige Git, root ou uma chave de API. Os fontes/avisos do inventário já acompanham o bundle; regenerá-los requer acesso aos upstreams e `scripts/prepare_third_party.py`.

Os wheels são binários originais dos fornecedores. Para modificar/recompilar uma biblioteca nativa, use seu `sdist`, os crates correspondentes, instruções upstream e toolchain apropriada; pode ser necessário Rust/Cargo e ferramentas adicionais. Isso difere de reconstruir o `.deb` com os wheels já verificados. Bibliotecas e ferramentas gerais do sistema operacional mantêm sua distribuição de fontes própria.

A compilação reproduzível bit a bit não foi estabelecida: timestamps e ambientes das ferramentas podem mudar o checksum. Registre a versão das ferramentas, manifestos de entrada e hashes de saída. Hash não substitui autenticação de origem ou assinatura.
