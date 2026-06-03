"""
Serviço de integração com Pluggy Open Finance.

Fluxo:
1. autenticar()         → obtém apiKey (válida 2h)
2. criar_connect_token() → token para o widget do morador/admin conectar o banco
3. sync_transacoes()    → puxa transações de um item (conta conectada)
4. processar_webhook()  → recebe notificações automáticas do Pluggy
"""

import httpx
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import select, and_

from ..models.conta_bancaria import ContaBancaria
from ..models.transacao import Transacao, TipoTransacao, StatusConciliacao
from ..models.tenant import Tenant


PLUGGY_BASE = "https://api.pluggy.ai"


class PluggyService:

    def __init__(self, client_id: str, client_secret: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self._api_key: str | None = None
        self._api_key_expira: datetime | None = None

    async def autenticar(self) -> str:
        """
        Obtém ou renova o apiKey do Pluggy.
        apiKey é válida por 2 horas — reutiliza se ainda válida.
        """
        agora = datetime.utcnow()
        if self._api_key and self._api_key_expira and agora < self._api_key_expira:
            return self._api_key

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{PLUGGY_BASE}/auth",
                json={"clientId": self.client_id, "clientSecret": self.client_secret}
            )
            resp.raise_for_status()
            data = resp.json()

        self._api_key = data["apiKey"]
        self._api_key_expira = agora + timedelta(hours=1, minutes=50)  # margem de 10min
        return self._api_key

    async def criar_connect_token(
        self,
        webhook_url: str,
        client_user_id: str,
        avoid_duplicates: bool = True
    ) -> str:
        """
        Cria connectToken para abrir o Pluggy Connect Widget.
        O widget permite o usuário autorizar a conexão com o banco.
        """
        api_key = await self.autenticar()
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{PLUGGY_BASE}/connect_token",
                headers={"X-API-KEY": api_key},
                json={
                    "webhookUrl": webhook_url,
                    "clientUserId": client_user_id,
                    "avoidDuplicates": avoid_duplicates
                }
            )
            resp.raise_for_status()
            return resp.json()["accessToken"]

    async def buscar_contas(self, item_id: str) -> list[dict]:
        """Busca contas bancárias de um item conectado."""
        api_key = await self.autenticar()
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{PLUGGY_BASE}/accounts",
                headers={"X-API-KEY": api_key},
                params={"itemId": item_id}
            )
            resp.raise_for_status()
            return resp.json().get("results", [])

    async def buscar_transacoes(
        self,
        account_id: str,
        data_inicio: datetime | None = None,
        data_fim: datetime | None = None
    ) -> list[dict]:
        """Busca transações de uma conta Pluggy."""
        api_key = await self.autenticar()
        params = {"accountId": account_id, "pageSize": 500}
        if data_inicio:
            params["from"] = data_inicio.strftime("%Y-%m-%d")
        if data_fim:
            params["to"] = data_fim.strftime("%Y-%m-%d")

        transacoes = []
        page = 1
        while True:
            params["page"] = page
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{PLUGGY_BASE}/transactions",
                    headers={"X-API-KEY": api_key},
                    params=params
                )
                resp.raise_for_status()
                data = resp.json()

            transacoes.extend(data.get("results", []))
            if len(transacoes) >= data.get("total", 0):
                break
            page += 1

        return transacoes

    async def sync_conta(
        self,
        db: Session,
        conta: ContaBancaria,
        data_inicio: datetime | None = None
    ) -> dict:
        """
        Sincroniza transações de uma conta bancária com o banco de dados.
        Evita duplicatas pelo pluggy_transaction_id (unique constraint).
        """
        if not conta.pluggy_account_id:
            raise ValueError(f"Conta {conta.id} não possui pluggy_account_id")

        transacoes_pluggy = await self.buscar_transacoes(
            conta.pluggy_account_id,
            data_inicio=data_inicio or datetime.utcnow() - timedelta(days=90)
        )

        novas = 0
        ignoradas = 0

        for t in transacoes_pluggy:
            # Verifica se já existe (evita duplicatas do webhook)
            existente = db.execute(
                select(Transacao).where(
                    Transacao.pluggy_transaction_id == t["id"]
                )
            ).scalars().first()

            if existente:
                ignoradas += 1
                continue

            tipo = TipoTransacao.CREDITO if t["type"] == "CREDIT" else TipoTransacao.DEBITO

            nova_transacao = Transacao(
                tenant_id=conta.tenant_id,
                condominio_id=conta.condominio_id,
                conta_bancaria_id=conta.id,
                pluggy_transaction_id=t["id"],
                data=datetime.fromisoformat(t["date"].replace("Z", "+00:00")),
                descricao=t.get("description", ""),
                valor=abs(float(t["amount"])),
                tipo=tipo,
                categoria=t.get("category"),
                saldo_apos=t.get("balance"),
                status_conciliacao=StatusConciliacao.PENDENTE
            )
            db.add(nova_transacao)
            novas += 1

        # Atualiza última sync
        conta.ultima_sync = datetime.utcnow()
        conta.pluggy_status = "UPDATED"

        db.commit()
        return {"novas": novas, "ignoradas": ignoradas, "total_pluggy": len(transacoes_pluggy)}

    async def processar_webhook(
        self,
        db: Session,
        payload: dict
    ) -> dict:
        """
        Processa notificação de webhook do Pluggy.
        Chamado automaticamente quando há novas transações.
        """
        event_type = payload.get("event")
        item_id = payload.get("itemId")

        if event_type not in ["item/updated", "item/created", "transactions/added"]:
            return {"processado": False, "motivo": f"evento ignorado: {event_type}"}

        # Busca conta pela pelo item_id do Pluggy
        conta = db.execute(
            select(ContaBancaria).where(
                ContaBancaria.pluggy_item_id == item_id
            )
        ).scalars().first()

        if not conta:
            return {"processado": False, "motivo": f"item_id {item_id} não encontrado"}

        # Sync automático das transações novas
        resultado = await self.sync_conta(db, conta, data_inicio=datetime.utcnow() - timedelta(days=3))
        return {"processado": True, "conta_id": conta.id, **resultado}


def get_pluggy_service(tenant: Tenant) -> PluggyService:
    """Factory que cria o serviço com as credenciais do tenant."""
    if not tenant.pluggy_client_id or not tenant.pluggy_client_secret:
        raise ValueError("Tenant não tem credenciais Pluggy configuradas")
    return PluggyService(tenant.pluggy_client_id, tenant.pluggy_client_secret)
