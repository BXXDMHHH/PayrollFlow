"""Domain errors raised while importing Excel workbooks."""

from payrollflow.exceptions import PayrollFlowError


class ExcelIngestionError(PayrollFlowError):
    """Base error for a workbook that cannot be safely standardized."""


class SourceFileNotFoundError(ExcelIngestionError):
    """The requested source workbook does not exist."""


class WorkbookReadError(ExcelIngestionError):
    """The source workbook is damaged or cannot be read as Excel."""


class WorksheetNotFoundError(ExcelIngestionError):
    """The configured worksheet does not exist in the workbook."""


class MissingColumnsError(ExcelIngestionError):
    """One or more required source columns are missing."""


class InvalidFieldValueError(ExcelIngestionError):
    """A non-empty value cannot be converted to its configured data type."""
