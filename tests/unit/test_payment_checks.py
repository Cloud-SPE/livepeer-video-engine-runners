"""Exact payment-policy arithmetic without wallets, RPC, Docker or spending."""

from decimal import Decimal
from fractions import Fraction
import json
import sys
import pytest

from video_runners.tools.payment_check import check_payments

MAX_PROB = 2**256 - 1


def settings():
    node = {
        "Network": "arbitrum-one-mainnet",
        "TicketFaceValue": "10",
        "TicketWinProb": str(MAX_PROB // 2),
        "KeystorePassword": "PRIVATE_PASSWORD_SENTINEL",
    }
    signer = {
        "Network": "arbitrum-one-mainnet",
        "MaxHourlyPrice": "2",
        "MaxTicketEV": "5",
        "MaxBatchEV": "15",
        "DepositMultiplier": 1,
    }
    return node, signer


def test_missing_explicit_payment_settings_fail():
    result = check_payments({}, {}, {"example": Decimal("1")})
    assert result["ready"] is False
    assert result["checks"][0]["check"] == "payment-settings"


def test_exact_expected_value_and_batch_capacity_are_reported():
    node, signer = settings()
    result = check_payments(node, signer, {"example": Decimal("1")}, batch_tickets=3)
    assert result["ready"] is True
    expected = Fraction(10 * (MAX_PROB // 2), MAX_PROB)
    summary = result["summary"]
    assert (
        Fraction(
            int(summary["ticket_ev_wei"]["numerator"]),
            int(summary["ticket_ev_wei"]["denominator"]),
        )
        == expected
    )
    assert summary["max_tickets_per_batch"] == 3
    assert summary["proposed_batch_tickets"] == 3
    assert "PRIVATE" not in str(result)


def test_ticket_ev_limit_is_exact_beyond_float_precision():
    node, signer = settings()
    node.update(TicketFaceValue=str(MAX_PROB), TicketWinProb="1")
    signer["MaxTicketEV"] = "0.999999999999999999999999"
    result = check_payments(node, signer, {"example": Decimal("1")})
    assert result["ready"] is False
    assert any(
        row["check"] == "ticket-ev-ceiling" and not row["ready"]
        for row in result["checks"]
    )


def test_hourly_price_cannot_round_down_to_the_signer_ceiling():
    node, signer = settings()
    signer["MaxHourlyPrice"] = "1"
    result = check_payments(node, signer, {"example": Decimal("1.000000000000000001")})
    assert result["ready"] is False
    assert any(
        row["check"] == "hourly-price-ceiling" and not row["ready"]
        for row in result["checks"]
    )


def test_proposed_batch_must_fit_the_expected_value_ceiling():
    node, signer = settings()
    result = check_payments(node, signer, {"example": Decimal("1")}, batch_tickets=4)
    assert result["ready"] is False
    assert any(
        row["check"] == "batch-ev-ceiling" and not row["ready"]
        for row in result["checks"]
    )


def test_infinite_signer_rate_ceiling_is_rejected():
    node, signer = settings()
    signer["MaxHourlyPrice"] = "Infinity"
    result = check_payments(node, signer, {"example": Decimal("1")})
    assert result["ready"] is False
    assert result["checks"][0]["check"] == "payment-settings"


def test_node_and_signer_networks_must_match_for_paid_checks():
    node, signer = settings()
    signer["Network"] = "offchain"
    result = check_payments(node, signer, {"example": Decimal("1")})
    assert result["ready"] is False
    assert any(
        row["check"] == "payment-network" and not row["ready"]
        for row in result["checks"]
    )


def test_payment_cli_reads_only_supplied_config_files(tmp_path, monkeypatch, capsys):
    from video_runners.tools import init_deployment

    node, signer = settings()
    node["KeystoreFile"] = str(tmp_path / "nonexistent-private-key.json")
    files = []
    for name, settings_dict in [("node", node), ("signer", signer)]:
        path = tmp_path / (name + ".toml")
        path.write_text(
            "\n".join(
                key + " = " + json.dumps(value) for key, value in settings_dict.items()
            )
        )
        files.append(path)
    catalog = tmp_path / "public.json"
    catalog.write_text('{"models":[{"id":"example","price_usd_per_hour":1.25}]}')
    monkeypatch.setattr(
        init_deployment,
        "output",
        lambda *args: (_ for _ in ()).throw(
            AssertionError("No commands in offline payment check")
        ),
    )
    monkeypatch.setattr(
        init_deployment.socket,
        "socket",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("No network in offline payment check")
        ),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "init",
            "--check-payments",
            "--node-config",
            str(files[0]),
            "--signer-config",
            str(files[1]),
            "--public-catalog",
            str(catalog),
            "--model",
            "example",
            "--batch-tickets",
            "3",
        ],
    )
    before = {path: path.read_bytes() for path in tmp_path.iterdir()}
    init_deployment.main()
    output = capsys.readouterr().out
    result = json.loads(output)
    assert result["ready"] is True
    assert result["summary"]["hourly_usd"] == {"example": "1.25"}
    assert "PRIVATE" not in output
    assert before == {path: path.read_bytes() for path in tmp_path.iterdir()}


@pytest.mark.parametrize(
    "side,key,value",
    [
        ("node", "TicketFaceValue", "0"),
        ("node", "TicketFaceValue", str(MAX_PROB + 1)),
        ("node", "TicketWinProb", "0"),
        ("node", "TicketWinProb", str(MAX_PROB)),
        ("signer", "MaxTicketEV", "NaN"),
        ("signer", "MaxBatchEV", "0"),
        ("signer", "MaxHourlyPrice", "NaN"),
        ("signer", "DepositMultiplier", 0),
    ],
)
def test_invalid_payment_numbers_fail_without_echoing_input(side, key, value):
    node, signer = settings()
    (node if side == "node" else signer)[key] = value
    result = check_payments(node, signer, {"example": Decimal("1")})
    assert result["ready"] is False
    assert result["checks"][0]["check"] == "payment-settings"
    assert "PRIVATE" not in str(result)


def test_matching_zero_chain_ids_are_still_invalid():
    node, signer = settings()
    node["ChainID"] = signer["ChainID"] = 0
    result = check_payments(node, signer, {"example": Decimal("1")})
    assert result["ready"] is False
    assert any(
        row["check"] == "payment-network" and not row["ready"]
        for row in result["checks"]
    )
