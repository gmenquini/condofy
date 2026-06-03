import uuid
from enum import Enum as PyEnum
from sqlalchemy import String, Boolean, ForeignKey, Enum, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base, TimestampMixin
from datetime import datetime


class RoleUsuario(str, PyEnum):
    SUPER_ADMIN = "super_admin"      # você — acesso total
    ADMIN_TENANT = "admin_tenant"    # dono da administradora
    GERENTE = "gerente"              # gerente da administradora
    OPERADOR = "operador"            # operador comum


class Usuario(Base, TimestampMixin):
    """
    Usuário do sistema.
    Super admin não tem tenant_id — acessa tudo.
    Outros usuários pertencem a um tenant.
    """
    __tablename__ = "usuarios"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    # Isolamento — super_admin tem tenant_id = None
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=True, index=True
    )

    nome: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str] = mapped_column(String(200), unique=True, nullable=False, index=True)
    senha_hash: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[RoleUsuario] = mapped_column(
        Enum(RoleUsuario), default=RoleUsuario.OPERADOR, nullable=False
    )
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    ultimo_login: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relacionamentos
    tenant: Mapped["Tenant"] = relationship("Tenant", foreign_keys=[tenant_id])
