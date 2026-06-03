import uuid
from sqlalchemy import String, Boolean, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base, TimestampMixin


class Tenant(Base, TimestampMixin):
    """
    Administradora de condomínios.
    Cada tenant é completamente isolado — nunca cruzar dados entre tenants.
    """
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    nome: Mapped[str] = mapped_column(String(200), nullable=False)
    cnpj: Mapped[str] = mapped_column(String(18), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    telefone: Mapped[str] = mapped_column(String(20), nullable=True)

    # Plano / billing
    plano: Mapped[str] = mapped_column(String(50), default="basico")  # basico, profissional, enterprise
    max_condominios: Mapped[int] = mapped_column(Integer, default=5)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    endereco: Mapped[str] = mapped_column(String(300), nullable=True)
    cidade: Mapped[str] = mapped_column(String(100), nullable=True)
    estado: Mapped[str] = mapped_column(String(2), nullable=True)
    cep: Mapped[str] = mapped_column(String(9), nullable=True)
    lat: Mapped[float] = mapped_column(nullable=True)
    lng: Mapped[float] = mapped_column(nullable=True)

    # Pluggy — credenciais por tenant (cada administradora tem as próprias)
    pluggy_client_id: Mapped[str] = mapped_column(String(100), nullable=True)
    pluggy_client_secret: Mapped[str] = mapped_column(String(100), nullable=True)

    # Relacionamentos
    condominios: Mapped[list["Condominio"]] = relationship(
        "Condominio", back_populates="tenant", cascade="all, delete-orphan"
    )
