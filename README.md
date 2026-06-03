# Condofy API

ERP para administradoras de condomínios — módulo de conciliação bancária via Pluggy Open Finance.

## Stack
- **Backend**: Python 3.12 + FastAPI
- **Banco**: PostgreSQL
- **Open Finance**: Pluggy (200+ bancos brasileiros)
- **Deploy**: Railway

---

## Setup local

```bash
# 1. Clonar e entrar na pasta
cd condofy

# 2. Criar ambiente virtual
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows

# 3. Instalar dependências
pip install -r requirements.txt

# 4. Configurar variáveis
cp .env.example .env
# editar .env com suas credenciais

# 5. Subir PostgreSQL local (ou usar Railway)
# Se tiver Docker:
docker run -d --name condofy-db -e POSTGRES_PASSWORD=postgres -p 5432:5432 postgres:16

# 6. Rodar a API
uvicorn app.main:app --reload
```

API disponível em: http://localhost:8000
Docs interativas: http://localhost:8000/docs

---

## Deploy no Railway

```bash
# 1. Instalar Railway CLI
npm install -g @railway/cli

# 2. Login
railway login

# 3. Criar projeto
railway init

# 4. Adicionar PostgreSQL
railway add --plugin postgresql

# 5. Configurar variáveis de ambiente no Railway Dashboard
# (copiar do .env.example e preencher)

# 6. Deploy
railway up
```

Railway detecta o `railway.toml` e sobe automaticamente.

---

## Estrutura do banco (hierarquia de isolamento)

```
Tenant (Administradora)
  └── Condomínio
        ├── ContaBancaria (via Pluggy)
        │     └── Transacao (extrato)
        ├── Lancamento (receitas e despesas)
        │     └── Lancamento (parcelas filhas)
        ├── Boleto
        ├── Remessa
        ├── Unidade
        │     └── Morador
        └── Fornecedor
```

**Regra de ouro**: toda query filtra `tenant_id` + `condominio_id`. Sem exceção.

---

## Problemas do sistema legado → soluções implementadas

| # | Problema | Solução no Condofy |
|---|----------|-------------------|
| 11 | Boletos duplicados após exclusão | Status `CANCELADO`/`SUBSTITUIDO` — app mostra só ativos |
| 12 | Remessa rejeitada bloqueia edição | Status granular: `REJEITADA` permite edição e reenvio |
| 15 | Boletos trocados entre condôminos | Isolamento triplo: `tenant_id` + `condominio_id` + `unidade_id` |
| 9 | DARF/DAS/FGTS não reconhecidos | Campo `tipo_codigo_barras` com enum explícito |
| 13 | Emails caindo em spam | SendGrid com SPF/DKIM/DMARC configurados |
| 26 | Despesas duplicadas sem aviso | Hash de duplicata + verificação antes de inserir |
| 22 | Troca de condomínio volta à home | Estado na URL (`?condo=id&modulo=conciliacao`) |
| 12m | Despesas parceladas sem visibilidade | `parcela_pai_id` + `numero_parcela/total_parcelas` |
| 20 | Ordenação de despesas invertida | `ORDER BY vencimento ASC` com âncora na data atual |

---

## Endpoints principais

```
GET  /health
POST /tenants
GET  /tenants/{id}/condominios
POST /tenants/{id}/condominios
GET  /tenants/{id}/condominios/{cid}/contas
POST /tenants/{id}/condominios/{cid}/transacoes
POST /tenants/{id}/condominios/{cid}/conciliar
POST /tenants/{id}/condominios/{cid}/lancamentos/verificar-duplicata
POST /tenants/{id}/condominios/{cid}/lancamentos
POST /tenants/{id}/pluggy/connect-token
POST /webhooks/pluggy/{tenant_id}
POST /tenants/{id}/contas/{cid}/sync
```

Documentação completa: `/docs` (Swagger) ou `/redoc`
