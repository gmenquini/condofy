# Manual do Condofy — Guia de Uso

## URL do sistema
- **API:** https://condofy-lvo3.onrender.com
- **Documentação interativa:** https://condofy-lvo3.onrender.com/docs

---

## Usuários de exemplo criados automaticamente

| Usuário | Email | Senha | Nível de acesso |
|---------|-------|-------|-----------------|
| **Super Admin** | admin@condofy.com.br | Condofy@2026! | Acesso total ao sistema |
| **Admin Demo** | admin@demo.com.br | Demo@2026! | Gerencia a Administradora Demo |
| **Gerente Demo** | gerente@demo.com.br | Gerente@2026! | Acesso operacional |
| **Operador Demo** | operador@demo.com.br | Operador@2026! | Acesso básico |

---

## Níveis de acesso

| Nível | O que pode fazer |
|-------|-----------------|
| **Super Admin** | Criar/ver todas as administradoras, todos os usuários, todos os dados |
| **Admin Tenant** | Gerenciar a própria administradora, criar usuários, ver todos os condomínios |
| **Gerente** | Operar conciliação, lançamentos, contas bancárias |
| **Operador** | Visualizar dados, conciliar manualmente |

---

## Como fazer login

### Via Swagger (para testar):
1. Acesse https://condofy-lvo3.onrender.com/docs
2. Clique em **POST /auth/login**
3. Clique em **Try it out**
4. Preencha:
```json
{
  "email": "admin@condofy.com.br",
  "senha": "Condofy@2026!"
}
```
5. Execute — vai retornar um `access_token`
6. Copie o token
7. Clique no botão **Authorize** (cadeado) no topo da página
8. Cole o token no campo **Value** e clique **Authorize**
9. Agora todos os endpoints estão autenticados

---

## Fluxo básico de uso

### 1. Super Admin cria uma administradora
```
POST /tenants
{
  "nome": "Administradora Silva Ltda",
  "cnpj": "12.345.678/0001-99",
  "email": "contato@silva.com.br"
}
```

### 2. Administradora se cadastra sozinha
```
POST /auth/registro-administradora
{
  "nome": "João Silva",
  "email": "joao@silva.com.br",
  "senha": "MinhaSenh@123",
  "nome_empresa": "Administradora Silva Ltda",
  "cnpj": "12.345.678/0001-99"
}
```

### 3. Criar condomínio
```
POST /tenants/{tenant_id}/condominios
{
  "nome": "Residencial das Flores",
  "cidade": "São Paulo",
  "estado": "SP",
  "total_unidades": 48
}
```

### 4. Conectar banco via Pluggy
```
POST /tenants/{tenant_id}/pluggy/connect-token
{}
```
Retorna um `connect_token` para abrir o widget de conexão bancária.

### 5. Sincronizar extrato
```
POST /tenants/{tenant_id}/contas/{conta_id}/sync
```

### 6. Executar conciliação automática
```
POST /tenants/{tenant_id}/condominios/{condominio_id}/conciliar
{
  "mes_referencia": "2026-06"
}
```

### 7. Ver transações pendentes
```
GET /tenants/{tenant_id}/condominios/{condominio_id}/transacoes?status=pendente
```

### 8. Conciliar manualmente uma transação
```
PATCH /tenants/{tenant_id}/transacoes/{transacao_id}/conciliar
{
  "lancamento_id": "uuid-do-lancamento",
  "observacao": "Conciliado manualmente"
}
```

---

## Como criar novos usuários

### Admin cria usuário na própria administradora:
```
POST /usuarios
{
  "nome": "Maria Operadora",
  "email": "maria@silva.com.br",
  "senha": "Senha@123",
  "role": "operador"
}
```

### Roles disponíveis:
- `super_admin` — só Super Admin pode criar
- `admin_tenant` — admin da administradora
- `gerente` — gerente
- `operador` — operador comum

---

## Como trocar senha
```
PATCH /usuarios/{usuario_id}/senha
{
  "nova_senha": "NovaSenha@123"
}
```

---

## Observações importantes

1. **Token expira em 8 horas** — faça login novamente quando expirar
2. **Plano gratuito do Render** — o serviço "dorme" após 15 minutos sem uso. A primeira requisição após isso pode demorar ~50 segundos para acordar
3. **Banco de dados gratuito** — o PostgreSQL gratuito do Render expira em 90 dias. Antes de expirar, crie um novo e atualize o DATABASE_URL
4. **Pluggy sandbox** — as credenciais atuais são de teste. Para produção, criar conta com CNPJ real em pluggy.ai

---

## Problemas comuns

**"Token inválido ou expirado"** → Faça login novamente

**"Sem permissão"** → Verifique se está usando o token do usuário correto para aquele tenant

**"Connection refused"** → O serviço está acordando, aguarde 50 segundos e tente novamente
