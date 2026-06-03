"""
Script de dados demo para D One Finance.
Popula o banco com dados realistas para testar todos os módulos.
"""
from sqlalchemy.orm import Session
from sqlalchemy import select
from datetime import datetime, date, timedelta
import random
import hashlib

from ..models.tenant import Tenant
from ..models.condominio import Condominio
from ..models.conta_bancaria import ContaBancaria
from ..models.transacao import Transacao, TipoTransacao, StatusConciliacao
from ..models.lancamento import Lancamento, LancamentoStatus, TipoLancamento, TipoCodigoBarras
from ..models.boleto import Boleto, BoletoStatus
from ..models.morador import Fornecedor, Unidade, Morador
from ..models.usuario import Usuario, RoleUsuario
from ..models.remessa import Remessa, RemessaItem, RemessaStatus, RemessaItemStatus
from .auth_service import hash_senha


def seed_demo(db: Session):
    """Cria dados demo completos se ainda não existirem."""

    # Verifica se já existe demo
    if db.execute(select(Tenant).where(Tenant.cnpj == "11.111.111/0001-11")).scalars().first():
        print("Demo já existe, pulando...")
        return

    print("Criando dados demo...")

    # ── TENANT 1: Administradora Silva ──────────────────────────────────────
    t1 = Tenant(
        nome="Administradora Silva Ltda",
        cnpj="11.111.111/0001-11",
        email="contato@silva.com.br",
        cidade="São Paulo", estado="SP",
        endereco="Av. Paulista, 1000, Bela Vista",
        cep="01310-100",
        lat=-23.5614, lng=-46.6561,
        pluggy_client_id="95a6b27b-3d9f-4bd7-9634-3d5ed1708699",
        pluggy_client_secret="0e5e33e2-81c9-45e5-bac6-badf5781238a",
    )
    db.add(t1)
    db.flush()

    # Usuários da Adm. Silva
    u_admin1 = Usuario(nome="Carlos Silva", email="carlos@silva.com.br",
        senha_hash=hash_senha("Silva@2026!"), role=RoleUsuario.ADMIN_TENANT, tenant_id=t1.id)
    u_ger1 = Usuario(nome="Ana Gerente", email="ana@silva.com.br",
        senha_hash=hash_senha("Ana@2026!"), role=RoleUsuario.GERENTE, tenant_id=t1.id)
    u_op1 = Usuario(nome="Pedro Operador", email="pedro@silva.com.br",
        senha_hash=hash_senha("Pedro@2026!"), role=RoleUsuario.OPERADOR, tenant_id=t1.id)
    db.add_all([u_admin1, u_ger1, u_op1])

    # ── TENANT 2: Gestão Condominial SP ─────────────────────────────────────
    t2 = Tenant(
        nome="Gestão Condominial SP",
        cnpj="22.222.222/0001-22",
        email="contato@gestaocondsp.com.br",
        cidade="Campinas", estado="SP",
        endereco="Rua Barão de Jaguara, 500, Centro",
        cep="13010-050",
        lat=-22.9056, lng=-47.0608,
        pluggy_client_id="95a6b27b-3d9f-4bd7-9634-3d5ed1708699",
        pluggy_client_secret="0e5e33e2-81c9-45e5-bac6-badf5781238a",
    )
    db.add(t2)
    db.flush()

    u_admin2 = Usuario(nome="Maria Gestão", email="maria@gestaocondsp.com.br",
        senha_hash=hash_senha("Maria@2026!"), role=RoleUsuario.ADMIN_TENANT, tenant_id=t2.id)
    db.add(u_admin2)

    # ── CONDOMÍNIOS (Adm. Silva) ─────────────────────────────────────────────
    condos_data = [
        ("Residencial das Flores", "11.111.222/0001-33", "São Paulo", "SP", 48, -23.5489, -46.6388, "Rua das Flores, 100"),
        ("Ed. Panorama", "11.111.333/0001-44", "Campinas", "SP", 120, -22.9099, -47.0626, "Av. das Palmeiras, 200"),
        ("Cond. Solar", "11.111.444/0001-55", "Santos", "SP", 64, -23.9608, -46.3331, "Rua da Praia, 300"),
        ("Torre Azul", "11.111.555/0001-66", "São Paulo", "SP", 88, -23.5505, -46.6333, "Av. Paulista, 2000"),
        ("Park Place", "11.111.666/0001-77", "Guarulhos", "SP", 96, -23.4629, -46.5333, "Rua das Acácias, 50"),
    ]

    condos = []
    for nome, cnpj, cidade, estado, unidades, lat, lng, end in condos_data:
        c = Condominio(tenant_id=t1.id, nome=nome, cnpj=cnpj, cidade=cidade,
            estado=estado, total_unidades=unidades, lat=lat, lng=lng, endereco=end)
        db.add(c)
        condos.append(c)
    db.flush()

    # ── CONDOMÍNIOS (Gestão SP) ──────────────────────────────────────────────
    c_gsp = Condominio(tenant_id=t2.id, nome="Villa Verde", cnpj="22.222.333/0001-11",
        cidade="Campinas", estado="SP", total_unidades=72, lat=-22.8978, lng=-47.0456,
        endereco="Rua Verde, 400")
    db.add(c_gsp)
    db.flush()

    # ── CONTAS BANCÁRIAS ─────────────────────────────────────────────────────
    bancos = [
        ("Bradesco", "0237", "12345-6", 48320.00, "UPDATED"),
        ("Itaú", "0341", "78901-2", 122850.00, "UPDATED"),
        ("Banco do Brasil", "0001", "34567-8", 15200.00, "OUTDATED"),
        ("Santander", "0033", "56789-0", 67400.00, "UPDATED"),
        ("Sicoob", "0756", "90123-4", 31800.00, "UPDATED"),
    ]

    contas = []
    for i, (banco, ag, conta, saldo, status) in enumerate(bancos):
        ct = ContaBancaria(
            tenant_id=t1.id, condominio_id=condos[i].id,
            banco_nome=banco, agencia=ag, conta=conta,
            saldo_atual=saldo, pluggy_status=status,
            ultima_sync=datetime.utcnow() - timedelta(hours=random.randint(1, 48))
        )
        db.add(ct)
        contas.append(ct)
    db.flush()

    # ── UNIDADES E MORADORES ─────────────────────────────────────────────────
    sindico_condo = condos[0]  # Res. das Flores
    for bloco in ['A', 'B']:
        for num in range(1, 13):
            unid = Unidade(tenant_id=t1.id, condominio_id=condos[0].id,
                identificacao=f"{bloco}-{num:02d}", bloco=bloco)
            db.add(unid)
    db.flush()

    # Pega primeira unidade para síndico e morador
    unidades = db.execute(select(Unidade).where(Unidade.condominio_id == condos[0].id).limit(3)).scalars().all()
    if unidades:
        morador_sindico = Morador(tenant_id=t1.id, unidade_id=unidades[0].id,
            nome="João Síndico", cpf="111.111.111-11", email="joao.sindico@email.com",
            tipo="proprietario")
        morador1 = Morador(tenant_id=t1.id, unidade_id=unidades[1].id,
            nome="Maria Condômina", cpf="222.222.222-22", email="maria@email.com",
            tipo="proprietario")
        db.add_all([morador_sindico, morador1])
        db.flush()

        # Usuário síndico vinculado ao condomínio
        u_sind = Usuario(nome="João Síndico", email="sindico@flores.com.br",
            senha_hash=hash_senha("Sindico@2026!"), role=RoleUsuario.SINDICO,
            tenant_id=t1.id, condominio_id=sindico_condo.id)
        u_mor = Usuario(nome="Maria Condômina", email="maria@flores.com.br",
            senha_hash=hash_senha("Maria@2026!"), role=RoleUsuario.MORADOR,
            tenant_id=t1.id, condominio_id=sindico_condo.id)
        db.add_all([u_sind, u_mor])

    # ── FORNECEDORES ─────────────────────────────────────────────────────────
    forns_data = [
        ("Clean Masters Ltda", "33.333.111/0001-11", "João Lima", "Rua A, 100", "São Paulo", "SP"),
        ("Elevadores Tech", "33.333.222/0001-22", "Pedro Tech", "Rua B, 200", "São Paulo", "SP"),
        ("Seguros Prediais", "33.333.333/0001-33", "Ana Seguros", "Rua C, 300", "São Paulo", "SP"),
        ("Portaria Segura", "33.333.444/0001-44", "Carlos Port.", "Rua D, 400", "São Paulo", "SP"),
    ]
    forns = []
    for nome, doc, tit, end, cid, est in forns_data:
        f = Fornecedor(tenant_id=t1.id, condominio_id=condos[0].id,
            nome=nome, documento=doc, titular=tit,
            endereco=end, cidade=cid, estado=est)
        db.add(f)
        forns.append(f)
    db.flush()

    # ── LANÇAMENTOS ──────────────────────────────────────────────────────────
    hoje = date.today()
    mes = hoje.strftime("%Y-%m")

    lanc_data = [
        # (desc, valor, tipo, dias_venc, fornecedor_idx)
        ("Taxa condominial Apto A-01", 850.00, TipoLancamento.RECEITA, 0, None),
        ("Taxa condominial Apto A-02", 850.00, TipoLancamento.RECEITA, 0, None),
        ("Taxa condominial Apto A-03", 850.00, TipoLancamento.RECEITA, 0, None),
        ("Taxa condominial Apto B-01", 850.00, TipoLancamento.RECEITA, 0, None),
        ("Taxa condominial Apto B-02", 850.00, TipoLancamento.RECEITA, 0, None),
        ("Fundo de reserva", 2400.00, TipoLancamento.RECEITA, 0, None),
        ("Limpeza — Clean Masters", 3200.00, TipoLancamento.DESPESA, 5, 0),
        ("Manutenção elevador", 1800.00, TipoLancamento.DESPESA, 8, 1),
        ("Seguro predial — 1/4", 1500.00, TipoLancamento.DESPESA, 10, 2),
        ("Seguro predial — 2/4", 1500.00, TipoLancamento.DESPESA, 40, 2),
        ("Portaria terceirizada", 8400.00, TipoLancamento.DESPESA, 5, 3),
        ("Energia elétrica", 2840.00, TipoLancamento.DESPESA, 8, None),
        ("Água — SABESP", 1920.00, TipoLancamento.DESPESA, 15, None),
        ("Internet fibra", 299.00, TipoLancamento.DESPESA, 10, None),
        ("FGTS porteiro", 420.00, TipoLancamento.IMPOSTO, 7, None),
    ]

    lancamentos = []
    for desc, valor, tipo, dias, forn_idx in lanc_data:
        forn_id = forns[forn_idx].id if forn_idx is not None else None
        h = hashlib.sha256(f"{forn_id or ''}{valor}{str(hoje + timedelta(days=dias))}{condos[0].id}".encode()).hexdigest()
        l = Lancamento(
            tenant_id=t1.id, condominio_id=condos[0].id,
            tipo=tipo, descricao=desc, valor=valor,
            data_vencimento=hoje + timedelta(days=dias),
            mes_referencia=mes, fornecedor_id=forn_id,
            hash_duplicata=h,
            tipo_codigo_barras=TipoCodigoBarras.FGTS if tipo == TipoLancamento.IMPOSTO else TipoCodigoBarras.BOLETO,
            numero_parcela=int(desc[-3]) if "1/4" in desc or "2/4" in desc else None,
            total_parcelas=4 if "1/4" in desc or "2/4" in desc else None,
        )
        db.add(l)
        lancamentos.append(l)
    db.flush()

    # ── TRANSAÇÕES (simulando extrato bancário) ──────────────────────────────
    tx_data = [
        ("Taxa condominial Apto A-01", 850.00, TipoTransacao.CREDITO, -5, StatusConciliacao.CONCILIADA),
        ("Taxa condominial Apto A-02", 850.00, TipoTransacao.CREDITO, -5, StatusConciliacao.CONCILIADA),
        ("Taxa condominial Apto A-03", 850.00, TipoTransacao.CREDITO, -4, StatusConciliacao.CONCILIADA),
        ("Taxa condominial Apto B-01", 850.00, TipoTransacao.CREDITO, -3, StatusConciliacao.CONCILIADA),
        ("Taxa condominial Apto B-02", 850.00, TipoTransacao.CREDITO, -3, StatusConciliacao.PENDENTE),
        ("CLEAN MASTERS LTDA", 3200.00, TipoTransacao.DEBITO, -6, StatusConciliacao.CONCILIADA),
        ("CPFL ENERGIA", 2840.00, TipoTransacao.DEBITO, -4, StatusConciliacao.CONCILIADA),
        ("PORTARIA SOLUCOES", 8400.00, TipoTransacao.DEBITO, -5, StatusConciliacao.CONCILIADA),
        ("SABESP", 1920.00, TipoTransacao.DEBITO, -2, StatusConciliacao.PENDENTE),
        ("Pix recebido origem desconhecida", 450.00, TipoTransacao.CREDITO, -1, StatusConciliacao.PENDENTE),
        ("TED recebida", 200.00, TipoTransacao.CREDITO, -2, StatusConciliacao.PENDENTE),
        ("Fundo de reserva — transferência", 2400.00, TipoTransacao.CREDITO, -5, StatusConciliacao.CONCILIADA),
        ("Internet fibra", 299.00, TipoTransacao.DEBITO, -3, StatusConciliacao.CONCILIADA),
        ("Taxa condominial Apto A-04", 850.00, TipoTransacao.CREDITO, -1, StatusConciliacao.PENDENTE),
        ("Manutenção elevador — Elevadores Tech", 1800.00, TipoTransacao.DEBITO, -7, StatusConciliacao.CONCILIADA),
    ]

    for i, (desc, valor, tipo, dias, status) in enumerate(tx_data):
        t = Transacao(
            tenant_id=t1.id, condominio_id=condos[0].id,
            conta_bancaria_id=contas[0].id,
            pluggy_transaction_id=f"demo_tx_{i:04d}",
            data=datetime.utcnow() + timedelta(days=dias),
            descricao=desc, valor=valor, tipo=tipo,
            status_conciliacao=status,
            lancamento_id=lancamentos[i].id if status == StatusConciliacao.CONCILIADA and i < len(lancamentos) else None,
        )
        db.add(t)

    # Transações para outros condomínios
    for condo_idx in [1, 2, 3]:
        for j in range(5):
            t = Transacao(
                tenant_id=t1.id, condominio_id=condos[condo_idx].id,
                conta_bancaria_id=contas[condo_idx].id,
                pluggy_transaction_id=f"demo_tx_c{condo_idx}_{j:03d}",
                data=datetime.utcnow() - timedelta(days=j+1),
                descricao=f"Transação demo {j+1}",
                valor=random.uniform(500, 5000),
                tipo=TipoTransacao.CREDITO if j % 2 == 0 else TipoTransacao.DEBITO,
                status_conciliacao=StatusConciliacao.CONCILIADA if j < 3 else StatusConciliacao.PENDENTE,
            )
            db.add(t)

    db.commit()
    print("✓ Dados demo criados com sucesso!")
    print("\n  USUÁRIOS DE TESTE:")
    print("  Super Admin:   admin@condofy.com.br    / Condofy@2026!")
    print("  Admin Silva:   carlos@silva.com.br     / Silva@2026!")
    print("  Admin Gestão:  maria@gestaocondsp.com.br / Maria@2026!")
    print("  Gerente:       ana@silva.com.br        / Ana@2026!")
    print("  Operador:      pedro@silva.com.br      / Pedro@2026!")
    print("  Síndico:       sindico@flores.com.br   / Sindico@2026!")
    print("  Morador:       maria@flores.com.br     / Maria@2026!")
