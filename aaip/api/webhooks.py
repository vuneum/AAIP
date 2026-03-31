"""
AAIP Webhooks Module - Stub implementation for test compatibility

NOTE: This is a stub module created to fix test import failures.
The actual implementation should be developed separately.
"""

import hmac
import hashlib
import sqlite3
import json
import time
from pathlib import Path
from typing import List, Dict, Any, Optional, Set
from dataclasses import dataclass
from enum import Enum
import httpx


class Events(Enum):
    """Webhook event types"""
    PAYMENT_SUCCESS = "payment.success"
    PAYMENT_FAILED = "payment.failed"
    ALL = "*"


@dataclass
class Endpoint:
    """Webhook endpoint configuration"""
    url: str
    secret: str = ""
    events: Set[str] = None
    active: bool = True
    
    def __post_init__(self):
        if self.events is None:
            self.events = {Events.ALL.value}


class WebhookRegistry:
    """Registry for webhook endpoints"""
    
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.conn = sqlite3.connect(str(db_path))
        self._create_tables()
        
    def _create_tables(self):
        """Create database tables if they don't exist"""
        cursor = self.conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS endpoints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT UNIQUE NOT NULL,
                secret TEXT NOT NULL,
                events TEXT NOT NULL,
                active BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS deliveries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                endpoint_id INTEGER,
                event TEXT NOT NULL,
                payload TEXT NOT NULL,
                status_code INTEGER,
                response TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (endpoint_id) REFERENCES endpoints(id)
            )
        """)
        self.conn.commit()
        
    def register(self, url: str, secret: str = "", events: List[str] = None) -> int:
        """Register a webhook endpoint"""
        # Basic URL validation (stub - test expects ValueError for invalid URLs)
        if not url.startswith(("http://", "https://")):
            raise ValueError(f"Invalid URL: {url}")
            
        if events is None:
            events = [Events.ALL.value]
            
        events_json = json.dumps(events)
        
        cursor = self.conn.cursor()
        try:
            cursor.execute(
                "INSERT OR REPLACE INTO endpoints (url, secret, events, active) VALUES (?, ?, ?, 1)",
                (url, secret, events_json)
            )
            self.conn.commit()
            return cursor.lastrowid
        except sqlite3.Error:
            # If insert fails, try update
            cursor.execute(
                "UPDATE endpoints SET secret = ?, events = ?, active = 1 WHERE url = ?",
                (secret, events_json, url)
            )
            self.conn.commit()
            return self._get_endpoint_id(url)
            
    def _get_endpoint_id(self, url: str) -> Optional[int]:
        """Get endpoint ID by URL"""
        cursor = self.conn.cursor()
        cursor.execute("SELECT id FROM endpoints WHERE url = ?", (url,))
        row = cursor.fetchone()
        return row[0] if row else None
        
    def deregister(self, url: str) -> bool:
        """Deregister a webhook endpoint"""
        cursor = self.conn.cursor()
        cursor.execute("UPDATE endpoints SET active = 0 WHERE url = ?", (url,))
        self.conn.commit()
        return cursor.rowcount > 0
        
    def all_endpoints(self) -> List[Dict[str, Any]]:
        """Get all endpoints"""
        cursor = self.conn.cursor()
        cursor.execute("SELECT id, url, secret, events, active FROM endpoints WHERE active = 1")
        rows = cursor.fetchall()
        
        endpoints = []
        for row in rows:
            endpoints.append({
                "id": row[0],
                "endpoint_id": row[0],  # Alias for test compatibility
                "url": row[1],
                "secret": row[2],
                "events": json.loads(row[3]),
                "active": bool(row[4])
            })
        return endpoints
        
    def endpoints_for_event(self, event: str) -> List[Dict[str, Any]]:
        """Get endpoints subscribed to a specific event"""
        all_endpoints = self.all_endpoints()
        matching = []
        
        for endpoint in all_endpoints:
            events = endpoint["events"]
            if Events.ALL.value in events or event in events:
                matching.append(endpoint)
                
        return matching
        
    def log_delivery(self, endpoint_id: int, event: str, attempt: int = 1, 
                    success: bool = True, status_code: Optional[int] = None, 
                    error: Optional[str] = None):
        """Log a webhook delivery attempt"""
        cursor = self.conn.cursor()
        cursor.execute(
            "INSERT INTO deliveries (endpoint_id, event, payload, status_code, response) VALUES (?, ?, ?, ?, ?)",
            (endpoint_id, event, f"attempt={attempt}, success={success}", status_code, error)
        )
        self.conn.commit()
        
    def delivery_log(self) -> List[Dict[str, Any]]:
        """Get delivery log"""
        cursor = self.conn.cursor()
        cursor.execute("SELECT id, endpoint_id, event, payload, status_code, response, created_at FROM deliveries ORDER BY id DESC")
        rows = cursor.fetchall()
        
        logs = []
        for row in rows:
            logs.append({
                "id": row[0],
                "endpoint_id": row[1],
                "event": row[2],
                "payload": row[3],
                "status_code": row[4],
                "response": row[5],
                "created_at": row[6],
                "success": 1 if "success=True" in str(row[3]) else 0
            })
        return logs
        
    def close(self):
        """Close the database connection"""
        self.conn.close()


class WebhookDispatcher:
    """Dispatcher for webhook events"""
    
    def __init__(self, registry: WebhookRegistry):
        self.registry = registry
        
    def dispatch(self, event: str, payload: Dict[str, Any]):
        """Dispatch an event to all subscribed endpoints"""
        endpoints = self.registry.endpoints_for_event(event)
        if not endpoints:
            return
        
        payload_json = json.dumps(payload, separators=(',', ':'))
        payload_bytes = payload_json.encode('utf-8')
        
        for endpoint in endpoints:
            self._deliver_to_endpoint(endpoint, event, payload_json, payload_bytes)
    
    def _deliver_to_endpoint(self, endpoint: Dict[str, Any], event: str, 
                            payload_json: str, payload_bytes: bytes):
        """Deliver a webhook to a single endpoint with retry logic"""
        url = endpoint['url']
        secret = endpoint.get('secret', '')
        endpoint_id = endpoint['id']
        
        # Prepare headers
        headers = {
            'Content-Type': 'application/json',
            'User-Agent': 'AAIP-Webhook/1.0',
            'X-AAIP-Event': event,
            'X-AAIP-Delivery-ID': str(int(time.time() * 1000)),
        }
        
        # Add HMAC signature if secret is provided
        if secret:
            signature = _sign_payload(payload_bytes, secret)
            headers['Authorization'] = f'HMAC-SHA256 {signature}'
        
        # Retry configuration
        max_retries = 3
        retry_delay = 1.0  # seconds
        last_error = None
        
        for attempt in range(1, max_retries + 1):
            try:
                response = httpx.post(
                    url,
                    content=payload_bytes,
                    headers=headers,
                    timeout=30.0
                )
                
                # Log the delivery attempt
                self.registry.log_delivery(
                    endpoint_id=endpoint_id,
                    event=event,
                    attempt=attempt,
                    success=(200 <= response.status_code < 300),
                    status_code=response.status_code,
                    error=None if (200 <= response.status_code < 300) else f"HTTP {response.status_code}"
                )
                
                # Success - return
                if 200 <= response.status_code < 300:
                    return
                
                # Retry on 5xx errors
                if 500 <= response.status_code < 600 and attempt < max_retries:
                    time.sleep(retry_delay * (2 ** (attempt - 1)))  # Exponential backoff
                    continue
                    
                # Client errors (4xx) are not retried
                break
                    
            except httpx.TimeoutException as e:
                last_error = f"Timeout: {e}"
                self.registry.log_delivery(
                    endpoint_id=endpoint_id,
                    event=event,
                    attempt=attempt,
                    success=False,
                    status_code=None,
                    error=last_error
                )
                if attempt < max_retries:
                    time.sleep(retry_delay * (2 ** (attempt - 1)))
                    continue
                break
                
            except httpx.RequestError as e:
                last_error = f"Request error: {e}"
                self.registry.log_delivery(
                    endpoint_id=endpoint_id,
                    event=event,
                    attempt=attempt,
                    success=False,
                    status_code=None,
                    error=last_error
                )
                if attempt < max_retries:
                    time.sleep(retry_delay * (2 ** (attempt - 1)))
                    continue
                break
                
            except Exception as e:
                last_error = f"Unexpected error: {e}"
                self.registry.log_delivery(
                    endpoint_id=endpoint_id,
                    event=event,
                    attempt=attempt,
                    success=False,
                    status_code=None,
                    error=last_error
                )
                break


def _sign_payload(payload: bytes, secret: str) -> str:
    """Sign payload with HMAC-SHA256"""
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


# Global dispatcher instance
_dispatcher: Optional[WebhookDispatcher] = None
_registry: Optional[WebhookRegistry] = None


def get_dispatcher() -> Optional[WebhookDispatcher]:
    """Get the global webhook dispatcher"""
    global _dispatcher
    return _dispatcher