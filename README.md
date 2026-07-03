# Le Grand Terroir - Sistema de Candidaturas

Sistema completo (site + formulário + banco de dados + painel administrativo) para
receber e gerenciar candidaturas às vagas da Le Grand Terroir.

Não tem nenhuma dependência externa, roda só com Python 3 (biblioteca padrão). Não
precisa instalar nada com `pip`.

## O que tem aqui

- `main.py`: backend que recebe as candidaturas e salva em um banco SQLite, e serve o
  site.
- `frontend/index.html`: o site público, com as vagas e o formulário de candidatura.
- `frontend/admin.html`: painel para ver, filtrar, atualizar status e exportar as
  candidaturas recebidas.
- `candidaturas.db`: banco de dados (criado automaticamente na primeira vez que o
  servidor roda).

## Sobre o formulário: sem upload de arquivo, por decisão de segurança

O formulário **não aceita anexar currículo em arquivo**. Isso foi uma decisão
deliberada: qualquer upload de arquivo aberto ao público é uma porta de entrada para
malware (alguém pode disfarçar um executável de PDF, por exemplo), e evitar esse risco
por completo é mais simples e seguro do que tentar mitigá-lo.

Em vez de currículo anexado, o candidato preenche tudo como texto:
- Dados pessoais e endereço completo
- Experiências profissionais (pode adicionar quantas quiser, com botão "+ Adicionar
  experiência")
- Formação acadêmica (mesma lógica, com "+ Adicionar formação")
- Mensagem / carta de apresentação

Tudo isso fica salvo no banco e aparece formatado no painel admin (clique em "Ver
detalhes" na linha do candidato) e no CSV exportado.

## Identidade visual

O site foi redesenhado com uma direção de marca premium (paleta escura, tipografia
editorial, sem elementos de "portal de RH"). Tudo isso é só CSS/JS puro dentro de
`frontend/index.html` e `frontend/admin.html`, nada de framework.

- **Paleta** (definida em `:root` no `<style>`): Preto Profundo `#0B0B0C`, Vinho Profundo
  `#4A0F1C`, Burgundy `#6E1024`, Ouro Envelhecido `#B89B5E`, Oliva Seco `#5C6652`,
  Grafite Quente `#2B2B2D`, Off White Mineral `#F2EFE8`. O dourado é usado só em
  detalhes (bordas ativas, ícones, botão principal).
- **Tipografia**: `Cormorant Garamond` (títulos, carregada via Google Fonts) e `Inter`
  (textos). Para trocar a fonte, edite os `<link>` do Google Fonts e a variável
  `--serif` / `--sans` no CSS.
- **Fotografia**: as seções "Sobre a operação" (Flagship Store, Wine Bar, Centro de
  Distribuição, Tecnologia) usam blocos com gradiente escuro no lugar de fotos reais.
  Procure por `.photo-plate` no CSS e pela classe `about-block` no HTML. Para colocar
  fotos de verdade, troque o `background` de `.photo-plate` por
  `background-image: url('sua-foto.jpg')` (ou adicione uma tag `<img>` dentro do bloco).
- **Ícones**: sistema próprio de ícones lineares em SVG inline (sem emojis, sem
  bibliotecas externas). Procure por `<svg class="icon"` no HTML para editar ou trocar.

## Rodando localmente (para testar)

Precisa só de Python 3.9 ou mais novo.

```bash
cd le-grand-terroir-sistema
ADMIN_TOKEN=escolha-uma-senha python3 main.py
```

Depois abra:
- Site público: http://localhost:8000
- Painel admin: http://localhost:8000/admin.html (peça o token que você definiu em `ADMIN_TOKEN`)

Sem definir `ADMIN_TOKEN`, o sistema usa a senha padrão `troque-este-token`. Funciona
para testar, mas **troque antes de publicar de verdade**.

## Publicando o site (deploy)

Como é só Python puro, funciona em qualquer serviço que rode uma aplicação Python. Os
dois mais simples e com plano gratuito são o **Render** e o **Railway**. Passo a passo
com o Render:

1. Crie uma conta em [render.com](https://render.com) e um repositório no GitHub com o
   conteúdo desta pasta (`main.py`, `frontend/`, `requirements.txt`, `Procfile`).
2. No Render, clique em **New > Web Service** e aponte para esse repositório.
3. Em **Build Command**, deixe em branco (não há nada para instalar).
4. Em **Start Command**, use: `python3 main.py`
5. Em **Environment Variables**, adicione:
   - `ADMIN_TOKEN` → uma senha forte, só você deve saber
   - `ALLOWED_ORIGIN` → `*` (ou o domínio do site, se for diferente)
6. Clique em **Create Web Service**. Em alguns minutos, o Render te dá uma URL tipo
   `https://le-grand-terroir.onrender.com`. Esse é o seu site, já com o formulário
   funcionando e o painel admin em `/admin.html`.

O Railway funciona de forma bem parecida (New Project > Deploy from GitHub > definir as
mesmas variáveis de ambiente).

### Sobre o banco de dados em produção

O banco (`candidaturas.db`) é um arquivo local no servidor. Isso funciona bem para
começar, mas serviços como Render **apagam o disco a cada novo deploy** no plano
gratuito, a menos que você configure um "disco persistente" (opção paga, ou o plano
gratuito com "Persistent Disk" dependendo do serviço). Se isso for um problema, me avise
que ajusto o sistema para usar um banco externo (ex: Postgres gratuito no próprio
Render/Railway/Supabase), é uma mudança pequena.

## Usando o painel admin

Acesse `/admin.html`, informe o token de administrador e você verá:

- Lista de todas as candidaturas, com busca por nome/e-mail/telefone e filtro por vaga
  ou status.
- Botão "Ver detalhes" em cada linha, que expande o endereço completo, as experiências
  profissionais e a formação acadêmica preenchidas pelo candidato.
- Um seletor de status por linha (novo, em análise, entrevista, aprovado, rejeitado).
- Botão para exportar tudo em CSV (abre certo no Excel/Google Sheets, com acentos).
- Botão para remover uma candidatura.

O token fica salvo no navegador só durante a sessão (fecha a aba, precisa digitar de
novo).

## Segurança: o que saber antes de publicar

- O "login" do admin é um token único (não é usuário/senha por pessoa). Serve bem para
  uma ou poucas pessoas de RH gerenciando as candidaturas. Se quiser login individual
  por pessoa (com e-mail/senha), dá para evoluir o sistema, é só pedir.
- Sempre acesse o painel admin por HTTPS (os serviços de hospedagem citados já dão isso
  de graça) para o token não trafegar exposto.
- Troque o `ADMIN_TOKEN` padrão antes de publicar. É a única coisa que protege os
  dados pessoais das candidaturas.

## Personalizando

- **E-mail de contato / vagas**: os textos do site estão em `frontend/index.html`.
- **Lista de vagas**: em `frontend/index.html`, todas as vagas vêm de um único array
  JavaScript (`const VAGAS = [...]`, perto do final do arquivo). Os cards, o select do
  formulário e os filtros são gerados a partir dele, então editar uma vaga é editar um
  único lugar. O título de cada vaga também precisa bater exatamente com a lista
  `VAGAS_VALIDAS` em `main.py` (é o que o backend usa para validar candidaturas). Se
  adicionar ou remover uma vaga, atualize os dois arquivos.
- **Área/departamento de cada vaga** (usado nos chips de filtro "Operações",
  "Logística" etc.): é o objeto `const AREAS = {...}` logo acima de `VAGAS` no mesmo
  arquivo.
- **Frontend e backend em hosts diferentes**: se um dia você quiser hospedar o site
  separado do backend, edite a constante `API_BASE_URL` no `<script>` de
  `frontend/index.html` e `frontend/admin.html` para apontar para a URL do backend.
