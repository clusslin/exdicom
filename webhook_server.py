"""
Webhook Server
Receive push notifications from Google Apps Script
Trigger processing flow when new data is available in Google Sheets
"""

import os
import json
import logging
import hmac
import hashlib
import threading
from datetime import datetime
from flask import Flask, request, jsonify
from pathlib import Path
from typing import Dict, Optional

app = Flask(__name__)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global variable: store reference to workflow manager
workflow_manager = None

# Security key (for verifying request source)
WEBHOOK_SECRET = os.getenv('WEBHOOK_SECRET', 'change-this-secret-key')


class WebhookServer:
    def __init__(self, port: int = 5000, host: str = '0.0.0.0', enable_auth: bool = True):
        """
        Initialize webhook server

        Args:
            port: Server port
            host: Server host address
            enable_auth: Whether to enable request verification
        """
        self.port = port
        self.host = host
        self.enable_auth = enable_auth
        self.server_thread = None

        logger.info(f"Webhook server initialized - Host: {host}, Port: {port}")

    def set_workflow_manager(self, manager):
        """Set workflow manager"""
        global workflow_manager
        workflow_manager = manager
        logger.info("Workflow manager configured")

    def start(self):
        """Start webhook server (in background thread)"""
        self.server_thread = threading.Thread(
            target=self._run_server,
            daemon=True
        )
        self.server_thread.start()
        logger.info(f"Webhook server started in background thread - http://{self.host}:{self.port}")

    def _run_server(self):
        """Run Flask server"""
        app.run(host=self.host, port=self.port, debug=False, use_reloader=False)


def verify_webhook_signature(payload: bytes, signature: str) -> bool:
    """
    Verify webhook request signature

    Args:
        payload: Request content
        signature: Signature

    Returns:
        Whether verification passed
    """
    expected_signature = hmac.new(
        WEBHOOK_SECRET.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(expected_signature, signature)


@app.route('/', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'ok',
        'service': 'DICOM Webhook Server',
        'timestamp': datetime.now().isoformat()
    })


@app.route('/webhook/upload', methods=['GET', 'POST'])
def handle_upload_notification():
    """
    Handle upload notification
    Google Apps Script calls this endpoint when new upload records are available

    GET: Test connection (return server status)
    POST: Receive actual upload notification
    """
    # Handle GET request (test)
    if request.method == 'GET':
        return jsonify({
            'status': 'ok',
            'message': 'Webhook endpoint is operational',
            'service': 'DICOM Upload Webhook',
            'method_required': 'POST',
            'workflow_manager': 'ready' if workflow_manager else 'not_ready',
            'timestamp': datetime.now().isoformat()
        }), 200

    # Handle POST request (actual notification)
    try:
        # Verify request source (optional)
        if hasattr(app, 'config') and app.config.get('ENABLE_AUTH', True):
            signature = request.headers.get('X-Webhook-Signature', '')
            if not signature:
                logger.warning("Received unsigned webhook request")
                return jsonify({'error': 'Missing signature'}), 401

            if not verify_webhook_signature(request.data, signature):
                logger.warning("Webhook signature verification failed")
                return jsonify({'error': 'Signature verification failed'}), 401

        # Parse request data
        data = request.get_json()

        if not data:
            logger.error("Received empty webhook request")
            return jsonify({'error': 'Request content is empty'}), 400

        logger.info(f"Received upload notification: {json.dumps(data, ensure_ascii=False)}")

        # Verify required fields
        required_fields = ['identifier', 'filename', 'row_number']
        missing_fields = [field for field in required_fields if field not in data]

        if missing_fields:
            logger.error(f"Missing required fields: {missing_fields}")
            return jsonify({'error': f'Missing required fields: {missing_fields}'}), 400

        # Check if workflow manager is configured
        if workflow_manager is None:
            logger.error("Workflow manager not configured")
            return jsonify({'error': 'System not ready'}), 503

        # Process in background thread (avoid blocking webhook response)
        processing_thread = threading.Thread(
            target=process_upload_async,
            args=(data,),
            daemon=True
        )
        processing_thread.start()

        # Respond immediately to Google Apps Script (avoid timeout)
        return jsonify({
            'status': 'accepted',
            'message': 'Upload notification received, starting processing',
            'identifier': data['identifier'],
            'timestamp': datetime.now().isoformat()
        }), 202  # 202 Accepted

    except Exception as e:
        logger.error(f"Error processing webhook request: {e}")
        return jsonify({'error': str(e)}), 500


def process_upload_async(data: Dict):
    """
    Process upload asynchronously in background

    Args:
        data: Upload data
    """
    try:
        logger.info(f"Starting upload processing - ID: {data['identifier']}")

        # Create application information (compatible with existing format)
        application = {
            'row_number': data['row_number'],
            'creation_time': data.get('creation_time', ''),
            'hospital_name': data.get('hospital_name', ''),
            'exam_type': data.get('exam_type', ''),
            'uploader_name': data.get('uploader_name', ''),
            'uploader_phone': data.get('uploader_phone', ''),
            'uploader_email': data.get('uploader_email', ''),
            'filename': data['filename'],
            'identifier': data['identifier'],
            'transmission_time': ''
        }

        # Call workflow manager to process
        success = workflow_manager.process_sheets_application(application)

        if success:
            logger.info(f"Upload processing successful - ID: {data['identifier']}")
        else:
            logger.error(f"Upload processing failed - ID: {data['identifier']}")

    except Exception as e:
        logger.error(f"Error during asynchronous upload processing: {e}")


@app.route('/webhook/test', methods=['POST'])
def test_webhook():
    """Test endpoint"""
    data = request.get_json()
    logger.info(f"Received test request: {data}")

    return jsonify({
        'status': 'ok',
        'message': 'Webhook test successful',
        'received_data': data,
        'timestamp': datetime.now().isoformat()
    })


@app.route('/webhook/status', methods=['GET'])
def webhook_status():
    """Query system status"""
    status = {
        'webhook_server': 'running',
        'workflow_manager': 'ready' if workflow_manager else 'not_ready',
        'timestamp': datetime.now().isoformat()
    }

    if workflow_manager:
        status['statistics'] = {
            'total_processed': workflow_manager.total_processed,
            'total_successful': workflow_manager.total_successful,
            'total_failed': workflow_manager.total_failed
        }

    return jsonify(status)


def create_webhook_server(port: int = 5000, host: str = '0.0.0.0', enable_auth: bool = True) -> WebhookServer:
    """
    Create webhook server instance

    Args:
        port: Server port
        host: Server host address
        enable_auth: Whether to enable request verification

    Returns:
        WebhookServer instance
    """
    server = WebhookServer(port=port, host=host, enable_auth=enable_auth)
    app.config['ENABLE_AUTH'] = enable_auth
    return server


if __name__ == "__main__":
    # Standalone test mode
    print("=" * 60)
    print("Webhook Server Test Mode")
    print("=" * 60)
    print(f"Server will start at http://0.0.0.0:5000")
    print("Test endpoints:")
    print("  GET  /              - Health check")
    print("  POST /webhook/upload - Upload notification")
    print("  POST /webhook/test   - Test endpoint")
    print("  GET  /webhook/status - System status")
    print("=" * 60)

    app.run(host='0.0.0.0', port=5000, debug=True)
