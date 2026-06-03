import uuid
from enum import Enum as PyEnum
from sqlalchemy import String, Numeric, DateTime, Date, ForeignKey, Boolean, Text, Enum, Integer, event
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base, TimestampMixin
from datetime import datetime, date


class TipoLancamento(str, PyEnum):
    RECEITA = "receita"
    DESPESA = "despesa"
    TRANSFERENCIA = "transferencia"
    IMPOSTO = "imposto"   # DARF, DAS, FGTS — suporte explícito ao problema #9


class LancamentoStatus(str, PyEnum):
    ABERTO = "aberto"
    PAGO = "pago"
    CANCELADO = "cancelado"
    VENCIDO = "vencido"


class TipoCodigoBarras(str, PyEnum):
    BOLETO = "boleto"
    DARF = "darf"
    DAS = "das"
    FGTS = "fgts"
    GPS = "gps"
    OUTROS = "outros"


class Lancamento(Base, TimestampMixin):
    """
    Lançamento financeiro (receita ou despesa) de um condomínio.

    REGRAS IMPLEMENTADAS:
    - Detecção de duplicatas: antes de inserir, checar fornecedor+valor+vencimento (problema #26)
    - Parcelamento: lancamentos filhos linkados via parcela_pai_id (problema #12 melhorias)
    - Tipos de código de barras: suporte a DARF/DAS/FGTS (problema #9)
    - Status granular: nunca bloquear edição de lançamento rejeitado (problema #12)
    """
    __tablename__ = "lancamentos"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    # Isolamento obrigatório
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id"), nullable=False, index=True
    )
    condominio_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("condominios.id", ondelete="CASCADE"),
        nullable=False, index=True
    )

    # Classificação
    tipo: Mapped[TipoLancamento] = mapped_column(Enum(TipoLancamento), nullable=False, index=True)
    status: Mapped[LancamentoStatus] = mapped_column(
        Enum(LancamentoStatus), default=LancamentoStatus.ABERTO, index=True
    )
    descricao: Mapped[str] = mapped_column(String(300), nullable=False)
    valor: Mapped[float] = mapped_column(Numeric(15, 2), nullable=False)

    # Datas
    data_vencimento: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    data_pagamento: Mapped[date] = mapped_column(Date, nullable=True)
    mes_referencia: Mapped[str] = mapped_column(String(7), nullable=True, index=True)  # "2025-06"

    # Fornecedor / sacado
    fornecedor_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("fornecedores.id"), nullable=True, index=True
    )
    sacado_preferencia: Mapped[str] = mapped_column(
        String(20), default="proprietario"  # proprietario, inquilino, responsavel — problema #3 melhorias
    )

    # Código de barras — suporte a múltiplos tipos (problema #9)
    codigo_barras: Mapped[str] = mapped_column(String(100), nullable=True)
    tipo_codigo_barras: Mapped[TipoCodigoBarras] = mapped_column(
        Enum(TipoCodigoBarras), default=TipoCodigoBarras.BOLETO, nullable=True
    )

    # Parcelamento — problema #12 melhorias
    parcela_pai_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("lancamentos.id"), nullable=True, index=True
    )
    numero_parcela: Mapped[int] = mapped_column(Integer, nullable=True)   # ex: 2
    total_parcelas: Mapped[int] = mapped_column(Integer, nullable=True)   # ex: 4

    # Controle de duplicatas — problema #26
    # Hash para detectar duplicatas: sha256(fornecedor_id + valor + vencimento + condominio_id)
    hash_duplicata: Mapped[str] = mapped_column(String(64), nullable=True, index=True)

    # Conta bancária associada
    conta_bancaria_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("contas_bancarias.id"), nullable=True
    )

    observacoes: Mapped[str] = mapped_column(Text, nullable=True)

    # Relacionamentos
    condominio: Mapped["Condominio"] = relationship(
        "Condominio", back_populates="lancamentos"
    )
    fornecedor: Mapped["Fornecedor"] = relationship(
        "Fornecedor", back_populates="lancamentos"
    )
    transacoes: Mapped[list["Transacao"]] = relationship(
        "Transacao", back_populates="lancamento"
    )
    parcelas: Mapped[list["Lancamento"]] = relationship(
        "Lancamento",
        foreign_keys=[parcela_pai_id],
        back_populates="parcela_pai"
    )
    parcela_pai: Mapped["Lancamento"] = relationship(
        "Lancamento",
        foreign_keys=[parcela_pai_id],
        back_populates="parcelas",
        remote_side="Lancamento.id"
    )


class LancamentoParcelaView:
    """
    Helper para exibir progresso de parcelamento.
    Resolve problema #12 melhorias: 'lancei seguro por 4 meses,
    outro atendente consegue ver 2/4 sem ir mês a mês'
    """
    @staticmethod
    def descricao_parcela(lancamento: Lancamento) -> str:
        if lancamento.total_parcelas and lancamento.total_parcelas > 1:
            return f"{lancamento.descricao} ({lancamento.numero_parcela}/{lancamento.total_parcelas})"
        return lancamento.descricao
