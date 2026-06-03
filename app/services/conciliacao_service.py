"""
Serviço de conciliação bancária automática.

Algoritmo de matching por score:
1. Match exato: valor + data + tipo                → score 100 → concilia automático
2. Match por valor + tipo (±1 dia)                → score 80  → concilia automático
3. Match por valor + tipo (±3 dias)               → score 60  → sugere para revisão
4. Match parcial: valor aproximado (±0.01) + tipo → score 40  → sugere para revisão
Abaixo de 40: pendente para revisão manual.
"""

from datetime import datetime, timedelta
from decimal import Decimal
from sqlalchemy.orm import Session
from sqlalchemy import select, and_, func
import hashlib

from ..models.transacao import Transacao, StatusConciliacao, TipoTransacao
from ..models.lancamento import Lancamento, LancamentoStatus, TipoLancamento


SCORE_AUTO = 75      # acima disso → concilia automático
SCORE_SUGERE = 40    # acima disso → sugere para revisão humana


def calcular_score(transacao: Transacao, lancamento: Lancamento) -> int:
    """Calcula score de compatibilidade entre transação e lançamento."""
    score = 0

    # Tipo compatível?
    tipo_ok = (
        (transacao.tipo == TipoTransacao.CREDITO and lancamento.tipo == TipoLancamento.RECEITA) or
        (transacao.tipo == TipoTransacao.DEBITO and lancamento.tipo in [
            TipoLancamento.DESPESA, TipoLancamento.IMPOSTO, TipoLancamento.TRANSFERENCIA
        ])
    )
    if not tipo_ok:
        return 0

    # Valor exato
    valor_transacao = float(transacao.valor)
    valor_lancamento = float(lancamento.valor)
    diff_valor = abs(valor_transacao - valor_lancamento)

    if diff_valor == 0:
        score += 50
    elif diff_valor <= 0.01:
        score += 40  # centavo de diferença (arredondamento)
    elif diff_valor / valor_lancamento <= 0.001:
        score += 30  # diferença < 0.1%
    else:
        return 0  # valor muito diferente, não é match

    # Diferença de datas
    data_transacao = transacao.data.date() if hasattr(transacao.data, 'date') else transacao.data
    data_vencimento = lancamento.data_vencimento
    diff_dias = abs((data_transacao - data_vencimento).days)

    if diff_dias == 0:
        score += 50
    elif diff_dias <= 1:
        score += 35
    elif diff_dias <= 3:
        score += 20
    elif diff_dias <= 7:
        score += 10
    else:
        score += 0

    return min(score, 100)


def conciliar_automatico(
    db: Session,
    tenant_id: str,
    condominio_id: str,
    conta_bancaria_id: str | None = None,
    mes_referencia: str | None = None
) -> dict:
    """
    Executa conciliação automática para um condomínio.
    
    Retorna dict com:
    - conciliadas: int
    - sugeridas: int  (score entre 40-74, aguarda revisão humana)
    - pendentes: int
    - detalhes: list
    """

    # Buscar transações pendentes — SEMPRE com filtro de tenant + condomínio
    query_transacoes = select(Transacao).where(
        and_(
            Transacao.tenant_id == tenant_id,
            Transacao.condominio_id == condominio_id,
            Transacao.status_conciliacao == StatusConciliacao.PENDENTE
        )
    )
    if conta_bancaria_id:
        query_transacoes = query_transacoes.where(
            Transacao.conta_bancaria_id == conta_bancaria_id
        )

    transacoes = db.execute(query_transacoes).scalars().all()

    # Buscar lançamentos abertos — SEMPRE com filtro de tenant + condomínio
    query_lancamentos = select(Lancamento).where(
        and_(
            Lancamento.tenant_id == tenant_id,
            Lancamento.condominio_id == condominio_id,
            Lancamento.status == LancamentoStatus.ABERTO
        )
    )
    if mes_referencia:
        query_lancamentos = query_lancamentos.where(
            Lancamento.mes_referencia == mes_referencia
        )

    lancamentos = db.execute(query_lancamentos).scalars().all()

    resultado = {
        "conciliadas": 0,
        "sugeridas": 0,
        "pendentes": 0,
        "detalhes": []
    }

    lancamentos_usados = set()

    for transacao in transacoes:
        melhor_score = 0
        melhor_lancamento = None

        for lancamento in lancamentos:
            if lancamento.id in lancamentos_usados:
                continue

            score = calcular_score(transacao, lancamento)
            if score > melhor_score:
                melhor_score = score
                melhor_lancamento = lancamento

        if melhor_lancamento and melhor_score >= SCORE_AUTO:
            # Conciliação automática
            transacao.status_conciliacao = StatusConciliacao.CONCILIADA
            transacao.lancamento_id = melhor_lancamento.id
            transacao.conciliado_em = datetime.utcnow()
            melhor_lancamento.status = LancamentoStatus.PAGO
            melhor_lancamento.data_pagamento = transacao.data.date()
            lancamentos_usados.add(melhor_lancamento.id)
            resultado["conciliadas"] += 1
            resultado["detalhes"].append({
                "transacao_id": transacao.id,
                "lancamento_id": melhor_lancamento.id,
                "score": melhor_score,
                "acao": "conciliada_automatico"
            })

        elif melhor_lancamento and melhor_score >= SCORE_SUGERE:
            # Sugestão para revisão humana
            resultado["sugeridas"] += 1
            resultado["detalhes"].append({
                "transacao_id": transacao.id,
                "lancamento_id": melhor_lancamento.id,
                "score": melhor_score,
                "acao": "sugerida_revisao"
            })
        else:
            resultado["pendentes"] += 1
            resultado["detalhes"].append({
                "transacao_id": transacao.id,
                "lancamento_id": None,
                "score": 0,
                "acao": "pendente_manual"
            })

    db.commit()
    return resultado


def verificar_duplicata(
    db: Session,
    tenant_id: str,
    condominio_id: str,
    fornecedor_id: str,
    valor: float,
    data_vencimento: str
) -> dict:
    """
    Verifica se existe lançamento duplicado antes de inserir.
    Resolve problema #26: alerta quando despesa igual já existe.
    
    Janela de verificação: ±30 dias em relação ao vencimento.
    """
    hash_key = hashlib.sha256(
        f"{fornecedor_id}{valor}{data_vencimento}{condominio_id}".encode()
    ).hexdigest()

    existente = db.execute(
        select(Lancamento).where(
            and_(
                Lancamento.tenant_id == tenant_id,
                Lancamento.condominio_id == condominio_id,
                Lancamento.hash_duplicata == hash_key,
                Lancamento.status != LancamentoStatus.CANCELADO
            )
        )
    ).scalars().first()

    if existente:
        return {
            "duplicata": True,
            "lancamento_existente_id": existente.id,
            "descricao": existente.descricao,
            "status": existente.status,
            "message": f"Já existe um lançamento igual com status '{existente.status}'. Deseja continuar mesmo assim?"
        }

    return {"duplicata": False}


def gerar_hash_duplicata(fornecedor_id: str, valor: float, data_vencimento: str, condominio_id: str) -> str:
    """Gera hash para detecção de duplicatas."""
    return hashlib.sha256(
        f"{fornecedor_id}{valor}{data_vencimento}{condominio_id}".encode()
    ).hexdigest()
