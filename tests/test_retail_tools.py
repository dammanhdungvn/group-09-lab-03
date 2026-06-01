from src.retail.tools import RetailTools


def test_detect_stockout_risk_for_fast_moving_product():
    tools = RetailTools()

    result = tools.detect_stockout_risk("P001", days=7)

    assert result["risk_level"] == "high"
    assert result["days_until_stockout"] <= result["lead_time_days"] + 2


def test_reorder_quantity_respects_pack_size():
    tools = RetailTools()

    result = tools.recommend_reorder_quantity("P001", days=7)

    assert result["recommended_quantity"] > 0
    assert result["recommended_quantity"] % result["pack_size"] == 0


def test_detect_slow_moving_items_uses_sell_through_and_overstock():
    tools = RetailTools()

    result = tools.detect_slow_moving_items(days=30)
    ids = {item["product_id"] for item in result["items"]}

    assert "P006" in ids
    assert "P008" in ids
    assert "P001" not in ids


def test_seasonal_stock_plan_uses_period_multiplier():
    tools = RetailTools()

    trend = tools.get_seasonal_trends("tet_holiday")
    plan = tools.recommend_seasonal_stock_plan("tet_holiday")
    ids = {item["product_id"] for item in plan["items"]}

    assert trend["label"] == "Trước Tết"
    assert "P012" in ids
    assert "P010" in ids
    assert plan["count"] > 0
    assert all(item["demand_multiplier"] > 1 for item in plan["items"])


def test_tool_specs_include_react_argument_schemas():
    specs = RetailTools().tool_specs()
    spec_by_name = {spec["name"]: spec for spec in specs}

    assert "parameters" in spec_by_name["get_inventory"]
    assert "product_id" in spec_by_name["detect_stockout_risk"]["parameters"]
    assert "period_id" in spec_by_name["recommend_seasonal_stock_plan"]["parameters"]
