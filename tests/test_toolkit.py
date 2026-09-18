"""Tool layer: schema inference from type hints, argument coercion, structured failures."""

from __future__ import annotations

import enum
import json
from typing import Any, Literal

import pytest

from ballast.kernel.toolkit import Param, Tool, ToolError, Toolkit, tool
from ballast.tools.desk import CLAIM_TYPES, RESOLUTIONS, TEAMS, build_desk_tools


@tool
def compute(order_id: str, amount: float, qty: int, target_skus: list[str] | None = None, urgent: bool = False, claim: Literal["no_reason", "quality"] = "no_reason", blob: dict | None = None) -> dict:
    """Derive the policy-correct refund.

    Args:
        order_id: the order to assess.
        amount: currency amount, taken from compute_refund.
        qty: how many units.
        target_skus: SKUs claimed; omit for the whole order.
        urgent: hurry up.
        claim: which policy branch applies.
        blob: an opaque object parameter.
    """
    return {"order_id": order_id, "amount": amount, "qty": qty, "skus": target_skus, "urgent": urgent, "claim": claim, "blob": blob}


class Tier(str, enum.Enum):
    BRONZE = "BRONZE"
    GOLD = "GOLD"


@tool
def by_enum(tier: Tier, note: str = "") -> str:
    """Resolve a tier.

    Args:
        tier: customer tier.
        note: free text.
    """
    return f"{tier}|{note}"


def param(tool_: Tool, name: str) -> Param:
    return next(p for p in tool_.params if p.name == name)


class TestSchemaInference:
    def test_json_types_come_from_annotations(self) -> None:
        assert param(compute, "order_id").json_type == "string"
        assert param(compute, "amount").json_type == "number"
        assert param(compute, "qty").json_type == "integer"
        assert param(compute, "urgent").json_type == "boolean"
        assert param(compute, "blob").json_type == "object"

    def test_optional_list_keeps_its_item_type(self) -> None:
        skus = param(compute, "target_skus")
        assert (skus.json_type, skus.items, skus.required) == ("array", "string", False)

    def test_literal_arguments_become_enums(self) -> None:
        claim = param(compute, "claim")
        assert claim.enum == ["no_reason", "quality"]
        assert claim.json_type == "string"
        assert claim.default == "no_reason" and claim.required is False

    def test_str_enum_classes_are_inferred(self) -> None:
        tier = param(by_enum, "tier")
        assert tier.enum == ["BRONZE", "GOLD"]

    def test_docstring_summary_and_args_become_descriptions(self) -> None:
        assert compute.description == "Derive the policy-correct refund."
        assert param(compute, "order_id").description == "the order to assess."
        assert param(compute, "target_skus").description == "SKUs claimed; omit for the whole order."
        assert by_enum.description == "Resolve a tier."

    def test_required_list_and_schema_shape(self) -> None:
        schema = compute.schema()
        assert schema["type"] == "function"
        fn = schema["function"]
        assert fn["name"] == "compute"
        assert fn["parameters"]["required"] == ["order_id", "amount", "qty"]
        assert fn["parameters"]["properties"]["target_skus"] == {
            "type": "array",
            "items": {"type": "string"},
            "description": "SKUs claimed; omit for the whole order.",
        }
        assert fn["parameters"]["properties"]["claim"]["enum"] == ["no_reason", "quality"]

    def test_defaults_are_advertised(self) -> None:
        assert param(compute, "urgent").as_schema()["default"] is False
        assert "default" not in param(compute, "target_skus").as_schema()

    def test_keyword_overrides(self) -> None:
        @tool(name="renamed", description="override", mutating=True, tags=["money"], enums={"x": ["a", "b"]})
        def raw(x: str) -> dict:  # pragma: no cover - never invoked
            """Ignored docstring.

            Args:
                x: a value.
            """
            return {}

        assert (raw.name, raw.description, raw.mutating, raw.tags) == ("renamed", "override", True, ["money"])
        assert param(raw, "x").enum == ["a", "b"]

    def test_self_and_var_args_are_skipped(self) -> None:
        @tool
        def with_star(first: str, *extra: str, **options: str) -> dict:
            """Star args.

            Args:
                first: the only real parameter.
            """
            return {"first": first}

        assert [p.name for p in with_star.params] == ["first"]

    def test_unannotated_function_still_builds(self) -> None:
        @tool
        def loose(thing):  # noqa: ANN001, ANN202 - deliberately untyped
            """Loose tool.

            Args:
                thing: whatever.
            """
            return thing

        assert param(loose, "thing").json_type == "string"


