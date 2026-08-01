"""
Data transformation logic.

Reads multi-sheet Excel files, validates against schemas,
performs cross-table correlation, computes aggregates,
and outputs structured JSON for LLM consumption.
"""

import logging
from datetime import datetime
from io import BytesIO
from typing import Any

import pandas as pd

from src.modules.data_parser.schema import get_schema_for_sheet

logger = logging.getLogger(__name__)


class DataTransformError(Exception):
    """Raised when data transformation fails."""
    pass


class CreditCardDataTransformer:
    """
    Transforms raw Excel credit card statistics into structured JSON.

    Handles:
    - Multi-sheet reading
    - Schema validation
    - Cross-table correlation
    - Aggregation (monthly totals, YoY growth, market share)
    - JSON output formatting for LLM consumption
    """

    def __init__(self, excel_bytes: bytes):
        """
        Initialize transformer with Excel file content.

        Args:
            excel_bytes: Raw bytes of the Excel file
        """
        self._excel_bytes = excel_bytes
        self._sheets: dict[str, pd.DataFrame] = {}
        self._validated_sheets: dict[str, pd.DataFrame] = {}
        self._validation_errors: list[str] = []

    def read_sheets(self) -> dict[str, pd.DataFrame]:
        """Read all sheets from the Excel file."""
        try:
            xls = pd.ExcelFile(BytesIO(self._excel_bytes))
            for sheet_name in xls.sheet_names:
                df = pd.read_excel(xls, sheet_name=sheet_name)
                # Remove completely empty rows/columns
                df = df.dropna(how="all").dropna(axis=1, how="all")
                if not df.empty:
                    self._sheets[sheet_name] = df
                    logger.info(
                        f"Read sheet '{sheet_name}': {len(df)} rows, {len(df.columns)} cols"
                    )
            return self._sheets
        except Exception as e:
            raise DataTransformError(f"Failed to read Excel file: {e}")

    def validate(self) -> bool:
        """
        Validate all sheets against their data contracts.

        Returns:
            True if all validations pass, False otherwise
        """
        if not self._sheets:
            self.read_sheets()

        self._validation_errors = []

        for sheet_name, df in self._sheets.items():
            schema = get_schema_for_sheet(sheet_name)
            if schema is None:
                logger.warning(f"No schema found for sheet '{sheet_name}', skipping validation")
                self._validated_sheets[sheet_name] = df
                continue

            try:
                validated_df = schema.validate(df, lazy=True)
                self._validated_sheets[sheet_name] = validated_df
                logger.info(f"Sheet '{sheet_name}' passed validation")
            except Exception as e:
                error_msg = f"Sheet '{sheet_name}' validation failed: {e}"
                self._validation_errors.append(error_msg)
                logger.error(error_msg)
                # Still include the sheet but mark as unvalidated
                self._validated_sheets[sheet_name] = df

        return len(self._validation_errors) == 0

    def compute_aggregates(self) -> dict[str, Any]:
        """
        Compute cross-table aggregates and derived metrics.

        Returns:
            Dict containing computed aggregates
        """
        aggregates = {}

        for sheet_name, df in self._validated_sheets.items():
            if "簽帳金額" in df.columns and "銀行名稱" in df.columns:
                # Market share
                total_amount = df["簽帳金額"].sum()
                if total_amount > 0:
                    market_share = (
                        df.groupby("銀行名稱")["簽帳金額"]
                        .sum()
                        .sort_values(ascending=False)
                    )
                    aggregates["簽帳金額_市占率"] = {
                        bank: round(amount / total_amount * 100, 2)
                        for bank, amount in market_share.items()
                    }
                    aggregates["簽帳金額_總計"] = round(total_amount, 2)

            if "流通卡數" in df.columns and "銀行名稱" in df.columns:
                total_cards = df["流通卡數"].sum()
                card_share = (
                    df.groupby("銀行名稱")["流通卡數"]
                    .sum()
                    .sort_values(ascending=False)
                )
                aggregates["流通卡數_市占率"] = {
                    bank: round(count / total_cards * 100, 2)
                    for bank, count in card_share.items()
                }
                aggregates["流通卡數_總計"] = int(total_cards)

            if "有效卡數" in df.columns and "流通卡數" in df.columns:
                # Activation rate per bank
                if "銀行名稱" in df.columns:
                    activation = df.groupby("銀行名稱").agg(
                        有效卡數=("有效卡數", "sum"),
                        流通卡數=("流通卡數", "sum"),
                    )
                    activation["活卡率"] = (
                        activation["有效卡數"] / activation["流通卡數"] * 100
                    ).round(2)
                    aggregates["活卡率"] = activation["活卡率"].to_dict()

        return aggregates

    def to_llm_json(self) -> dict[str, Any]:
        """
        Convert all processed data to structured JSON for LLM consumption.

        Returns:
            Complete structured JSON dict ready for Bedrock prompt
        """
        if not self._validated_sheets:
            self.validate()

        aggregates = self.compute_aggregates()

        # Convert DataFrames to records
        sheets_data = {}
        for sheet_name, df in self._validated_sheets.items():
            sheets_data[sheet_name] = {
                "columns": list(df.columns),
                "row_count": len(df),
                "data": df.head(50).to_dict(orient="records"),  # Limit for LLM context
                "summary_stats": self._compute_summary_stats(df),
            }

        result = {
            "metadata": {
                "source_file": "credit_card_stats.xlsx",
                "parsed_at": datetime.utcnow().isoformat(),
                "total_sheets": len(self._validated_sheets),
                "sheet_names": list(self._validated_sheets.keys()),
                "validation_passed": len(self._validation_errors) == 0,
                "validation_errors": self._validation_errors,
            },
            "sheets": sheets_data,
            "aggregates": aggregates,
            "top_banks": self._get_top_banks(),
        }

        return result

    def _compute_summary_stats(self, df: pd.DataFrame) -> dict[str, Any]:
        """Compute basic summary statistics for numeric columns."""
        stats = {}
        numeric_cols = df.select_dtypes(include=["number"]).columns
        for col in numeric_cols:
            stats[col] = {
                "min": round(float(df[col].min()), 2) if not df[col].isna().all() else None,
                "max": round(float(df[col].max()), 2) if not df[col].isna().all() else None,
                "mean": round(float(df[col].mean()), 2) if not df[col].isna().all() else None,
                "sum": round(float(df[col].sum()), 2) if not df[col].isna().all() else None,
            }
        return stats

    def _get_top_banks(self, n: int = 10) -> list[str]:
        """Get the top N banks by total signing amount across all sheets."""
        all_amounts = {}
        for df in self._validated_sheets.values():
            if "簽帳金額" in df.columns and "銀行名稱" in df.columns:
                for _, row in df.iterrows():
                    bank = row["銀行名稱"]
                    amount = row.get("簽帳金額", 0)
                    all_amounts[bank] = all_amounts.get(bank, 0) + (amount or 0)

        sorted_banks = sorted(all_amounts.items(), key=lambda x: x[1], reverse=True)
        return [bank for bank, _ in sorted_banks[:n]]
