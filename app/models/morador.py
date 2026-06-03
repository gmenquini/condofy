import uuid
from sqlalchemy import String, Boolean, ForeignKey, Text, Numeric, Date
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base, TimestampMixin


class Fornecedor(Base, TimestampMixin):
    """
    Fornecedor de serviços para o condomínio.
    
    REGRAS (problema #6 melhorias):
    - Não permitir cadastro sem: CNPJ/CPF, nome, endereço, titular
    - Ao digitar CNPJ, buscar nome automaticamente na Receita Federal (problema #5)
    """
    __tablename__ = "fornecedores"

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

    # Dados obrigatórios
    nome: Mapped[str] = mapped_column(String(200), nullable=False)
    documento: Mapped[str] = mapped_column(String(18), nullable=False)  # CNPJ ou CPF
    tipo_documento: Mapped[str] = mapped_column(String(4), default="cnpj")  # cnpj, cpf
    titular: Mapped[str] = mapped_column(String(200), nullable=False)

    # Endereço obrigatório
    endereco: Mapped[str] = mapped_column(String(300), nullable=False)
    cidade: Mapped[str] = mapped_column(String(100), nullable=False)
    estado: Mapped[str] = mapped_column(String(2), nullable=False)
    cep: Mapped[str] = mapped_column(String(9), nullable=True)

    # Contato
    email: Mapped[str] = mapped_column(String(200), nullable=True)
    telefone: Mapped[str] = mapped_column(String(20), nullable=True)

    # Dados bancários para pagamento
    banco: Mapped[str] = mapped_column(String(10), nullable=True)
    agencia: Mapped[str] = mapped_column(String(10), nullable=True)
    conta: Mapped[str] = mapped_column(String(20), nullable=True)

    ativo: Mapped[bool] = mapped_column(Boolean, default=True)

    # Relacionamentos
    condominio: Mapped["Condominio"] = relationship(
        "Condominio", back_populates="fornecedores"
    )
    lancamentos: Mapped[list["Lancamento"]] = relationship(
        "Lancamento", back_populates="fornecedor"
    )


class Unidade(Base, TimestampMixin):
    """Unidade (apartamento/casa) dentro do condomínio."""
    __tablename__ = "unidades"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    # Isolamento
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id"), nullable=False, index=True
    )
    condominio_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("condominios.id", ondelete="CASCADE"),
        nullable=False, index=True
    )

    identificacao: Mapped[str] = mapped_column(String(20), nullable=False)  # "101", "A-12"
    bloco: Mapped[str] = mapped_column(String(20), nullable=True)
    fracao_ideal: Mapped[float] = mapped_column(Numeric(10, 6), nullable=True)
    area_privativa: Mapped[float] = mapped_column(Numeric(10, 2), nullable=True)
    ativa: Mapped[bool] = mapped_column(Boolean, default=True)

    # Relacionamentos
    condominio: Mapped["Condominio"] = relationship(
        "Condominio", back_populates="unidades"
    )
    moradores: Mapped[list["Morador"]] = relationship(
        "Morador", back_populates="unidade"
    )
    boletos: Mapped[list["Boleto"]] = relationship(
        "Boleto", back_populates="unidade"
    )


class Morador(Base, TimestampMixin):
    """
    Morador/proprietário de uma unidade.
    
    tipo: proprietario, inquilino, dependente, procurador
    Voto por procuração (problema #16): tipo 'procurador' com procurador_de_id
    """
    __tablename__ = "moradores"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    # Isolamento
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id"), nullable=False, index=True
    )
    unidade_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("unidades.id", ondelete="CASCADE"),
        nullable=False, index=True
    )

    nome: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    cpf: Mapped[str] = mapped_column(String(14), nullable=True)
    email: Mapped[str] = mapped_column(String(200), nullable=True)
    telefone: Mapped[str] = mapped_column(String(20), nullable=True)

    # Tipo e voto por procuração (problema #16)
    tipo: Mapped[str] = mapped_column(
        String(20), default="proprietario"
        # proprietario, inquilino, dependente, procurador
    )
    procurador_de_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("moradores.id"), nullable=True
        # Se tipo=procurador, aponta para o morador que ele representa
    )

    ativo: Mapped[bool] = mapped_column(Boolean, default=True)

    # Relacionamentos
    unidade: Mapped["Unidade"] = relationship("Unidade", back_populates="moradores")
