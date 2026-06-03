import uuid
from sqlalchemy import String, Boolean, Numeric, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base, TimestampMixin
from datetime import datetime


class ContaBancaria(Base, TimestampMixin):
    """
    Conta bancária de um condomínio.
    Conectada via Pluggy (item_id) ou cadastrada manualmente.
    """
    __tablename__ = "contas_bancarias"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    # Isolamento — sempre filtrar por tenant_id + condominio_id
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id"), nullable=False, index=True
    )
    condominio_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("condominios.id", ondelete="CASCADE"),
        nullable=False, index=True
    )

    # Dados bancários
    banco_nome: Mapped[str] = mapped_column(String(100), nullable=False)
    banco_codigo: Mapped[str] = mapped_column(String(10), nullable=True)
    agencia: Mapped[str] = mapped_column(String(10), nullable=True)
    conta: Mapped[str] = mapped_column(String(20), nullable=True)
    tipo: Mapped[str] = mapped_column(String(30), default="corrente")  # corrente, poupanca, pool

    # Integração Pluggy
    pluggy_item_id: Mapped[str] = mapped_column(String(100), nullable=True, unique=True)
    pluggy_account_id: Mapped[str] = mapped_column(String(100), nullable=True)
    pluggy_status: Mapped[str] = mapped_column(String(30), nullable=True)  # UPDATED, UPDATING, OUTDATED, LOGIN_ERROR

    # Saldo e sync
    saldo_atual: Mapped[float] = mapped_column(Numeric(15, 2), nullable=True)
    ultima_sync: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    ativa: Mapped[bool] = mapped_column(Boolean, default=True)

    # Relacionamentos
    condominio: Mapped["Condominio"] = relationship(
        "Condominio", back_populates="contas_bancarias"
    )
    transacoes: Mapped[list["Transacao"]] = relationship(
        "Transacao", back_populates="conta_bancaria", cascade="all, delete-orphan"
    )
    remessas: Mapped[list["Remessa"]] = relationship(
        "Remessa", back_populates="conta_bancaria"
    )
