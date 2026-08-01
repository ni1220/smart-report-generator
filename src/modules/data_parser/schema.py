"""
Data contract definitions using Pandera.

Defines expected schemas for credit card business statistics Excel data.
Validation failures raise clear errors caught by Step Functions.
"""

import pandera as pa
from pandera import Column, DataFrameSchema, Check


# 信用卡業務統計主表 Schema
credit_card_monthly_schema = DataFrameSchema(
    columns={
        "銀行名稱": Column(str, nullable=False, coerce=True),
        "流通卡數": Column(
            int,
            Check.greater_than(0),
            nullable=False,
            coerce=True,
        ),
        "有效卡數": Column(
            int,
            Check.greater_than(0),
            nullable=False,
            coerce=True,
        ),
        "簽帳金額": Column(
            float,
            Check.greater_than_or_equal_to(0),
            nullable=False,
            coerce=True,
        ),
        "預借現金金額": Column(
            float,
            Check.greater_than_or_equal_to(0),
            nullable=True,
            coerce=True,
        ),
        "循環信用餘額": Column(
            float,
            nullable=True,
            coerce=True,
        ),
        "逾期帳款": Column(
            float,
            Check.greater_than_or_equal_to(0),
            nullable=True,
            coerce=True,
        ),
        "呆帳率": Column(
            float,
            Check.in_range(0, 1),
            nullable=True,
            coerce=True,
        ),
    },
    # Allow additional columns not defined here
    strict=False,
    coerce=True,
)

# 分期業務 Schema
installment_schema = DataFrameSchema(
    columns={
        "銀行名稱": Column(str, nullable=False, coerce=True),
        "分期金額": Column(
            float,
            Check.greater_than_or_equal_to(0),
            nullable=False,
            coerce=True,
        ),
        "分期筆數": Column(
            int,
            Check.greater_than_or_equal_to(0),
            nullable=True,
            coerce=True,
        ),
    },
    strict=False,
    coerce=True,
)

# Schema registry for different sheet types
SCHEMA_REGISTRY: dict[str, DataFrameSchema] = {
    "信用卡業務": credit_card_monthly_schema,
    "分期業務": installment_schema,
}


def get_schema_for_sheet(sheet_name: str) -> DataFrameSchema | None:
    """
    Get the appropriate schema for a given sheet name.

    Uses fuzzy matching to find the best schema.

    Args:
        sheet_name: Excel sheet name

    Returns:
        DataFrameSchema or None if no match found
    """
    for key, schema in SCHEMA_REGISTRY.items():
        if key in sheet_name:
            return schema
    return None
