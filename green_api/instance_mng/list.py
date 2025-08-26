import requests
from datetime import datetime
from typing import Callable, Iterable, List, Optional

class GreenApiPartnerClient:
    def __init__(self, partner_api_url: str, partner_token: str, *, timeout: int = 10):
        self.partner_api_url = partner_api_url.rstrip('/')
        self.partner_token = partner_token
        self.timeout = timeout

    def get_instances(self) -> List[dict]:
        url = f"{self.partner_api_url}/partner/getInstances/{self.partner_token}"
        resp = requests.get(url, timeout=self.timeout)
        try:
            data = resp.json()
        except ValueError:
            resp.raise_for_status()
            raise
        if resp.status_code == 200:
            if isinstance(data, dict) and data.get("code"):
                raise RuntimeError(f"API error {data.get('code')}: {data.get('description')}")
            if isinstance(data, list):
                return data
            raise RuntimeError("Unexpected response structure")
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text!r}")

    @staticmethod
    def _parse_ts(v) -> Optional[datetime]:
        """Accepts UNIX seconds/millis or ISO8601; returns aware-agnostic naive UTC datetime."""
        if v is None:
            return None
        try:
            # int/float: seconds or millis
            if isinstance(v, (int, float)):
                secs = v / 1000.0 if v > 10_000_000_000 else v
                return datetime.utcfromtimestamp(secs)
            # ISO 8601
            return datetime.fromisoformat(str(v).replace('Z', '+00:00')).replace(tzinfo=None)
        except Exception:
            return None

    def filter_instances(
        self,
        *,
        active: Optional[bool] = None,            # True => not deleted and not expired
        include_deleted: Optional[bool] = None,    # If False, drop deleted regardless of 'active'
        name_contains: Optional[str] = None,
        tariff: Optional[str] = None,
        type_instance: Optional[str] = None,       # e.g. "whatsapp"
        is_free: Optional[bool] = None,
        is_partner: Optional[bool] = None,
        expired: Optional[bool] = None,            # True => only expired
        created_from: Optional[datetime] = None,   # inclusive
        created_to: Optional[datetime] = None,     # exclusive
        predicate: Optional[Callable[[dict], bool]] = None,  # custom filter hook
    ) -> List[dict]:
        items = self.get_instances()

        def ok(inst: dict) -> bool:
            deleted = bool(inst.get("deleted"))
            is_exp = bool(inst.get("isExpired"))
            if include_deleted is False and deleted:
                return False
            if active is True and (deleted or is_exp):
                return False
            if active is False and (not deleted and not is_exp):
                return False
            if expired is True and not is_exp:
                return False
            if expired is False and is_exp:
                return False
            if name_contains and (name_contains.lower() not in str(inst.get("name", "")).lower()):
                return False
            if tariff and str(inst.get("tariff")) != tariff:
                return False
            if type_instance and str(inst.get("typeInstance")) != type_instance:
                return False
            if is_free is not None and bool(inst.get("isFree")) != is_free:
                return False
            if is_partner is not None and bool(inst.get("isPartner")) != is_partner:
                return False

            # timeCreated / timeDeleted may be epoch or ISO; guard quietly
            tc = self._parse_ts(inst.get("timeCreated"))
            if created_from and (tc is None or tc < created_from):
                return False
            if created_to and (tc is None or tc >= created_to):
                return False

            if predicate and not predicate(inst):
                return False
            return True

        return [i for i in items if ok(i)]

if __name__ == "__main__":
    client = GreenApiPartnerClient("https://api.green-api.com", "gac.adf3fc6465ed4c3b93cc973419607dbde355f4e829684a")

    # Active, paid (not free), created since Aug 1, 2025
    from datetime import datetime
    rows = client.filter_instances(
        active=True,
        is_free=False,
        created_from=datetime(2025, 8, 1)
    )

    print(rows)
    # Custom predicate example: only instances whose name starts with "echo-"
    #rows2 = client.filter_instances(predicate=lambda i: str(i.get("name","")).startswith("Echo"))

    #print(rows2)