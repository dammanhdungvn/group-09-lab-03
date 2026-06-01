from src.retail.advisor import RetailStockAdvisor


def test_weekly_advisor_returns_restock_promotion_and_trace():
    advisor = RetailStockAdvisor()

    result = advisor.answer("Tuần này tôi nên nhập thêm mặt hàng nào và giảm giá mặt hàng nào?")

    assert result.restock_items
    assert result.promotion_items
    assert result.metrics["tool_calls"] >= 6
    assert result.metrics["products_analyzed"] == 12
    assert any("recommend_reorder_quantity" in step.action for step in result.trace)
    assert "Khuyến nghị tuần này" in result.answer


def test_advisor_can_include_seasonal_trend_case():
    advisor = RetailStockAdvisor()

    result = advisor.answer(
        "Trước Tết tôi nên chuẩn bị thêm mặt hàng nào?",
        period_id="tet_holiday",
    )

    assert result.seasonal_items
    assert result.metrics["seasonal_count"] == len(result.seasonal_items)
    assert any("get_seasonal_trends" in step.action for step in result.trace)
    assert any("recommend_seasonal_stock_plan" in step.action for step in result.trace)
    assert "Xu hướng theo giai đoạn" in result.answer
