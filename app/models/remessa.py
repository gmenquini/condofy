import uuid
from enum import Enum as PyEnum
from sqlalchemy import String, Numeric, DateTime, ForeignKey, Text, Enum, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base, TimestampMixin
from datetime import datetime


class RemessaStatus(str, PyEnum):
    """
    Status granular da remessa.
    
    PROBLEMA #12 resolvido: status REJEITADO permite edição e reenvio.
    Nunca forçar exclusão + recriação de lançamento.
    """
    GERADA = "gerada"           # arquivo gerado, ainda não enviado
    ENVIADA = "enviada"         # enviado ao banco, aguardando retorno
    PROCESSADA = "processada"   # banco confirmou todas as operações
    REJEITADA = "rejeitada"     # banco rejeitou — EDITÁVEL, pode reenviar
    PARCIAL = "parcial"         # algumas ok, algumas rejeitadas


class RemessaItemStatus(str, PyEnum):
    PENDENTE = "pendente"
    APROVADO = "aprovado"
    REJEITADO = "rejeitado"     # item rejeitado — editável


class Remessa(Base, TimestampMixin):
    """
    Arquivo de remessa bancária (CNAB 240/400).
    
    Fluxo: GERADA → ENVIADA → PROCESSADA (ou REJEITADA ou PARCIAL)
    Se REJEITADA: editar os itens com erro e gerar nova remessa.
    NUNCA bloquear edição. NUNCA exigir excluir e recriar. (problema #12)
    """
    __tablename__ = "remessas"

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
        String(36), ForeignKey("contas_bancarias.id"), nullable=False
    )

    status: Mapped[RemessaStatus] = mapped_column(
        Enum(RemessaStatus), default=RemessaStatus.GERADA, index=True
    )
    numero_sequencial: Mapped[int] = mapped_column(Integer, nullable=False)
    nome_arquivo: Mapped[str] = mapped_column(String(100), nullable=True)
    total_registros: Mapped[int] = mapped_column(Integer, default=0)
    total_aprovados: Mapped[int] = mapped_column(Integer, default=0)
    total_rejeitados: Mapped[int] = mapped_column(Integer, default=0)

    enviada_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    retorno_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    observacoes: Mapped[str] = mapped_column(Text, nullable=True)

    # Relacionamentos
    conta_bancaria: Mapped["ContaBancaria"] = relationship(
        "ContaBancaria", back_populates="remessas"
    )
    itens: Mapped[list["RemessaItem"]] = relationship(
        "RemessaItem", back_populates="remessa", cascade="all, delete-orphan"
    )


class RemessaItem(Base, TimestampMixin):
    """
    Item individual dentro de uma remessa.
    Pode ser editado quando status = REJEITADO.
    """
    __tablename__ = "remessa_itens"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    remessa_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("remessas.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    lancamento_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("lancamentos.id"), nullable=False
    )

    status: Mapped[RemessaItemStatus] = mapped_column(
        Enum(RemessaItemStatus), default=RemessaItemStatus.PENDENTE
    )
    codigo_retorno: Mapped[str] = mapped_column(String(10), nullable=True)
    motivo_rejeicao: Mapped[str] = mapped_column(String(300), nullable=True)

    # Dados editáveis quando rejeitado (problema #12)
    codigo_barras_corrigido: Mapped[str] = mapped_column(String(100), nullable=True)
    valor_corrigido: Mapped[float] = mapped_column(Numeric(15, 2), nullable=True)

    # Relacionamentos
    remessa: Mapped["Remessa"] = relationship("Remessa", back_populates="itens")
    lancamento: Mapped["Lancamento"] = relationship("Lancamento")
