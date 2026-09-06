"""Canonical render-time processing and mastering architecture."""

from .catalog import (
    ProcessorSpec,
    canonical_processor_name,
    get_processor_spec,
    processing_catalog,
    processor_names,
)
from .model import ProcessingOperation, ProcessingPlan

__all__ = [
    "ProcessorSpec",
    "ProcessingOperation",
    "ProcessingPlan",
    "canonical_processor_name",
    "get_processor_spec",
    "processing_catalog",
    "processor_names",
]
