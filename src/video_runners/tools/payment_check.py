"""Offline comparison of public rates and explicit node/signer payment settings."""

from fractions import Fraction
from decimal import Decimal
import json
import tomllib

from video_runners.catalog import MODEL_ID

MAX_PROB = 2**256 - 1


def check_payment_files(
    node_file, signer_file, catalog_file, models, batch_tickets=None
):
    try:
        node = tomllib.loads(node_file.read_text(), parse_float=Decimal)
        signer = tomllib.loads(signer_file.read_text(), parse_float=Decimal)

        def reject_constant(_):
            raise ValueError("non-finite JSON value")

        catalog = json.loads(
            catalog_file.read_text(),
            parse_float=Decimal,
            parse_constant=reject_constant,
        )
        entries = catalog["models"]
        if not isinstance(entries, list) or not all(
            isinstance(entry, dict)
            and isinstance(entry.get("id"), str)
            and MODEL_ID.fullmatch(entry["id"])
            for entry in entries
        ):
            raise ValueError("invalid public catalog IDs")
        by_id = {entry["id"]: entry for entry in entries}
        if (
            len(by_id) != len(entries)
            or not models
            or any(model not in by_id for model in models)
        ):
            raise ValueError("select distinct catalog profiles")
        rates = {
            model: by_id[model].get("price_usd_per_hour", 0)
            for model in dict.fromkeys(models)
        }
        return check_payments(node, signer, rates, batch_tickets)
    except (OSError, ValueError, KeyError, TypeError):
        return {
            "ready": False,
            "checks": [
                dict(
                    check="payment-files",
                    ready=False,
                    detail="Explicit TOML files, public catalog or selected model IDs are invalid.",
                    hint="Provide the intended node/signer TOML and priced public catalog; no configuration values or parser errors are printed.",
                )
            ],
        }


def positive_fraction(value):
    result = Fraction(str(value))
    if result <= 0:
        raise ValueError("positive monetary value required")
    return result


def positive_price(value):
    result = Decimal(str(value))
    if not result.is_finite() or result <= 0:
        raise ValueError("positive finite catalog price required")
    return result


def check_payments(node, signer, rates, batch_tickets=None):
    if (
        not {"Network", "TicketFaceValue", "TicketWinProb"} <= node.keys()
        or not {
            "Network",
            "MaxHourlyPrice",
            "MaxTicketEV",
            "MaxBatchEV",
            "DepositMultiplier",
        }
        <= signer.keys()
    ):
        return {
            "ready": False,
            "checks": [
                dict(
                    check="payment-settings",
                    ready=False,
                    detail="Explicit network, ticket parameters and signer ceilings are required.",
                    hint="Review private node/signer TOML files; this check reads no keys and performs no RPC calls.",
                )
            ],
        }
    try:

        def integer(value):
            text = str(value)
            return int(text, 16 if text.lower().startswith("0x") else 10)

        face, probability = integer(node["TicketFaceValue"]), integer(
            node["TicketWinProb"]
        )
        if not 0 < face <= MAX_PROB or not 0 < probability < MAX_PROB:
            raise ValueError("ticket parameters outside pinned node bounds")
        hourly = positive_fraction(signer["MaxHourlyPrice"])
        max_ticket, max_batch = (
            positive_fraction(signer[key]) for key in ("MaxTicketEV", "MaxBatchEV")
        )
        multiplier = integer(signer["DepositMultiplier"])
        if not 1 <= multiplier < 2**63:
            raise ValueError("invalid deposit multiplier")
        prices = {model: positive_price(value) for model, value in rates.items()}
    except (ValueError, TypeError, ArithmeticError):
        return {
            "ready": False,
            "checks": [
                dict(
                    check="payment-settings",
                    ready=False,
                    detail="Invalid ticket parameters, finite positive monetary settings or deposit multiplier.",
                    hint="Use explicit valid uint256 ticket values, probability below 2^256-1, positive signer limits and positive finite catalog prices.",
                )
            ],
        }
    ev = Fraction(face * probability, MAX_PROB)
    capacity = max_batch // ev
    limit_ok = ev <= max_ticket
    checks = [
        dict(
            check="ticket-ev-ceiling",
            ready=limit_ok,
            detail="Expected ticket value checked against the signer ceiling.",
            hint="Review face value, win probability and MaxTicketEV independently.",
        )
    ]
    network_ok = bool(
        isinstance(node["Network"], str)
        and node["Network"]
        and node["Network"] != "offchain"
        and node["Network"] == signer["Network"]
    )
    node_chain = node.get(
        "ChainID", 42161 if node["Network"] == "arbitrum-one-mainnet" else None
    )
    signer_chain = signer.get(
        "ChainID", 42161 if signer["Network"] == "arbitrum-one-mainnet" else None
    )
    try:
        network_ok = (
            network_ok
            and 0 < integer(node_chain) < 2**64
            and integer(node_chain) == integer(signer_chain)
        )
    except (ValueError, TypeError):
        network_ok = False
    checks.append(
        dict(
            check="payment-network",
            ready=network_ok,
            detail="On-chain network and configured chain IDs checked for agreement.",
            hint="Use matching on-chain networks and chain IDs; other named/custom networks require explicit ChainID in both files.",
        )
    )
    price_ok = bool(prices) and all(
        Fraction(price) <= hourly for price in prices.values()
    )
    checks.append(
        dict(
            check="hourly-price-ceiling",
            ready=price_ok,
            detail="Selected positive hourly rates checked against the signer ceiling.",
            hint="Set reviewed public catalog prices and a compatible MaxHourlyPrice; rate ceilings are not total budgets.",
        )
    )
    batch_ok = capacity >= 1 and (
        batch_tickets is None
        or type(batch_tickets) is int
        and 1 <= batch_tickets <= capacity
    )
    checks.append(
        dict(
            check="batch-ev-ceiling",
            ready=batch_ok,
            detail="Proposed batch expected value checked against MaxBatchEV.",
            hint="Choose a batch count within the reported capacity; this does not configure SDK batch negotiation.",
        )
    )
    return {
        "ready": all(row["ready"] for row in checks),
        "checks": checks,
        "summary": {
            "ticket_ev_wei": {
                "numerator": str(ev.numerator),
                "denominator": str(ev.denominator),
            },
            "max_tickets_per_batch": capacity,
            "proposed_batch_tickets": batch_tickets,
            "hourly_usd": {model: str(price) for model, price in prices.items()},
            "ticket_face_value_wei": str(face),
            "deposit_multiplier": multiplier,
        },
    }
