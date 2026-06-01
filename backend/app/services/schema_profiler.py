from typing import Any

import pandas as pd


class SchemaProfiler:
    @staticmethod
    def infer_column_type(series: pd.Series) -> str:
        if pd.api.types.is_integer_dtype(series):
            return "integer"

        if pd.api.types.is_float_dtype(series):
            return "float"

        if pd.api.types.is_bool_dtype(series):
            return "boolean"

        if pd.api.types.is_datetime64_any_dtype(series):
            return "datetime"

        return "text"

    @staticmethod
    def get_numeric_stats(series: pd.Series) -> dict[str, Any] | None:
        if not pd.api.types.is_numeric_dtype(series):
            return None

        non_null_series = series.dropna()

        if non_null_series.empty:
            return None

        return {
            "min": float(non_null_series.min()),
            "max": float(non_null_series.max()),
            "mean": float(non_null_series.mean()),
            "median": float(non_null_series.median()),
            "std": (
                float(non_null_series.std())
                if len(non_null_series) > 1
                else 0.0
            ),
        }

    @staticmethod
    def get_sample_values(
        series: pd.Series,
        max_samples: int = 5,
    ) -> list[str] | None:
        """
        Returns small safe categorical samples for prompt grounding.
        Avoids exposing full dataset rows.
        """

        if pd.api.types.is_numeric_dtype(series):
            return None

        unique_values = (
            series.dropna()
            .astype(str)
            .unique()
            .tolist()
        )

        if not unique_values:
            return None

        return unique_values[:max_samples]

    @classmethod
    def generate_profile(
        cls,
        dataframe: pd.DataFrame,
        table_name: str,
        original_filename: str,
    ) -> dict[str, Any]:

        row_count = len(dataframe)
        column_count = len(dataframe.columns)

        columns = []

        for column_name in dataframe.columns:
            series = dataframe[column_name]

            null_count = int(series.isna().sum())
            non_null_count = int(series.notna().sum())

            columns.append(
                {
                    "name": column_name,
                    "pandas_dtype": str(series.dtype),
                    "inferred_type": cls.infer_column_type(series),
                    "null_count": null_count,
                    "non_null_count": non_null_count,
                    "null_percentage": (
                        round((null_count / row_count) * 100, 2)
                        if row_count > 0
                        else 0
                    ),
                    "unique_count": int(
                        series.nunique(dropna=True)
                    ),
                    "numeric_stats": cls.get_numeric_stats(series),
                    "sample_values": cls.get_sample_values(series),
                }
            )

        return {
            "dataset": {
                "original_filename": original_filename,
                "table_name": table_name,
                "row_count": row_count,
                "column_count": column_count,
            },
            "columns": columns,
            "privacy_note": (
                "Raw CSV rows are not included. "
                "This profile only contains schema metadata "
                "and safe summary statistics."
            ),
        }