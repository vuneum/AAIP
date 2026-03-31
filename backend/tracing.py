"""
AAIP — Lightweight Tracing Module

Provides basic OpenTelemetry-style spans for payment and anchor execution paths.
Can be enhanced with full OpenTelemetry SDK later.

Usage:
    from backend.tracing import trace_span
    
    with trace_span("payment_execution", attributes={"agent_id": "agent_123"}) as span:
        # Payment logic here
        span.set_attribute("amount", 100)
        span.set_status("success")
    
    # Async context manager
    async with trace_span_async("anchor_execution") as span:
        await anchor_proof(...)
        span.set_attribute("poe_hash", poe_hash)
"""

import contextlib
import time
import uuid
import contextvars
from typing import Optional, Dict, Any
from dataclasses import dataclass, field
from datetime import datetime
import logging

log = logging.getLogger("aaip.tracing")

# Global tracer state - use contextvar for async-safe span stacks
_active_spans_var = contextvars.ContextVar("_active_spans", default=None)
_trace_exporter = None


@dataclass
class Span:
    """Simple span implementation."""
    name: str
    trace_id: str
    span_id: str
    parent_span_id: Optional[str] = None
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    attributes: Dict[str, Any] = field(default_factory=dict)
    status: str = "unset"
    status_message: Optional[str] = None
    events: list = field(default_factory=list)
    
    def set_attribute(self, key: str, value: Any):
        """Set a span attribute."""
        self.attributes[key] = value
    
    def add_event(self, name: str, attributes: Optional[Dict[str, Any]] = None):
        """Add an event to the span."""
        self.events.append({
            "name": name,
            "timestamp": time.time(),
            "attributes": attributes or {}
        })
    
    def set_status(self, status: str, message: Optional[str] = None):
        """Set span status."""
        self.status = status
        self.status_message = message
    
    def end(self):
        """End the span."""
        self.end_time = time.time()
        
        # Log the span for now (could export to OpenTelemetry collector)
        duration_ms = (self.end_time - self.start_time) * 1000
        log.debug(
            f"Span '{self.name}' completed: "
            f"trace_id={self.trace_id}, "
            f"duration={duration_ms:.2f}ms, "
            f"status={self.status}"
        )
        
        # Export if exporter is configured
        if _trace_exporter:
            _trace_exporter.export(self)


class TraceExporter:
    """Base class for trace exporters."""
    
    def export(self, span: Span):
        """Export a span."""
        pass


class LoggingExporter(TraceExporter):
    """Export traces to logs."""
    
    def export(self, span: Span):
        duration_ms = (span.end_time - span.start_time) * 1000 if span.end_time else 0
        log.info(
            f"TRACE: {span.name} | "
            f"TraceID: {span.trace_id} | "
            f"Duration: {duration_ms:.2f}ms | "
            f"Status: {span.status} | "
            f"Attributes: {span.attributes}"
        )


def configure_tracing(exporter: Optional[TraceExporter] = None):
    """Configure tracing with an exporter."""
    global _trace_exporter
    _trace_exporter = exporter or LoggingExporter()


@contextlib.contextmanager
def trace_span(name: str, attributes: Optional[Dict[str, Any]] = None):
    """Context manager for creating spans."""
    # Get the current context's span stack - always work with a fresh copy
    active_spans = list(_active_spans_var.get() or [])
    
    # Generate IDs
    trace_id = str(uuid.uuid4())
    span_id = str(uuid.uuid4())
    
    # Get parent span if any
    parent_span_id = active_spans[-1].span_id if active_spans else None
    
    # Create span
    span = Span(
        name=name,
        trace_id=trace_id,
        span_id=span_id,
        parent_span_id=parent_span_id,
        attributes=attributes or {}
    )
    
    # Push to active spans
    active_spans.append(span)
    _active_spans_var.set(active_spans)
    
    try:
        yield span
        span.set_status("success")
    except Exception as e:
        span.set_status("error", str(e))
        raise
    finally:
        span.end()
        # Pop from stack - get fresh copy again
        active_spans = list(_active_spans_var.get() or [])
        if active_spans:  # Should always be non-empty here
            active_spans.pop()
            # If list is now empty, set back to None to avoid sharing empty lists
            if not active_spans:
                _active_spans_var.set(None)
            else:
                _active_spans_var.set(active_spans)


@contextlib.asynccontextmanager
async def trace_span_async(name: str, attributes: Optional[Dict[str, Any]] = None):
    """Async context manager for creating spans."""
    # Get the current context's span stack - always work with a fresh copy
    active_spans = list(_active_spans_var.get() or [])
    
    # Generate IDs
    trace_id = str(uuid.uuid4())
    span_id = str(uuid.uuid4())
    
    # Get parent span if any
    parent_span_id = active_spans[-1].span_id if active_spans else None
    
    # Create span
    span = Span(
        name=name,
        trace_id=trace_id,
        span_id=span_id,
        parent_span_id=parent_span_id,
        attributes=attributes or {}
    )
    
    # Push to active spans
    active_spans.append(span)
    _active_spans_var.set(active_spans)
    
    try:
        yield span
        span.set_status("success")
    except Exception as e:
        span.set_status("error", str(e))
        raise
    finally:
        span.end()
        # Pop from stack - get fresh copy again
        active_spans = list(_active_spans_var.get() or [])
        if active_spans:  # Should always be non-empty here
            active_spans.pop()
            # If list is now empty, set back to None to avoid sharing empty lists
            if not active_spans:
                _active_spans_var.set(None)
            else:
                _active_spans_var.set(active_spans)


def get_current_span() -> Optional[Span]:
    """Get the current active span."""
    active_spans = list(_active_spans_var.get() or [])
    return active_spans[-1] if active_spans else None


# Payment-specific tracing helpers
def trace_payment_execution(agent_id: str, recipient: str, amount: float, currency: str = "USDC"):
    """Create a span for payment execution."""
    return trace_span(
        "payment_execution",
        attributes={
            "agent_id": agent_id,
            "recipient": recipient,
            "amount": amount,
            "currency": currency,
            "payment_type": "agent_to_agent"
        }
    )


def trace_anchor_execution(poe_hash: str, chain: str, tx_hash: Optional[str] = None):
    """Create a span for proof anchoring."""
    return trace_span(
        "anchor_execution",
        attributes={
            "poe_hash": poe_hash,
            "chain": chain,
            "tx_hash": tx_hash,
            "anchor_type": "proof_of_execution"
        }
    )


# Initialize with logging exporter by default
configure_tracing(LoggingExporter())