"""
Condofy API — Backend principal
FastAPI + PostgreSQL + Pluggy Open Finance
"""

from fastapi import FastAPI, Depends, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from contextlib import asynccontextmanager
import os

from .models.base import Base
from .models import (
    Tenant, Condominio, ContaBancaria, Transacao,
    Lancamento, Remessa, Boleto, Fornecedor, Morador, Unidade
)
from .services.conciliacao_service import conciliar_automatico, verificar_duplicata
from .services.pluggy_service import get_pluggy_service


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
    yield


app = FastAPI(
    title="Condofy API",
    description="ERP para administradoras de condomínios",
    version="0.1.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # ajustar para domínio real em produção
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Health ───────────────────────────────────────────────────────────────────

@app.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok", "service": "condofy-api", "version": "0.1.0"}


# ─── Tenants ──────────────────────────────────────────────────────────────────

@app.post("/tenants", status_code=201)
def criar_tenant(dados: dict, db: Session = Depends(get_db)):
    """Cadastra nova administradora."""
    tenant = Tenant(
        nome=dados["nome"],
        cnpj=dados["cnpj"],
        email=dados["email"],
        telefone=dados.get("telefone"),
        pluggy_client_id=dados.get("pluggy_client_id"),
        pluggy_client_secret=dados.get("pluggy_client_secret"),
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    return {"id": tenant.id, "nome": tenant.nome, "cnpj": tenant.cnpj}


@app.get("/tenants/{tenant_id}")
def buscar_tenant(tenant_id: str, db: Session = Depends(get_db)):
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(404, "Tenant não encontrado")
    return {
        "id": tenant.id,
        "nome": tenant.nome,
        "cnpj": tenant.cnpj,
        "plano": tenant.plano,
        "ativo": tenant.ativo
    }


# ─── Condomínios ──────────────────────────────────────────────────────────────

@app.get("/tenants/{tenant_id}/condominios")
def listar_condominios(tenant_id: str, db: Session = Depends(get_db)):
    """
    SEMPRE filtra por tenant_id. Nunca retorna condomínios de outro tenant.
    """
    condominios = db.query(Condominio).filter(
        Condominio.tenant_id == tenant_id,
        Condominio.ativo == True
    ).all()
    return [
        {
            "id": c.id,
            "nome": c.nome,
            "cnpj": c.cnpj,
            "cidade": c.cidade,
            "estado": c.estado,
            "total_unidades": c.total_unidades,
        }
        for c in condominios
    ]


@app.post("/tenants/{tenant_id}/condominios", status_code=201)
def criar_condominio(tenant_id: str, dados: dict, db: Session = Depends(get_db)):
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(404, "Tenant não encontrado")

    # Verifica limite do plano
    total = db.query(Condominio).filter(
        Condominio.tenant_id == tenant_id, Condominio.ativo == True
    ).count()
    if total >= tenant.max_condominios:
        raise HTTPException(402, f"Limite de {tenant.max_condominios} condomínios atingido. Atualize o plano.")

    condo = Condominio(
        tenant_id=tenant_id,
        nome=dados["nome"],
        cnpj=dados.get("cnpj"),
        endereco=dados.get("endereco"),
        cidade=dados.get("cidade"),
        estado=dados.get("estado"),
        total_unidades=dados.get("total_unidades", 0),
    )
    db.add(condo)
    db.commit()
    db.refresh(condo)
    return {"id": condo.id, "nome": condo.nome}


# ─── Contas Bancárias ─────────────────────────────────────────────────────────

@app.get("/tenants/{tenant_id}/condominios/{condominio_id}/contas")
def listar_contas(tenant_id: str, condominio_id: str, db: Session = Depends(get_db)):
    """Isolamento duplo: tenant + condomínio."""
    contas = db.query(ContaBancaria).filter(
        ContaBancaria.tenant_id == tenant_id,
        ContaBancaria.condominio_id == condominio_id,
        ContaBancaria.ativa == True
    ).all()
    return [
        {
            "id": c.id,
            "banco_nome": c.banco_nome,
            "agencia": c.agencia,
            "conta": c.conta,
            "saldo_atual": float(c.saldo_atual) if c.saldo_atual else None,
            "ultima_sync": c.ultima_sync.isoformat() if c.ultima_sync else None,
            "pluggy_status": c.pluggy_status,
        }
        for c in contas
    ]


# ─── Pluggy — Connect Token ───────────────────────────────────────────────────

@app.post("/tenants/{tenant_id}/pluggy/connect-token")
async def gerar_connect_token(tenant_id: str, dados: dict, db: Session = Depends(get_db)):
    """
    Gera token para abrir o Pluggy Connect Widget.
    O frontend usa este token para exibir o popup de conexão bancária.
    """
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(404, "Tenant não encontrado")

    pluggy = get_pluggy_service(tenant)
    webhook_url = os.getenv("PLUGGY_WEBHOOK_URL", f"https://api.condofy.com.br/webhooks/pluggy/{tenant_id}")

    token = await pluggy.criar_connect_token(
        webhook_url=webhook_url,
        client_user_id=dados.get("user_id", tenant_id)
    )
    return {"connect_token": token}


# ─── Pluggy — Webhook ─────────────────────────────────────────────────────────

@app.post("/webhooks/pluggy/{tenant_id}")
async def webhook_pluggy(tenant_id: str, request: Request, db: Session = Depends(get_db)):
    """
    Recebe notificações automáticas do Pluggy quando há novas transações.
    Dispara sincronização automática da conta afetada.
    """
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        return JSONResponse({"ok": False}, status_code=404)

    payload = await request.json()
    pluggy = get_pluggy_service(tenant)
    resultado = await pluggy.processar_webhook(db, payload)
    return {"ok": True, **resultado}


# ─── Sincronização Manual ─────────────────────────────────────────────────────

@app.post("/tenants/{tenant_id}/contas/{conta_id}/sync")
async def sincronizar_conta(tenant_id: str, conta_id: str, db: Session = Depends(get_db)):
    """Sincronização manual de uma conta bancária via Pluggy."""
    conta = db.query(ContaBancaria).filter(
        ContaBancaria.id == conta_id,
        ContaBancaria.tenant_id == tenant_id  # isolamento
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
    tenant_id: str,
    condominio_id: str,
    status: str | None = None,
    db: Session = Depends(get_db)
):
    """Lista transações do extrato com isolamento obrigatório."""
    query = db.query(Transacao).filter(
        Transacao.tenant_id == tenant_id,       # isolamento 1
        Transacao.condominio_id == condominio_id # isolamento 2
    )
    if status:
        query = query.filter(Transacao.status_conciliacao == status)

    transacoes = query.order_by(Transacao.data.desc()).limit(500).all()
    return [
        {
            "id": t.id,
            "data": t.data.isoformat(),
            "descricao": t.descricao,
            "valor": float(t.valor),
            "tipo": t.tipo,
            "status_conciliacao": t.status_conciliacao,
            "lancamento_id": t.lancamento_id,
        }
        for t in transacoes
    ]


@app.post("/tenants/{tenant_id}/condominios/{condominio_id}/conciliar")
def executar_conciliacao(
    tenant_id: str,
    condominio_id: str,
    dados: dict = {},
    db: Session = Depends(get_db)
):
    """Executa conciliação automática por score."""
    resultado = conciliar_automatico(
        db=db,
        tenant_id=tenant_id,
        condominio_id=condominio_id,
        conta_bancaria_id=dados.get("conta_bancaria_id"),
        mes_referencia=dados.get("mes_referencia")
    )
    return resultado


@app.patch("/tenants/{tenant_id}/transacoes/{transacao_id}/conciliar")
def conciliar_manual(
    tenant_id: str,
    transacao_id: str,
    dados: dict,
    db: Session = Depends(get_db)
):
    """Conciliação manual: vincula transação a um lançamento."""
    transacao = db.query(Transacao).filter(
        Transacao.id == transacao_id,
        Transacao.tenant_id == tenant_id  # isolamento
    ).first()
    if not transacao:
        raise HTTPException(404, "Transação não encontrada")

    from .models.transacao import StatusConciliacao
    from .models.lancamento import LancamentoStatus
    from datetime import datetime

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
    return {"ok": True, "transacao_id": transacao_id}


# ─── Lançamentos ──────────────────────────────────────────────────────────────

@app.post("/tenants/{tenant_id}/condominios/{condominio_id}/lancamentos/verificar-duplicata")
def verificar_lancamento_duplicado(
    tenant_id: str,
    condominio_id: str,
    dados: dict,
    db: Session = Depends(get_db)
):
    """
    Verifica duplicata ANTES de criar o lançamento.
    Frontend chama isso e mostra aviso se já existir. (problema #26)
    """
    return verificar_duplicata(
        db=db,
        tenant_id=tenant_id,
        condominio_id=condominio_id,
        fornecedor_id=dados["fornecedor_id"],
        valor=dados["valor"],
        data_vencimento=dados["data_vencimento"]
    )


@app.post("/tenants/{tenant_id}/condominios/{condominio_id}/lancamentos", status_code=201)
def criar_lancamento(
    tenant_id: str,
    condominio_id: str,
    dados: dict,
    db: Session = Depends(get_db)
):
    from .services.conciliacao_service import gerar_hash_duplicata

    hash_dup = gerar_hash_duplicata(
        dados.get("fornecedor_id", ""),
        dados.get("valor", 0),
        dados.get("data_vencimento", ""),
        condominio_id
    )

    lancamento = Lancamento(
        tenant_id=tenant_id,
        condominio_id=condominio_id,
        tipo=dados["tipo"],
        descricao=dados["descricao"],
        valor=dados["valor"],
        data_vencimento=dados["data_vencimento"],
        mes_referencia=dados.get("mes_referencia"),
        fornecedor_id=dados.get("fornecedor_id"),
        codigo_barras=dados.get("codigo_barras"),
        tipo_codigo_barras=dados.get("tipo_codigo_barras", "boleto"),
        numero_parcela=dados.get("numero_parcela"),
        total_parcelas=dados.get("total_parcelas"),
        parcela_pai_id=dados.get("parcela_pai_id"),
        hash_duplicata=hash_dup,
        observacoes=dados.get("observacoes"),
    )
    db.add(lancamento)
    db.commit()
    db.refresh(lancamento)
    return {"id": lancamento.id, "descricao": lancamento.descricao}