class TestValidateCoercion:
    def test_numeric_strings_are_coerced(self) -> None:
        args, problems = compute.validate({"order_id": "SO1", "amount": "12.5", "qty": "3"})
        assert problems == []
        assert (args["amount"], args["qty"]) == (12.5, 3)
        assert isinstance(args["qty"], int)

    def test_currency_and_thousand_separators(self) -> None:
        args, problems = compute.validate({"order_id": "SO1", "amount": "¥1,299.00", "qty": 1})
        assert problems == [] and args["amount"] == 1299.0

    def test_json_string_becomes_a_list(self) -> None:
        args, problems = compute.validate({"order_id": "S", "amount": 1, "qty": 1, "target_skus": '["SKU-A", "SKU-B"]'})
        assert problems == [] and args["target_skus"] == ["SKU-A", "SKU-B"]

    @pytest.mark.parametrize("raw", ["SKU-A,SKU-B", "SKU-A，SKU-B", "SKU-A SKU-B", "SKU-A; SKU-B"])
    def test_separated_strings_become_a_list(self, raw: str) -> None:
        args, problems = compute.validate({"order_id": "S", "amount": 1, "qty": 1, "target_skus": raw})
        assert problems == [] and args["target_skus"] == ["SKU-A", "SKU-B"]

    def test_single_scalar_becomes_a_one_item_list(self) -> None:
        args, problems = compute.validate({"order_id": "S", "amount": 1, "qty": 1, "target_skus": "SKU-A"})
        assert problems == [] and args["target_skus"] == ["SKU-A"]

    def test_booleans_accept_words(self) -> None:
        for value, expected in [("true", True), ("YES", True), ("1", True), ("false", False), ("no", False), ("0", False)]:
            args, problems = compute.validate({"order_id": "S", "amount": 1, "qty": 1, "urgent": value})
            assert problems == [] and args["urgent"] is expected

    def test_json_object_string_is_parsed(self) -> None:
        args, problems = compute.validate({"order_id": "S", "amount": 1, "qty": 1, "blob": '{"a": 1}'})
        assert problems == [] and args["blob"] == {"a": 1}

    def test_defaults_are_filled_for_omitted_optionals(self) -> None:
        args, _ = compute.validate({"order_id": "S", "amount": 1, "qty": 1})
        assert args["urgent"] is False and args["claim"] == "no_reason"
        assert "target_skus" not in args  # default None stays absent

    def test_integers_reject_fractional_values(self) -> None:
        _, problems = compute.validate({"order_id": "S", "amount": 1, "qty": 2.5})
        assert any(p.startswith("invalid_type: 'qty' expected integer, got fractional") for p in problems)

    def test_booleans_are_not_numbers(self) -> None:
        _, problems = compute.validate({"order_id": "S", "amount": True, "qty": 1})
        assert any("expected number, got boolean" in p for p in problems)

    def test_enum_violations_are_named(self) -> None:
        _, problems = compute.validate({"order_id": "S", "amount": 1, "qty": 1, "claim": "bogus"})
        assert problems[0].startswith("invalid_enum: 'claim'='bogus' not in ['no_reason', 'quality']")

    def test_missing_required_arguments_are_listed(self) -> None:
        args, problems = compute.validate({"amount": 1})
        assert any(p.startswith("missing_required_argument: 'order_id' (string)") for p in problems)
        assert any("qty" in p for p in problems)
        assert "order_id" not in args

    def test_unknown_argument_suggests_the_near_miss(self) -> None:
        args, problems = compute.validate({"orderId": "SO1", "amount": 1, "qty": 1})
        assert problems[0].startswith("unknown_argument: 'orderId' is not accepted by compute")
        assert "did you mean 'order_id'?" in problems[0]
        assert "orderId" not in args

    def test_unknown_argument_without_a_near_miss(self) -> None:
        _, problems = compute.validate({"order_id": "S", "amount": 1, "qty": 1, "quantum_tunnelling": 4})
        assert problems[0].startswith("unknown_argument: 'quantum_tunnelling'")
        assert "did you mean" not in problems[0]

    def test_non_object_arguments(self) -> None:
        assert compute.validate(None) == ({}, ["arguments must be a JSON object, got NoneType"])
        assert compute.validate("x")[1] == ["arguments must be a JSON object, got str"]

    def test_problems_accumulate_instead_of_short_circuiting(self) -> None:
        args, problems = compute.validate({"ticketId": "T1", "amount": "abc"})
        codes = [p.split(":", 1)[0] for p in problems]
        assert codes.count("unknown_argument") == 1 and codes.count("invalid_type") == 1
        assert codes.count("missing_required_argument") == 3  # order_id, qty and the failed amount
        # only the usable values survive: a rejected argument is absent, not guessed
        assert "amount" not in args and "ticketId" not in args
        assert args["urgent"] is False  # defaults are still filled in

    def test_enum_values_pass_validation_unchanged(self) -> None:
        args, problems = by_enum.validate({"tier": "GOLD"})
        assert problems == [] and args["tier"] == "GOLD"
        assert by_enum.call(args) == "GOLD|"
        assert by_enum.validate({"tier": "DIAMOND"})[1][0].startswith("invalid_enum: 'tier'")


