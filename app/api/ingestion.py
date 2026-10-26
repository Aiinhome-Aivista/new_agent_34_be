import logging
from flask import Blueprint, request, jsonify, Response
from app.services.ingest_service import IngestService, AutoTriggerScheduler

logger = logging.getLogger("fraud_agent.api.ingestion")
ingestion_bp = Blueprint("ingestion", __name__)

@ingestion_bp.route("/upload", methods=["POST"])
def upload_batch_file():
    """
    Accepts multipart Excel (.xlsx) or CSV (.csv) file upload.
    Parses transactions, updates MySQL source domain tables, and triggers fraud investigations.
    """
    if "file" not in request.files:
        return jsonify({"error": "Bad Request", "message": "No file part in multipart request"}), 400

    uploaded_file = request.files["file"]
    if not uploaded_file.filename:
        return jsonify({"error": "Bad Request", "message": "No file selected"}), 400

    filename = uploaded_file.filename
    auto_investigate = request.form.get("auto_investigate", "true").lower() == "true"

    try:
        content = uploaded_file.read()
        res = IngestService.parse_and_ingest(content, filename, auto_investigate=auto_investigate)
        return jsonify(res), 200
    except ValueError as ve:
        return jsonify({"error": "Validation Error", "message": str(ve)}), 422
    except Exception as e:
        logger.error(f"Error ingesting file {filename}: {e}")
        return jsonify({"error": "Internal Server Error", "message": str(e)}), 500

@ingestion_bp.route("/template", methods=["GET"])
def download_sample_template():
    """Returns downloadable sample CSV template with realistic fraud and normal user scenarios."""
    csv_data = IngestService.generate_sample_csv()
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=fraud_transactions_sample_template.csv"}
    )

@ingestion_bp.route("/status", methods=["GET"])
def get_poller_status():
    """Returns background auto-trigger poller status, interval, and metrics."""
    status = AutoTriggerScheduler.get_status()
    return jsonify(status), 200
