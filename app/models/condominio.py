import uuid
from sqlalchemy import String, Boolean, Integer, ForeignKey, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base, TimestampMixin


class Condominio(Base, TimestampMixin):
    """
    Condomínio gerenciado pela administradora.

    REGRA DE SEGURANÇA: todo SELECT nesta tabela DEVE filtrar por tenant_id.
    Nunca buscar sem escopo — isso previne o bug de boletos trocados (#15).
    """
    __tablename__ = "condominios"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    # Isolamento obrigatório
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True
    )

    # Dados do condomínio
    nome: Mapped[str] = mapped_column(String(200), nullable=False)
    cnpj: Mapped[str] = mapped_column(String(18), nullable=True)
    endereco: Mapped[str] = mapped_column(String(300), nullable=True)
    cidade: Mapped[str] = mapped_column(String(100), nullable=True)
    estado: Mapped[str] = mapped_column(String(2), nullable=True)
    cep: Mapped[str] = mapped_column(String(9), nullable=True)
    total_unidades: Mapped[int] = mapped_column(Integer, default=0)

    ativo: Mapped[bool] = mapped_column(Boolean, default=True)

    # Relacionamentos
    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="condominios")
    contas_bancarias: Mapped[list["ContaBancaria"]] = relationship(
        "ContaBancaria", back_populates="condominio", cascade="all, delete-orphan"
    )
    lancamentos: Mapped[list["Lancamento"]] = relationship(
        "Lancamento", back_populates="condominio", cascade="all, delete-orphan"
    )
    boletos: Mapped[list["Boleto"]] = relationship(
        "Boleto", back_populates="condominio", cascade="all, delete-orphan"
    )
    unidades: Mapped[list["Unidade"]] = relationship(
        "Unidade", back_populates="condominio", cascade="all, delete-orphan"
    )
    fornecedores: Mapped[list["Fornecedor"]] = relationship(
        "Fornecedor", back_populates="condominio"
    )