class TestToolkitDispatch:
    def test_registry_lookups(self) -> None:
        kit = Toolkit([compute, by_enum])
        assert "compute" in kit and "missing" not in kit
        assert kit.names == sorted(["compute", "by_enum"])
        assert kit.get("compute") is compute and kit.get("nope") is None
        assert {s["function"]["name"] for s in kit.schemas()} == {"compute", "by_enum"}
        assert [s["function"]["name"] for s in kit.schemas(["compute"])] == ["compute"]

    def test_unknown_tool_bounces_back_the_real_menu(self) -> None:
        kit = Toolkit([compute])
        result = kit.execute("get_order", {})
        assert result.ok is False
        payload = json.loads(result.content)
        assert payload["error"] == "unknown_tool"
        assert "available: compute" in payload["hint"]
        assert kit.rejections == 1

    def test_validation_failure_is_structured_and_counted(self) -> None:
        kit = Toolkit([compute])
        result = kit.execute("compute", {"order_id": "SO1", "amount": "nope", "qty": 1})
        assert result.ok is False
        assert result.error["error"] == "invalid_arguments"
        assert result.validation_problems
        assert "invalid_type" in result.error["hint"]
        assert result.error["problems"] == result.validation_problems
        assert kit.rejections == 1

    def test_happy_path_returns_json_and_latency(self) -> None:
        kit = Toolkit([compute])
        result = kit.execute("compute", {"order_id": "SO1", "amount": "12.5", "qty": "2"}, call_id="c9")
        assert result.ok and result.error is None
        assert json.loads(result.content)["amount"] == 12.5
        assert result.latency_ms >= 0.0
        assert result.as_message("c9") == {"role": "tool", "tool_call_id": "c9", "name": "compute", "content": result.content}

    def test_string_results_are_passed_through(self) -> None:
        @tool
        def raw_note(order_id: str) -> str:
            """Return plain text.

            Args:
                order_id: an order.
            """
            return f"note for {order_id}"

        assert Toolkit([raw_note]).execute("raw_note", {"order_id": "SO1"}).content == "note for SO1"

    def test_tool_error_becomes_a_readable_refusal(self) -> None:
        @tool
        def denied(order_id: str) -> dict:
            """Refuses.

            Args:
                order_id: an order.
            """
            raise ToolError("policy_denied", "window closed", hint="close the ticket", retryable=False)

        result = Toolkit([denied]).execute("denied", {"order_id": "SO1"})
        assert result.ok is False
        assert json.loads(result.content) == {"error": "policy_denied", "message": "window closed", "hint": "close the ticket", "retryable": False}

    def test_crashes_are_contained(self) -> None:
        @tool
        def broken(order_id: str) -> dict:
            """Crashes.

            Args:
                order_id: an order.
            """
            raise RuntimeError("boom")

        result = Toolkit([broken]).execute("broken", {"order_id": "SO1"})
        assert result.ok is False and result.error["error"] == "tool_crashed"
        assert "RuntimeError: boom" in result.error["message"] and result.error["retryable"] is True

    def test_non_serialisable_results_survive(self) -> None:
        @tool
        def weird(order_id: str) -> dict:
            """Returns something odd.

            Args:
                order_id: an order.
            """

            class Thing:
                def __repr__(self) -> str:
                    return "<thing>"

            return {"order_id": order_id, "thing": Thing()}

        assert "thing" in Toolkit([weird]).execute("weird", {"order_id": "SO1"}).content

    def test_prompt_section_is_a_compact_menu(self) -> None:
        section = Toolkit([compute, by_enum]).prompt_section()
        assert section.startswith("- by_enum: Resolve a tier.") or "- compute: Derive the policy-correct refund." in section
        assert "{" not in section  # no JSON schema noise


