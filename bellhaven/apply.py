"""Execute an approved proposal's ops against the CRM API. Ops are tiny and
auditable: 'create' (POST) and 'patch' (PATCH). The placeholder
{new_account_id} lets a CHOW proposal link the old account to the account the
same proposal just created."""
from . import crm


def apply(proposal: dict) -> list[dict]:
    log, new_id = [], None
    for i, op in enumerate(proposal["ops"]):
        if op["op"] == "noop":
            log.append({"op": i, "action": "noop"})
            continue
        if op["op"] == "create":
            res = crm.create_account(op["fields"])
            # Response shape can be the account or a confirmation; handle both.
            new_id = (res.get("account_id") or res.get("data", {}).get("account_id")
                      if isinstance(res, dict) else None)
            if not new_id:
                raise RuntimeError(f"create returned no account_id: {res}")
            log.append({"op": i, "action": "create", "new_account_id": new_id})
            continue
        if op["op"] == "patch":
            fields = {k: (v.replace("{new_account_id}", new_id)
                          if isinstance(v, str) and "{new_account_id}" in v else v)
                      for k, v in op["fields"].items()}
            res = crm.patch_account(op["account_id"], fields)
            log.append({"op": i, "action": "patch", "account_id": op["account_id"],
                        "fields": fields, "response": res})
            continue
        raise ValueError(f"unknown op {op['op']}")
    return log
