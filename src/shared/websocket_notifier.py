"""
WebSocket progress notifier.

Sends real-time progress updates to connected clients via
API Gateway WebSocket Management API.
"""

import json
import logging
from typing import Any

import boto3
from botocore.exceptions import ClientError

from src.shared.config import get_settings

logger = logging.getLogger(__name__)


class WebSocketNotifier:
    """
    Sends progress updates to WebSocket connections.

    Uses API Gateway Management API to push messages to
    connected clients stored in DynamoDB.
    """

    def __init__(self):
        self._settings = get_settings()
        self._dynamodb = boto3.resource(
            "dynamodb", region_name=self._settings.aws_region
        )
        self._table = self._dynamodb.Table(self._settings.dynamodb_connections_table)

    def _get_management_client(self):
        """Get API Gateway Management API client."""
        if not self._settings.websocket_api_endpoint:
            return None
        return boto3.client(
            "apigatewaymanagementapi",
            endpoint_url=self._settings.websocket_api_endpoint,
            region_name=self._settings.aws_region,
        )

    def get_connections_for_task(self, task_id: str) -> list[str]:
        """
        Get all WebSocket connection IDs subscribed to a task.

        Args:
            task_id: The task identifier

        Returns:
            List of connection IDs
        """
        try:
            response = self._table.query(
                IndexName="task-id-index",
                KeyConditionExpression="task_id = :tid",
                ExpressionAttributeValues={":tid": task_id},
            )
            return [item["connection_id"] for item in response.get("Items", [])]
        except ClientError as e:
            logger.error(f"Failed to query connections for task {task_id}: {e}")
            return []

    def notify_progress(
        self,
        task_id: str,
        step: str,
        status: str,
        progress: int,
        message: str,
        extra: dict[str, Any] | None = None,
    ):
        """
        Send progress update to all connections subscribed to a task.

        Args:
            task_id: Task identifier
            step: Current step name (e.g., "AIInsightGeneration")
            status: Step status ("in_progress", "completed", "failed")
            progress: Progress percentage (0-100)
            message: Human-readable status message
            extra: Additional data to include
        """
        client = self._get_management_client()
        if not client:
            logger.debug("WebSocket endpoint not configured, skipping notification")
            return

        payload = {
            "task_id": task_id,
            "step": step,
            "status": status,
            "progress": progress,
            "message": message,
        }
        if extra:
            payload.update(extra)

        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        connection_ids = self.get_connections_for_task(task_id)

        stale_connections = []
        for conn_id in connection_ids:
            try:
                client.post_to_connection(ConnectionId=conn_id, Data=data)
            except ClientError as e:
                error_code = e.response["Error"]["Code"]
                if error_code == "GoneException":
                    stale_connections.append(conn_id)
                else:
                    logger.error(f"Failed to send to connection {conn_id}: {e}")

        # Clean up stale connections
        for conn_id in stale_connections:
            self._remove_connection(conn_id)

    def _remove_connection(self, connection_id: str):
        """Remove a stale connection from DynamoDB."""
        try:
            self._table.delete_item(Key={"connection_id": connection_id})
        except ClientError as e:
            logger.error(f"Failed to remove stale connection {connection_id}: {e}")


# Module-level convenience function
_notifier: WebSocketNotifier | None = None


def get_notifier() -> WebSocketNotifier:
    """Get the global WebSocketNotifier instance."""
    global _notifier
    if _notifier is None:
        _notifier = WebSocketNotifier()
    return _notifier


def notify_progress(
    task_id: str,
    step: str,
    status: str,
    progress: int,
    message: str,
    **kwargs,
):
    """Convenience function to send progress notification."""
    get_notifier().notify_progress(task_id, step, status, progress, message, kwargs or None)