class TestDeskToolSchemas:
    """The real tool menu the model sees, built against a live run context."""

    @pytest.fixture
    def desk(self, kb: Any) -> tuple[Toolkit, Any]:
        from ballast.env.fixtures import by_id
        from ballast.kernel.events import RunContext
        from ballast.support.text import ScratchStore

        world = by_id("S01_inwindow_refund").build_world()
        ctx = RunContext(task_id="S01_inwindow_refund", arm="schema", world=world, sop=kb)
        ctx.scratch = ScratchStore()
        return Toolkit(build_desk_tools(ctx)), ctx

    def test_all_sixteen_tools_register(self, desk: tuple[Toolkit, Any]) -> None:
        kit, _ = desk
        assert len(kit.names) == 16
        for name in ("compute_refund", "issue_refund", "search_sop", "read_scratch", "close_ticket", "escalate_ticket"):
            assert name in kit

    def test_money_tools_are_flagged_mutating(self, desk: tuple[Toolkit, Any]) -> None:
        kit, _ = desk
        assert kit.get("issue_refund").mutating and "money" in kit.get("issue_refund").tags
        assert kit.get("send_coupon").mutating
        assert not kit.get("get_order").mutating and not kit.get("compute_refund").mutating

    def test_claim_type_and_team_menus_match_the_engine(self, desk: tuple[Toolkit, Any]) -> None:
        kit, _ = desk
        # The desk tools take these as free strings, but the policy engine and the
        # validators are the single source of truth for what is accepted.
        assert set(CLAIM_TYPES) == {"no_reason", "quality", "missing_item", "damaged", "duplicate_charge", "other"}
        assert set(RESOLUTIONS) >= {"refunded", "coupon", "escalated", "rejected_by_policy"}
        assert "refund" not in RESOLUTIONS  # a typo the desk tool would reject at runtime
        assert set(TEAMS) >= {"risk", "logistics", "supervisor"}
        assert kit.get("escalate_ticket") is not None and kit.get("flag_risk").mutating

    def test_compute_refund_schema_advertises_optional_skus(self, desk: tuple[Toolkit, Any]) -> None:
        kit, _ = desk
        schema = kit.get("compute_refund").schema()["function"]["parameters"]
        assert schema["required"] == ["order_id", "claim_type"]
        assert schema["properties"]["target_skus"]["items"] == {"type": "string"}

    def test_read_scratch_reads_back_an_offloaded_payload(self, desk: tuple[Toolkit, Any]) -> None:
        kit, ctx = desk
        handle = ctx.scratch.put("list_tickets-call_1", json.dumps({"tickets": [{"id": "T1042"}]}))
        result = kit.execute("read_scratch", {"handle": handle, "offset": 0, "limit": 20})
        assert result.ok and json.loads(result.content)["text"].startswith("{")
        assert kit.execute("read_scratch", {"handle": "scratch://nope-deadbeef"}).error["error"] == "not_found"

    def test_desk_tools_reject_model_authored_nonsense(self, desk: tuple[Toolkit, Any]) -> None:
        kit, _ = desk
        camel = kit.execute("get_order", {"orderId": "SO20261042"})
        assert camel.ok is False and camel.error["error"] == "invalid_arguments"
        assert any(p.startswith("unknown_argument: 'orderId'") and "did you mean 'order_id'" in p for p in camel.validation_problems)
        assert any(p.startswith("missing_required_argument: 'order_id'") for p in camel.validation_problems)
        assert kit.execute("close_ticket", {"ticket_id": "T1042", "resolution": "refunded"}).ok is False

    def test_amount_strings_coerce_all_the_way_into_the_world(self, desk: tuple[Toolkit, Any]) -> None:
        kit, ctx = desk
        kit.execute("compute_refund", {"order_id": "SO20261042", "claim_type": "no_reason"})
        result = kit.execute("issue_refund", {"order_id": "SO20261042", "amount": "129.00", "reason": "no_reason", "note": "中文备注"})
        assert result.ok, result.content
        assert json.loads(result.content)["amount"] == 129.0
        assert ctx.world.state()["refunds"][0]["note"] == "中文备注"
