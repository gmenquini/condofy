"""
Condofy API — Backend principal
FastAPI + PostgreSQL + Pluggy Open Finance
"""

from fastapi import FastAPI, Depends, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from sqlalchemy import create_engine, text, select
from sqlalchemy.orm import sessionmaker
from contextlib import asynccontextmanager
import os

from .models.base import Base
from .models import (
    Tenant, Condominio, ContaBancaria, Transacao,
    Lancamento, Remessa, Boleto, Fornecedor, Morador, Unidade
)
from .models.usuario import Usuario, RoleUsuario
from .services.conciliacao_service import conciliar_automatico, verificar_duplicata, gerar_hash_duplicata
from .services.auth_service import (
    autenticar_usuario, criar_token, decodificar_token,
    criar_usuario, hash_senha, seed_usuarios
)
from .services.pluggy_service import get_pluggy_service

security = HTTPBearer()

# ─── Banco de dados ───────────────────────────────────────────────────────────

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/condofy"
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ─── App ──────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    print("✓ Tabelas criadas/verificadas")
    db = SessionLocal()
    try:
        seed_usuarios(db)
    finally:
        db.close()
    yield


app = FastAPI(
    title="Condofy API",
    description="ERP para administradoras de condomínios",
    version="0.1.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Auth helpers ─────────────────────────────────────────────────────────────

def get_usuario_atual(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> Usuario:
    token = credentials.credentials
    payload = decodificar_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Token inválido ou expirado")
    usuario = db.get(Usuario, payload.get("sub"))
    if not usuario or not usuario.ativo:
        raise HTTPException(status_code=401, detail="Usuário não encontrado")
    return usuario


def requer_super_admin(usuario: Usuario = Depends(get_usuario_atual)) -> Usuario:
    if usuario.role != RoleUsuario.SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="Acesso restrito ao Super Admin")
    return usuario


def requer_admin_ou_acima(usuario: Usuario = Depends(get_usuario_atual)) -> Usuario:
    if usuario.role not in [RoleUsuario.SUPER_ADMIN, RoleUsuario.ADMIN_TENANT]:
        raise HTTPException(status_code=403, detail="Acesso restrito a administradores")
    return usuario


# ─── Health ───────────────────────────────────────────────────────────────────

@app.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok", "service": "condofy-api", "version": "0.1.0"}


# ─── Autenticação ─────────────────────────────────────────────────────────────

@app.post("/auth/login")
def login(dados: dict, db: Session = Depends(get_db)):
    """Login com email e senha. Retorna JWT token."""
    usuario = autenticar_usuario(db, dados.get("email"), dados.get("senha"))
    if not usuario:
        raise HTTPException(status_code=401, detail="Email ou senha incorretos")

    token = criar_token({
        "sub": usuario.id,
        "email": usuario.email,
        "role": usuario.role,
        "tenant_id": usuario.tenant_id
    })

    return {
        "access_token": token,
        "token_type": "bearer",
        "usuario": {
            "id": usuario.id,
            "nome": usuario.nome,
            "email": usuario.email,
            "role": usuario.role,
            "tenant_id": usuario.tenant_id
        }
    }


@app.get("/auth/me")
def me(usuario: Usuario = Depends(get_usuario_atual)):
    """Retorna dados do usuário logado."""
    return {
        "id": usuario.id,
        "nome": usuario.nome,
        "email": usuario.email,
        "role": usuario.role,
        "tenant_id": usuario.tenant_id,
        "condominio_id": getattr(usuario, 'condominio_id', None)
    }


@app.post("/auth/registro-administradora", status_code=201)
def registro_administradora(dados: dict, db: Session = Depends(get_db)):
    """
    Administradora se cadastra sozinha.
    Cria tenant + admin do tenant.
    """
    # Verifica se email já existe
    if db.execute(select(Usuario).where(Usuario.email == dados["email"])).scalars().first():
        raise HTTPException(400, "Email já cadastrado")

    tenant = Tenant(
        nome=dados["nome_empresa"],
        cnpj=dados["cnpj"],
        email=dados["email"],
        pluggy_client_id=os.getenv("PLUGGY_CLIENT_ID"),
        pluggy_client_secret=os.getenv("PLUGGY_CLIENT_SECRET"),
    )
    db.add(tenant)
    db.flush()

    usuario = criar_usuario(
        db, dados["nome"], dados["email"], dados["senha"],
        RoleUsuario.ADMIN_TENANT, tenant.id
    )

    token = criar_token({"sub": usuario.id, "email": usuario.email,
                         "role": usuario.role, "tenant_id": tenant.id})

    return {"access_token": token, "token_type": "bearer",
            "tenant_id": tenant.id, "usuario_id": usuario.id}


# ─── Usuários ─────────────────────────────────────────────────────────────────

@app.get("/usuarios")
def listar_usuarios(
    usuario_atual: Usuario = Depends(get_usuario_atual),
    db: Session = Depends(get_db)
):
    """Lista usuários do tenant. Super admin vê todos."""
    if usuario_atual.role == RoleUsuario.SUPER_ADMIN:
        usuarios = db.query(Usuario).all()
    else:
        usuarios = db.query(Usuario).filter(
            Usuario.tenant_id == usuario_atual.tenant_id
        ).all()

    return [{"id": u.id, "nome": u.nome, "email": u.email,
             "role": u.role, "ativo": u.ativo} for u in usuarios]


@app.post("/usuarios", status_code=201)
def criar_usuario_endpoint(
    dados: dict,
    usuario_atual: Usuario = Depends(requer_admin_ou_acima),
    db: Session = Depends(get_db)
):
    """Admin cria usuário no próprio tenant."""
    if db.execute(select(Usuario).where(Usuario.email == dados["email"])).scalars().first():
        raise HTTPException(400, "Email já cadastrado")

    tenant_id = usuario_atual.tenant_id if usuario_atual.role != RoleUsuario.SUPER_ADMIN else dados.get("tenant_id")
    role = dados.get("role", RoleUsuario.OPERADOR)

    # Admin do tenant não pode criar super_admin
    if usuario_atual.role == RoleUsuario.ADMIN_TENANT and role == RoleUsuario.SUPER_ADMIN:
        raise HTTPException(403, "Não permitido")

    u = criar_usuario(db, dados["nome"], dados["email"], dados["senha"], role, tenant_id)
    # Vincula condomínio para síndico/morador
    if dados.get("condominio_id") and role in ["sindico", "morador"]:
        u.condominio_id = dados["condominio_id"]
        db.commit()
    return {"id": u.id, "nome": u.nome, "email": u.email, "role": u.role}


@app.patch("/usuarios/{usuario_id}/senha")
def trocar_senha(
    usuario_id: str,
    dados: dict,
    usuario_atual: Usuario = Depends(get_usuario_atual),
    db: Session = Depends(get_db)
):
    """Troca senha do próprio usuário ou admin troca de qualquer um do tenant."""
    if usuario_atual.id != usuario_id and usuario_atual.role not in [RoleUsuario.SUPER_ADMIN, RoleUsuario.ADMIN_TENANT]:
        raise HTTPException(403, "Sem permissão")

    usuario = db.get(Usuario, usuario_id)
    if not usuario:
        raise HTTPException(404, "Usuário não encontrado")

    usuario.senha_hash = hash_senha(dados["nova_senha"])
    db.commit()
    return {"ok": True}


# ─── Tenants (Super Admin) ────────────────────────────────────────────────────

@app.get("/tenants")
def listar_tenants(
    _: Usuario = Depends(requer_super_admin),
    db: Session = Depends(get_db)
):
    tenants = db.query(Tenant).all()
    result = []
    for t in tenants:
        n_condos = db.query(Condominio).filter(
            Condominio.tenant_id == t.id, Condominio.ativo == True
        ).count()
        result.append({"id": t.id, "nome": t.nome, "cnpj": t.cnpj, "ativo": t.ativo, "n_condominios": n_condos,
            "cidade": t.cidade, "estado": t.estado, "endereco": t.endereco, "lat": t.lat, "lng": t.lng})
    return result


@app.post("/tenants", status_code=201)
def criar_tenant(dados: dict, _: Usuario = Depends(requer_super_admin), db: Session = Depends(get_db)):
    tenant = Tenant(
        nome=dados["nome"],
        cnpj=dados["cnpj"],
        email=dados["email"],
        telefone=dados.get("telefone"),
        pluggy_client_id=dados.get("pluggy_client_id", os.getenv("PLUGGY_CLIENT_ID")),
        pluggy_client_secret=dados.get("pluggy_client_secret", os.getenv("PLUGGY_CLIENT_SECRET")),
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    return {"id": tenant.id, "nome": tenant.nome}


@app.get("/tenants/{tenant_id}")
def buscar_tenant(tenant_id: str, usuario_atual: Usuario = Depends(get_usuario_atual), db: Session = Depends(get_db)):
    if usuario_atual.role != RoleUsuario.SUPER_ADMIN and usuario_atual.tenant_id != tenant_id:
        raise HTTPException(403, "Sem permissão")
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(404, "Tenant não encontrado")
    return {"id": tenant.id, "nome": tenant.nome, "cnpj": tenant.cnpj, "plano": tenant.plano}


# ─── Condomínios ──────────────────────────────────────────────────────────────

@app.get("/tenants/{tenant_id}/condominios")
def listar_condominios(
    tenant_id: str,
    usuario_atual: Usuario = Depends(get_usuario_atual),
    db: Session = Depends(get_db)
):
    if usuario_atual.role != RoleUsuario.SUPER_ADMIN and usuario_atual.tenant_id != tenant_id:
        raise HTTPException(403, "Sem permissão")
    condominios = db.query(Condominio).filter(
        Condominio.tenant_id == tenant_id, Condominio.ativo == True
    ).all()
    return [{"id": c.id, "nome": c.nome, "cidade": c.cidade,
             "estado": c.estado, "total_unidades": c.total_unidades} for c in condominios]


@app.post("/tenants/{tenant_id}/condominios", status_code=201)
def criar_condominio(
    tenant_id: str, dados: dict,
    usuario_atual: Usuario = Depends(requer_admin_ou_acima),
    db: Session = Depends(get_db)
):
    if usuario_atual.role != RoleUsuario.SUPER_ADMIN and usuario_atual.tenant_id != tenant_id:
        raise HTTPException(403, "Sem permissão")
    condo = Condominio(
        tenant_id=tenant_id, nome=dados["nome"],
        cnpj=dados.get("cnpj"), cidade=dados.get("cidade"),
        estado=dados.get("estado"), total_unidades=dados.get("total_unidades", 0),
    )
    db.add(condo)
    db.commit()
    db.refresh(condo)
    return {"id": condo.id, "nome": condo.nome}


# ─── Contas Bancárias ─────────────────────────────────────────────────────────

@app.get("/tenants/{tenant_id}/condominios/{condominio_id}/contas")
def listar_contas(
    tenant_id: str, condominio_id: str,
    usuario_atual: Usuario = Depends(get_usuario_atual),
    db: Session = Depends(get_db)
):
    if usuario_atual.role != RoleUsuario.SUPER_ADMIN and usuario_atual.tenant_id != tenant_id:
        raise HTTPException(403, "Sem permissão")
    contas = db.query(ContaBancaria).filter(
        ContaBancaria.tenant_id == tenant_id,
        ContaBancaria.condominio_id == condominio_id,
        ContaBancaria.ativa == True
    ).all()
    return [{"id": c.id, "banco_nome": c.banco_nome, "agencia": c.agencia,
             "conta": c.conta, "saldo_atual": float(c.saldo_atual) if c.saldo_atual else None,
             "ultima_sync": c.ultima_sync.isoformat() if c.ultima_sync else None,
             "pluggy_status": c.pluggy_status} for c in contas]


# ─── Pluggy ───────────────────────────────────────────────────────────────────

@app.post("/tenants/{tenant_id}/pluggy/connect-token")
async def gerar_connect_token(
    tenant_id: str, dados: dict,
    usuario_atual: Usuario = Depends(get_usuario_atual),
    db: Session = Depends(get_db)
):
    if usuario_atual.role != RoleUsuario.SUPER_ADMIN and usuario_atual.tenant_id != tenant_id:
        raise HTTPException(403, "Sem permissão")
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(404, "Tenant não encontrado")
    pluggy = get_pluggy_service(tenant)
    webhook_url = os.getenv("PLUGGY_WEBHOOK_URL", f"https://condofy-lvo3.onrender.com/webhooks/pluggy/{tenant_id}")
    token = await pluggy.criar_connect_token(webhook_url=webhook_url, client_user_id=dados.get("user_id", tenant_id))
    return {"connect_token": token}


@app.post("/webhooks/pluggy/{tenant_id}")
async def webhook_pluggy(tenant_id: str, request: Request, db: Session = Depends(get_db)):
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        return JSONResponse({"ok": False}, status_code=404)
    payload = await request.json()
    pluggy = get_pluggy_service(tenant)
    resultado = await pluggy.processar_webhook(db, payload)
    return {"ok": True, **resultado}


@app.post("/tenants/{tenant_id}/contas/{conta_id}/sync")
async def sincronizar_conta(
    tenant_id: str, conta_id: str,
    usuario_atual: Usuario = Depends(get_usuario_atual),
    db: Session = Depends(get_db)
):
    conta = db.query(ContaBancaria).filter(
        ContaBancaria.id == conta_id, ContaBancaria.tenant_id == tenant_id
    ).first()
    if not conta:
        raise HTTPException(404, "Conta não encontrada")
    tenant = db.get(Tenant, tenant_id)
    pluggy = get_pluggy_service(tenant)
    resultado = await pluggy.sync_conta(db, conta)
    return resultado


# ─── Conciliação ──────────────────────────────────────────────────────────────

@app.get("/tenants/{tenant_id}/condominios/{condominio_id}/transacoes")
def listar_transacoes(
    tenant_id: str, condominio_id: str,
    status: str = None,
    usuario_atual: Usuario = Depends(get_usuario_atual),
    db: Session = Depends(get_db)
):
    if usuario_atual.role != RoleUsuario.SUPER_ADMIN and usuario_atual.tenant_id != tenant_id:
        raise HTTPException(403, "Sem permissão")
    query = db.query(Transacao).filter(
        Transacao.tenant_id == tenant_id,
        Transacao.condominio_id == condominio_id
    )
    if status:
        query = query.filter(Transacao.status_conciliacao == status)
    transacoes = query.order_by(Transacao.data.desc()).limit(500).all()
    return [{"id": t.id, "data": t.data.isoformat(), "descricao": t.descricao,
             "valor": float(t.valor), "tipo": t.tipo,
             "status_conciliacao": t.status_conciliacao,
             "lancamento_id": t.lancamento_id} for t in transacoes]


@app.post("/tenants/{tenant_id}/condominios/{condominio_id}/conciliar")
def executar_conciliacao(
    tenant_id: str, condominio_id: str,
    dados: dict = {},
    usuario_atual: Usuario = Depends(get_usuario_atual),
    db: Session = Depends(get_db)
):
    if usuario_atual.role != RoleUsuario.SUPER_ADMIN and usuario_atual.tenant_id != tenant_id:
        raise HTTPException(403, "Sem permissão")
    return conciliar_automatico(db=db, tenant_id=tenant_id,
                                condominio_id=condominio_id,
                                conta_bancaria_id=dados.get("conta_bancaria_id"),
                                mes_referencia=dados.get("mes_referencia"))


@app.patch("/tenants/{tenant_id}/transacoes/{transacao_id}/conciliar")
def conciliar_manual(
    tenant_id: str, transacao_id: str, dados: dict,
    usuario_atual: Usuario = Depends(get_usuario_atual),
    db: Session = Depends(get_db)
):
    if usuario_atual.role != RoleUsuario.SUPER_ADMIN and usuario_atual.tenant_id != tenant_id:
        raise HTTPException(403, "Sem permissão")
    from .models.transacao import StatusConciliacao
    from .models.lancamento import LancamentoStatus
    from datetime import datetime
    transacao = db.query(Transacao).filter(
        Transacao.id == transacao_id, Transacao.tenant_id == tenant_id
    ).first()
    if not transacao:
        raise HTTPException(404, "Transação não encontrada")
    transacao.status_conciliacao = StatusConciliacao.CONCILIADA
    transacao.lancamento_id = dados.get("lancamento_id")
    transacao.conciliado_em = datetime.utcnow()
    transacao.observacao_conciliacao = dados.get("observacao")
    if dados.get("lancamento_id"):
        lancamento = db.get(Lancamento, dados["lancamento_id"])
        if lancamento and lancamento.tenant_id == tenant_id:
            lancamento.status = LancamentoStatus.PAGO
            lancamento.data_pagamento = transacao.data.date()
    db.commit()
    return {"ok": True}


# ─── Lançamentos ──────────────────────────────────────────────────────────────

@app.post("/tenants/{tenant_id}/condominios/{condominio_id}/lancamentos/verificar-duplicata")
def verificar_lancamento_duplicado(
    tenant_id: str, condominio_id: str, dados: dict,
    usuario_atual: Usuario = Depends(get_usuario_atual),
    db: Session = Depends(get_db)
):
    if usuario_atual.role != RoleUsuario.SUPER_ADMIN and usuario_atual.tenant_id != tenant_id:
        raise HTTPException(403, "Sem permissão")
    from .services.conciliacao_service import verificar_duplicata
    return verificar_duplicata(db=db, tenant_id=tenant_id, condominio_id=condominio_id,
                               fornecedor_id=dados["fornecedor_id"], valor=dados["valor"],
                               data_vencimento=dados["data_vencimento"])


@app.post("/tenants/{tenant_id}/condominios/{condominio_id}/lancamentos", status_code=201)
def criar_lancamento(
    tenant_id: str, condominio_id: str, dados: dict,
    usuario_atual: Usuario = Depends(get_usuario_atual),
    db: Session = Depends(get_db)
):
    if usuario_atual.role != RoleUsuario.SUPER_ADMIN and usuario_atual.tenant_id != tenant_id:
        raise HTTPException(403, "Sem permissão")
    hash_dup = gerar_hash_duplicata(dados.get("fornecedor_id", ""), dados.get("valor", 0),
                                    dados.get("data_vencimento", ""), condominio_id)
    lancamento = Lancamento(
        tenant_id=tenant_id, condominio_id=condominio_id,
        tipo=dados["tipo"], descricao=dados["descricao"],
        valor=dados["valor"], data_vencimento=dados["data_vencimento"],
        mes_referencia=dados.get("mes_referencia"),
        fornecedor_id=dados.get("fornecedor_id"),
        codigo_barras=dados.get("codigo_barras"),
        tipo_codigo_barras=dados.get("tipo_codigo_barras", "boleto"),
        numero_parcela=dados.get("numero_parcela"),
        total_parcelas=dados.get("total_parcelas"),
        parcela_pai_id=dados.get("parcela_pai_id"),
        hash_duplicata=hash_dup, observacoes=dados.get("observacoes"),
    )
    db.add(lancamento)
    db.commit()
    db.refresh(lancamento)
    return {"id": lancamento.id, "descricao": lancamento.descricao}


# ─── Dashboard endpoints ──────────────────────────────────────────────────────

@app.get("/dashboard/super-admin")
async def dashboard_super_admin(
    usuario_atual: Usuario = Depends(requer_super_admin),
    db: Session = Depends(get_db)
):
    """Dashboard do Super Admin — visão macro do negócio."""
    from sqlalchemy import func
    from .models.transacao import StatusConciliacao

    tenants = db.query(Tenant).filter(Tenant.ativo == True).all()
    total_condominios = db.query(Condominio).filter(Condominio.ativo == True).count()
    total_usuarios = db.query(Usuario).filter(Usuario.ativo == True).count()
    total_pendentes = db.query(Transacao).filter(
        Transacao.status_conciliacao == StatusConciliacao.PENDENTE
    ).count()

    # Dados por tenant
    tenants_data = []
    for t in tenants:
        n_condos = db.query(Condominio).filter(
            Condominio.tenant_id == t.id, Condominio.ativo == True
        ).count()
        n_contas = db.query(ContaBancaria).filter(
            ContaBancaria.tenant_id == t.id, ContaBancaria.ativa == True
        ).count()
        contas_desconectadas = db.query(ContaBancaria).filter(
            ContaBancaria.tenant_id == t.id,
            ContaBancaria.pluggy_status != "UPDATED",
            ContaBancaria.pluggy_item_id != None
        ).count()
        tenants_data.append({
            "id": t.id,
            "nome": t.nome,
            "cnpj": t.cnpj,
            "n_condominios": n_condos,
            "n_contas": n_contas,
            "contas_desconectadas": contas_desconectadas,
            "ativo": t.ativo
        })

    # Ordena por número de condomínios
    tenants_data.sort(key=lambda x: x["n_condominios"], reverse=True)

    return {
        "metricas": {
            "total_administradoras": len(tenants),
            "total_condominios": total_condominios,
            "total_usuarios": total_usuarios,
            "total_pendentes_conciliacao": total_pendentes,
        },
        "administradoras": tenants_data,
        "alertas": [
            t for t in tenants_data if t["contas_desconectadas"] > 0
        ]
    }


@app.get("/tenants/{tenant_id}/dashboard")
async def dashboard_administradora(
    tenant_id: str,
    usuario_atual: Usuario = Depends(get_usuario_atual),
    db: Session = Depends(get_db)
):
    """Dashboard da Administradora — visão operacional."""
    from .models.transacao import StatusConciliacao

    if usuario_atual.role != "super_admin" and usuario_atual.tenant_id != tenant_id:
        raise HTTPException(403, "Sem permissão")

    condominios = db.query(Condominio).filter(
        Condominio.tenant_id == tenant_id, Condominio.ativo == True
    ).all()

    total_unidades = sum(c.total_unidades for c in condominios)

    contas = db.query(ContaBancaria).filter(
        ContaBancaria.tenant_id == tenant_id, ContaBancaria.ativa == True
    ).all()

    total_saldo = sum(float(c.saldo_atual) for c in contas if c.saldo_atual)

    pendentes = db.query(Transacao).filter(
        Transacao.tenant_id == tenant_id,
        Transacao.status_conciliacao == StatusConciliacao.PENDENTE
    ).count()

    usuarios = db.query(Usuario).filter(
        Usuario.tenant_id == tenant_id, Usuario.ativo == True
    ).count()

    # Dados por condomínio
    condominios_data = []
    for c in condominios:
        contas_c = db.query(ContaBancaria).filter(
            ContaBancaria.condominio_id == c.id
        ).all()
        saldo_c = sum(float(ct.saldo_atual) for ct in contas_c if ct.saldo_atual)
        pend_c = db.query(Transacao).filter(
            Transacao.condominio_id == c.id,
            Transacao.status_conciliacao == StatusConciliacao.PENDENTE
        ).count()
        contas_desc = sum(1 for ct in contas_c if ct.pluggy_status not in ["UPDATED", None])
        condominios_data.append({
            "id": c.id,
            "nome": c.nome,
            "cidade": c.cidade,
            "estado": c.estado,
            "total_unidades": c.total_unidades,
            "saldo": saldo_c,
            "pendentes_conciliacao": pend_c,
            "contas_desconectadas": contas_desc,
        })

    return {
        "metricas": {
            "total_condominios": len(condominios),
            "total_unidades": total_unidades,
            "total_saldo": total_saldo,
            "pendentes_conciliacao": pendentes,
            "total_usuarios": usuarios,
            "total_contas": len(contas),
        },
        "condominios": condominios_data,
        "alertas": {
            "contas_desconectadas": sum(1 for ct in contas if ct.pluggy_status not in ["UPDATED", None] and ct.pluggy_item_id),
            "pendentes_conciliacao": pendentes,
        }
    }


@app.get("/tenants/{tenant_id}/condominios/{condominio_id}/dashboard")
async def dashboard_condominio(
    tenant_id: str,
    condominio_id: str,
    usuario_atual: Usuario = Depends(get_usuario_atual),
    db: Session = Depends(get_db)
):
    """Dashboard do Condomínio — visão financeira detalhada."""
    from datetime import date
    from .models.transacao import StatusConciliacao, TipoTransacao
    from .models.lancamento import LancamentoStatus

    if usuario_atual.role != "super_admin" and usuario_atual.tenant_id != tenant_id:
        raise HTTPException(403, "Sem permissão")

    condo = db.query(Condominio).filter(
        Condominio.id == condominio_id,
        Condominio.tenant_id == tenant_id
    ).first()
    if not condo:
        raise HTTPException(404, "Condomínio não encontrado")

    contas = db.query(ContaBancaria).filter(
        ContaBancaria.condominio_id == condominio_id
    ).all()
    saldo_total = sum(float(c.saldo_atual) for c in contas if c.saldo_atual)

    # Transações do mês
    hoje = date.today()
    inicio_mes = hoje.replace(day=1)

    from sqlalchemy import and_
    from datetime import datetime

    trans_mes_credito = db.query(Transacao).filter(
        Transacao.condominio_id == condominio_id,
        Transacao.tipo == TipoTransacao.CREDITO,
        Transacao.data >= datetime.combine(inicio_mes, datetime.min.time())
    ).all()
    trans_mes_debito = db.query(Transacao).filter(
        Transacao.condominio_id == condominio_id,
        Transacao.tipo == TipoTransacao.DEBITO,
        Transacao.data >= datetime.combine(inicio_mes, datetime.min.time())
    ).all()

    receita_mes = sum(float(t.valor) for t in trans_mes_credito)
    despesa_mes = sum(float(t.valor) for t in trans_mes_debito)

    # Lançamentos pendentes próximos 30 dias
    from datetime import timedelta
    prox_30 = hoje + timedelta(days=30)
    prox_venc = db.query(Lancamento).filter(
        Lancamento.condominio_id == condominio_id,
        Lancamento.status == LancamentoStatus.ABERTO,
        Lancamento.data_vencimento <= prox_30,
        Lancamento.data_vencimento >= hoje
    ).order_by(Lancamento.data_vencimento).limit(10).all()

    # Últimas transações conciliadas
    ultimas_trans = db.query(Transacao).filter(
        Transacao.condominio_id == condominio_id
    ).order_by(Transacao.data.desc()).limit(8).all()

    # Pendentes
    pendentes = db.query(Transacao).filter(
        Transacao.condominio_id == condominio_id,
        Transacao.status_conciliacao == StatusConciliacao.PENDENTE
    ).count()
    conciliadas = db.query(Transacao).filter(
        Transacao.condominio_id == condominio_id,
        Transacao.status_conciliacao == StatusConciliacao.CONCILIADA
    ).count()

    return {
        "condominio": {
            "id": condo.id,
            "nome": condo.nome,
            "cidade": condo.cidade,
            "estado": condo.estado,
            "total_unidades": condo.total_unidades,
        },
        "metricas": {
            "saldo_total": saldo_total,
            "receita_mes": receita_mes,
            "despesa_mes": despesa_mes,
            "saldo_mes": receita_mes - despesa_mes,
            "total_contas": len(contas),
            "pendentes_conciliacao": pendentes,
            "conciliadas": conciliadas,
        },
        "proximos_vencimentos": [
            {
                "descricao": l.descricao,
                "valor": float(l.valor),
                "data_vencimento": str(l.data_vencimento),
                "tipo": l.tipo,
                "parcela": f"{l.numero_parcela}/{l.total_parcelas}" if l.total_parcelas else None,
            } for l in prox_venc
        ],
        "ultimas_transacoes": [
            {
                "data": t.data.strftime("%d/%m"),
                "descricao": t.descricao[:40],
                "valor": float(t.valor),
                "tipo": t.tipo,
                "status": t.status_conciliacao,
            } for t in ultimas_trans
        ],
        "alertas": {
            "saldo_baixo": saldo_total < 10000,
            "pendentes_altos": pendentes > 5,
        }
    }


# ─── CNPJ + Geocode ───────────────────────────────────────────────────────────

@app.get("/cnpj/{cnpj}")
async def consultar_cnpj(
    cnpj: str,
    _: Usuario = Depends(get_usuario_atual)
):
    """Consulta dados da empresa na Receita Federal via BrasilAPI."""
    cnpj_limpo = ''.join(c for c in cnpj if c.isdigit())
    if len(cnpj_limpo) != 14:
        raise HTTPException(400, "CNPJ inválido")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"https://brasilapi.com.br/api/cnpj/v1/{cnpj_limpo}")
            if r.status_code != 200:
                raise HTTPException(404, "CNPJ não encontrado")
            d = r.json()
            return {
                "nome": d.get("razao_social", ""),
                "fantasia": d.get("nome_fantasia", ""),
                "cnpj": cnpj_limpo,
                "email": d.get("email", ""),
                "telefone": d.get("ddd_telefone_1", ""),
                "cep": d.get("cep", ""),
                "logradouro": d.get("logradouro", ""),
                "numero": d.get("numero", ""),
                "complemento": d.get("complemento", ""),
                "bairro": d.get("bairro", ""),
                "municipio": d.get("municipio", ""),
                "uf": d.get("uf", ""),
                "endereco_completo": f"{d.get('logradouro','')} {d.get('numero','')}, {d.get('bairro','')}, {d.get('municipio','')}/{d.get('uf','')} - CEP {d.get('cep','')}"
            }
    except httpx.TimeoutException:
        raise HTTPException(504, "Timeout ao consultar CNPJ")


@app.get("/geocode")
async def geocodificar(
    endereco: str,
    _: Usuario = Depends(get_usuario_atual)
):
    """Converte endereço em lat/lng via OpenStreetMap Nominatim."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                "https://nominatim.openstreetmap.org/search",
                params={"q": endereco, "format": "json", "limit": 1, "countrycodes": "br"},
                headers={"User-Agent": "Condofy/1.0"}
            )
            results = r.json()
            if not results:
                return {"lat": None, "lng": None, "found": False}
            return {
                "lat": float(results[0]["lat"]),
                "lng": float(results[0]["lon"]),
                "display": results[0].get("display_name", ""),
                "found": True
            }
    except Exception as e:
        return {"lat": None, "lng": None, "found": False, "error": str(e)}


@app.patch("/tenants/{tenant_id}/endereco")
async def atualizar_endereco_tenant(
    tenant_id: str,
    dados: dict,
    usuario_atual: Usuario = Depends(get_usuario_atual),
    db: Session = Depends(get_db)
):
    """Atualiza endereço e coordenadas de um tenant."""
    if usuario_atual.role != "super_admin" and usuario_atual.tenant_id != tenant_id:
        raise HTTPException(403, "Sem permissão")
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(404, "Tenant não encontrado")
    for campo in ["endereco", "cidade", "estado", "cep", "lat", "lng"]:
        if campo in dados:
            setattr(tenant, campo, dados[campo])
    db.commit()
    return {"ok": True}


@app.patch("/tenants/{tenant_id}/condominios/{condominio_id}/endereco")
async def atualizar_endereco_condo(
    tenant_id: str,
    condominio_id: str,
    dados: dict,
    usuario_atual: Usuario = Depends(get_usuario_atual),
    db: Session = Depends(get_db)
):
    """Atualiza endereço e coordenadas de um condomínio."""
    if usuario_atual.role != "super_admin" and usuario_atual.tenant_id != tenant_id:
        raise HTTPException(403, "Sem permissão")
    condo = db.query(Condominio).filter(
        Condominio.id == condominio_id,
        Condominio.tenant_id == tenant_id
    ).first()
    if not condo:
        raise HTTPException(404, "Condomínio não encontrado")
    for campo in ["endereco", "cidade", "estado", "cep", "lat", "lng"]:
        if campo in dados:
            setattr(condo, campo, dados[campo])
    db.commit()
    return {"ok": True}
