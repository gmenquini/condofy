"""
Serviço de autenticação — JWT + bcrypt
"""
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session
from sqlalchemy import select
import os

from ..models.usuario import Usuario, RoleUsuario

SECRET_KEY = os.getenv("SECRET_KEY", "condofy-dev-secret-troque-em-producao")
ALGORITHM = "HS256"
TOKEN_EXPIRE_HORAS = 8

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_senha(senha: str) -> str:
    return pwd_context.hash(senha)


def verificar_senha(senha: str, hash: str) -> bool:
    return pwd_context.verify(senha, hash)


def criar_token(dados: dict, expire_horas: int = TOKEN_EXPIRE_HORAS) -> str:
    payload = dados.copy()
    payload["exp"] = datetime.utcnow() + timedelta(hours=expire_horas)
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decodificar_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None


def autenticar_usuario(db: Session, email: str, senha: str) -> Optional[Usuario]:
    usuario = db.execute(
        select(Usuario).where(Usuario.email == email, Usuario.ativo == True)
    ).scalars().first()

    if not usuario or not verificar_senha(senha, usuario.senha_hash):
        return None

    usuario.ultimo_login = datetime.utcnow()
    db.commit()
    return usuario


def criar_usuario(
    db: Session,
    nome: str,
    email: str,
    senha: str,
    role: RoleUsuario,
    tenant_id: str = None
) -> Usuario:
    usuario = Usuario(
        nome=nome,
        email=email,
        senha_hash=hash_senha(senha),
        role=role,
        tenant_id=tenant_id
    )
    db.add(usuario)
    db.commit()
    db.refresh(usuario)
    return usuario


def seed_usuarios(db: Session, tenant_id: str = None):
    """
    Cria usuários de exemplo se não existirem.
    Chamado no startup da aplicação.
    """
    from ..models.tenant import Tenant

    # Super Admin
    if not db.execute(select(Usuario).where(Usuario.email == "admin@condofy.com.br")).scalars().first():
        criar_usuario(db, "Super Admin Condofy", "admin@condofy.com.br", "Condofy@2026!", RoleUsuario.SUPER_ADMIN)
        print("✓ Super admin criado: admin@condofy.com.br / Condofy@2026!")

    # Tenant de demo
    tenant_demo = db.execute(select(Tenant).where(Tenant.cnpj == "12.345.678/0001-99")).scalars().first()
    if not tenant_demo:
        tenant_demo = Tenant(
            nome="Administradora Demo Ltda",
            cnpj="12.345.678/0001-99",
            email="demo@administradora.com.br",
            pluggy_client_id=os.getenv("PLUGGY_CLIENT_ID"),
            pluggy_client_secret=os.getenv("PLUGGY_CLIENT_SECRET"),
        )
        db.add(tenant_demo)
        db.commit()
        db.refresh(tenant_demo)
        print(f"✓ Tenant demo criado: {tenant_demo.id}")

    # Admin da administradora demo
    if not db.execute(select(Usuario).where(Usuario.email == "admin@demo.com.br")).scalars().first():
        criar_usuario(db, "Admin Demo", "admin@demo.com.br", "Demo@2026!", RoleUsuario.ADMIN_TENANT, tenant_demo.id)
        print("✓ Admin demo criado: admin@demo.com.br / Demo@2026!")

    # Gerente demo
    if not db.execute(select(Usuario).where(Usuario.email == "gerente@demo.com.br")).scalars().first():
        criar_usuario(db, "Gerente Demo", "gerente@demo.com.br", "Gerente@2026!", RoleUsuario.GERENTE, tenant_demo.id)
        print("✓ Gerente demo criado: gerente@demo.com.br / Gerente@2026!")

    # Operador demo
    if not db.execute(select(Usuario).where(Usuario.email == "operador@demo.com.br")).scalars().first():
        criar_usuario(db, "Operador Demo", "operador@demo.com.br", "Operador@2026!", RoleUsuario.OPERADOR, tenant_demo.id)
        print("✓ Operador demo criado: operador@demo.com.br / Operador@2026!")
