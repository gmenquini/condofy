import uuid
from enum import Enum as PyEnum
from sqlalchemy import String, Numeric, DateTime, ForeignKey, Boolean, Text, Enum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base, TimestampMixin
from datetime import datetime


class TipoTransacao(str, PyEnum):
    CREDITO = "credito"
    DEBITO = "debito"


class StatusConciliacao(str, PyEnum):
    PENDENTE = "pendente"
    CONCILIADA = "conciliada"
    DIVERGENCIA = "divergencia"
    IGNORADA = "ignorada"


class Transacao(Base, TimestampMixin):
    """
    Transação do extrato bancário (origem: Pluggy ou importação manual).
    
    Cada transação pertence a uma conta, que pertence a um condomínio,
    que pertence a um tenant. Nunca expor sem filtrar toda a cadeia.
    """
    __tablename__ = "transacoes"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    # Isolamento
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id"), nullable=False, index=True
    )
    condominio_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("condominios.id"), nullable=False, index=True
    )
    conta_bancaria_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("contas_bancarias.id", ondelete="CASCADE"),
        nullable=False, index=True
    )

    # Dados da transação (vindos do Pluggy)
    pluggy_transaction_id: Mapped[str] = mapped_column(
        String(100), nullable=True, unique=True  # evita duplicatas do webhook
    )
    data: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    descricao: Mapped[str] = mapped_column(String(500), nullable=False)
    valor: Mapped[float] = mapped_column(Numeric(15, 2), nullable=False)
    tipo: Mapped[TipoTransacao] = mapped_column(
        Enum(TipoTransacao), nullable=False, index=True
    )
    categoria: Mapped[str] = mapped_column(String(100), nullable=True)  # categoria do Pluggy
    saldo_apos: Mapped[float] = mapped_column(Numeric(15, 2), nullable=True)

    # Conciliação
    status_conciliacao: Mapped[StatusConciliacao] = mapped_column(
        Enum(StatusConciliacao), default=StatusConciliacao.PENDENTE, index=True
    )
    lancamento_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("lancamentos.id"), nullable=True
    )
    conciliado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    conciliado_por: Mapped[str] = mapped_column(String(36), nullable=True)  # usuario_id
    observacao_conciliacao: Mapped[str] = mapped_column(Text, nullable=True)

    # Relacionamentos
    conta_bancaria: Mapped["ContaBancaria"] = relationship(
        "ContaBancaria", back_populates="transacoes"
    )
    lancamento: Mapped["Lancamento"] = relationship(
        "Lancamento", back_populates="transacoes"
    )
