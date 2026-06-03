import uuid
from enum import Enum as PyEnum
from sqlalchemy import String, Numeric, Date, DateTime, ForeignKey, Boolean, Text, Enum, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base, TimestampMixin
from datetime import datetime, date


class BoletoStatus(str, PyEnum):
    GERADO = "gerado"
    ENVIADO = "enviado"
    PAGO = "pago"
    VENCIDO = "vencido"
    CANCELADO = "cancelado"     # cancelado — nunca exibir para o morador
    SUBSTITUIDO = "substituido" # versão antiga, foi substituído por novo


class Boleto(Base, TimestampMixin):
    """
    Boleto de cobrança ao morador/unidade.
    
    REGRAS DE SEGURANÇA:
    
    1. Boletos trocados (problema #15): cada boleto tem tenant_id + condominio_id + unidade_id.
       A API NUNCA retorna boleto sem validar toda a cadeia de isolamento.
    
    2. Boletos duplicados (problema #11): quando um boleto é cancelado/substituído,
       status muda para CANCELADO ou SUBSTITUIDO. O app do morador só exibe
       boletos com status GERADO, ENVIADO ou VENCIDO. Nunca exibir CANCELADO.
    
    3. Versioning: boleto_versao incrementa a cada substituição.
       boleto_pai_id aponta para o original. Mantém histórico completo.
    """
    __tablename__ = "boletos"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    # Isolamento TRIPLO — nunca servir boleto sem validar os três
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id"), nullable=False, index=True
    )
    condominio_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("condominios.id"), nullable=False, index=True
    )
    unidade_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("unidades.id"), nullable=False, index=True
    )
    morador_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("moradores.id"), nullable=True
    )
    lancamento_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("lancamentos.id"), nullable=True
    )

    # Dados do boleto
    valor: Mapped[float] = mapped_column(Numeric(15, 2), nullable=False)
    data_vencimento: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    mes_referencia: Mapped[str] = mapped_column(String(7), nullable=True)  # "2025-06"
    linha_digitavel: Mapped[str] = mapped_column(String(60), nullable=True)
    codigo_barras: Mapped[str] = mapped_column(String(50), nullable=True)
    nosso_numero: Mapped[str] = mapped_column(String(30), nullable=True)

    # QR Code Pix (problema #8 e #14 — QRCode não aparecia)
    qrcode_pix: Mapped[str] = mapped_column(Text, nullable=True)          # payload EMV
    qrcode_pix_imagem: Mapped[str] = mapped_column(Text, nullable=True)   # base64 PNG

    # Status e controle de versão (problemas #11 e #15)
    status: Mapped[BoletoStatus] = mapped_column(
        Enum(BoletoStatus), default=BoletoStatus.GERADO, index=True
    )
    boleto_versao: Mapped[int] = mapped_column(Integer, default=1)
    boleto_pai_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("boletos.id"), nullable=True
    )

    # Envio
    enviado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    emails_destino: Mapped[str] = mapped_column(Text, nullable=True)  # JSON array de emails

    # Demonstrativo (problema #7 — demonstrativo não aparecia na régua)
    incluir_demonstrativo: Mapped[bool] = mapped_column(Boolean, default=True)
    demonstrativo_receitas: Mapped[str] = mapped_column(Text, nullable=True)  # JSON
    demonstrativo_despesas: Mapped[str] = mapped_column(Text, nullable=True)  # JSON

    pago_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    valor_pago: Mapped[float] = mapped_column(Numeric(15, 2), nullable=True)

    # Relacionamentos
    condominio: Mapped["Condominio"] = relationship(
        "Condominio", back_populates="boletos"
    )
    unidade: Mapped["Unidade"] = relationship("Unidade", back_populates="boletos")
    morador: Mapped["Morador"] = relationship("Morador")
