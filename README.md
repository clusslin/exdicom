# EXDICOM - DICOM Automated Processing System

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)

A comprehensive automation system for processing and transferring DICOM medical imaging files with Google Sheets integration, featuring webhook support for real-time notifications and multiple PACS connectivity options.

## Features

### Core Functionality
- **Automated DICOM Processing**: Automatic extraction, decompression, and anonymization of DICOM files
- **Multi-Source Support**:
  - Google Sheets-based application management
  - Google Drive file monitoring
  - Local folder monitoring
- **Flexible Output Targets**:
  - Traditional DICOM C-STORE protocol (PACS)
  - Orthanc DICOM server via REST API
- **Webhook Integration**: Real-time push notifications via Google Apps Script
- **Error Handling & Retry Logic**: Automatic retry with configurable intervals

### Advanced Features
- **Data Privacy**: Automatic DICOM anonymization
- **Resource Optimization**: Automatic cleanup of temporary files
- **Email Notifications**: Optional email alerts for processing status (configurable)
- **Comprehensive Logging**: Detailed logging with file rotation
- **Batch Processing**: Efficient multi-file handling with thread pooling
- **Connection Verification**: Automatic server connectivity testing

## System Requirements

### Software
- **Python**: 3.8 or higher
- **Operating System**: Windows, macOS, or Linux
- **Internet Connection**: Required for Google APIs and webhook mode

### APIs & Services
- **Google APIs**: Sheets API, Drive API (requires OAuth2 credentials)
- **DICOM Server**: PACS system or Orthanc server
- **Email Service** (Optional): Gmail with App Password for notifications

### Python Dependencies
See `requirements.txt` for complete list. Main dependencies:
- `pydicom`: DICOM file processing
- `pynetdicom`: DICOM network operations
- `google-api-python-client`: Google Sheets/Drive integration
- `flask`: Webhook server
- `rarfile`: RAR archive support
- `requests`: HTTP client

## Installation

### 1. Clone the Repository
```bash
git clone https://github.com/yourusername/exdicom.git
cd exdicom
```

### 2. Create Virtual Environment
```bash
# Windows
python -m venv venv
venv\Scripts\activate

# macOS/Linux
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Setup Configuration
```bash
# Copy example configuration
cp config.example.json config.json

# Edit configuration with your settings
# See Configuration section below
```

### 5. Setup Google API Credentials
1. Create a Google Cloud project
2. Enable Google Sheets API and Google Drive API
3. Create OAuth2 credentials (Desktop application)
4. Download credentials and save as `credentials.json` in project root
5. On first run, authorize the application via browser OAuth flow

## Configuration

### Basic Setup

Edit `config.json` with your settings:

```json
{
  "use_orthanc": false,
  "dicom_server": {
    "station_name": "YOUR_STATION_NAME",
    "aet": "YOUR_AET_TITLE",
    "ip": "your.pacs.server.ip",
    "port": 11112
  },
  "google": {
    "spreadsheet_id": "YOUR_SPREADSHEET_ID",
    "drive_folder_id": "YOUR_DRIVE_FOLDER_ID",
    "credentials_file": "credentials.json",
    "token_file": "token.json"
  }
}
```

### Key Configuration Options

| Option | Description |
|--------|-------------|
| `use_orthanc` | Use Orthanc server instead of traditional PACS |
| `dicom_server.station_name` | Your DICOM station name |
| `dicom_server.aet` | Application Entity Title |
| `dicom_server.ip` | PACS server IP address |
| `dicom_server.port` | PACS server port (default 11112) |
| `google.spreadsheet_id` | Google Sheets ID for application tracking |
| `google.drive_folder_id` | Google Drive folder for file uploads |
| `email.enable_notifications` | Enable email alerts |
| `processing.max_retry_attempts` | Number of retry attempts |

See `config.example.json` for all available options.

## Usage

### Basic Commands

```bash
# Run in continuous polling mode (default)
python main.py

# Run once and exit
python main.py --once

# Test DICOM server connection
python main.py --test-connection

# Use webhook mode (recommended for Google Sheets)
python main.py --webhook --webhook-port 5000

# Use local folder monitoring instead of Google Sheets
python main.py --local-mode

# Use Orthanc instead of PACS
# (Enable in config.json first)
python main.py
```

### Advanced Options

```bash
# Custom configuration file
python main.py --config my_config.json

# Set polling interval (seconds)
python main.py --interval 60

# Custom webhook host and port
python main.py --webhook --webhook-host 0.0.0.0 --webhook-port 8000
```

## Operating Modes

### 1. Continuous Polling Mode (Default)
Periodically checks Google Sheets or local folder for new files.
- Useful for low-frequency uploads
- Generates more API calls
- Less immediate response

```bash
python main.py --interval 30  # Check every 30 seconds
```

### 2. Webhook Mode (Recommended)
Google Apps Script pushes notifications when new files are available.
- Real-time processing
- Significantly fewer API calls
- Better for preventing Google API rate limits

```bash
python main.py --webhook --webhook-port 5000
```

To use webhook mode, configure Google Apps Script to POST to your webhook URL.

### 3. Local Monitoring Mode
Monitor a local folder for new DICOM files instead of using Google Sheets.

```bash
python main.py --local-mode
```

## Google Sheets Integration

### Setup Instructions

1. **Create Google Sheets Document**
   - Include columns: ID, Filename, Creation Time, Hospital Name, Status
   - Note the Spreadsheet ID from the URL

2. **Create Google Drive Folder**
   - Users upload files to this folder
   - Note the Folder ID

3. **Setup Google Apps Script** (For Webhook Mode)
   - Create a script in Google Sheets
   - Configure trigger for new file uploads
   - POST notification to your webhook URL

4. **Configure in config.json**
   ```json
   "google": {
     "spreadsheet_id": "YOUR_ID_HERE",
     "drive_folder_id": "YOUR_FOLDER_ID_HERE"
   }
   ```

## Docker Support (Optional)

A Dockerfile is included for containerized deployment:

```bash
# Build image
docker build -t exdicom .

# Run container
docker run -v $(pwd)/config.json:/app/config.json \
           -v $(pwd)/credentials.json:/app/credentials.json \
           -p 5000:5000 \
           exdicom
```

## Architecture

### Component Overview

```
┌─────────────────────────────────────────┐
│     Google Sheets / Local Folder        │
│            (Data Source)                │
└────────────────────┬────────────────────┘
                     │
        ┌────────────▼────────────┐
        │  Webhook Server /       │
        │  Polling Monitor        │
        └────────────┬────────────┘
                     │
        ┌────────────▼────────────┐
        │  Workflow Manager       │
        │  (Main Processing)      │
        └────────────┬────────────┘
                     │
        ┌────────────▼────────────┐
        │  DICOM Processor        │
        │  (Extract/Anonymize)    │
        └────────────┬────────────┘
                     │
        ┌────────────▼────────────┐
        │   DICOM Sender          │
        │   (PACS / Orthanc)      │
        └─────────────────────────┘
```

### File Processing Workflow

1. **Detection**: Identify new applications/files
2. **Download**: Retrieve files from Google Drive or local folder
3. **Processing**: Extract and anonymize DICOM data
4. **Transmission**: Send to PACS or Orthanc server
5. **Verification**: Confirm successful receipt
6. **Cleanup**: Remove temporary files and source documents
7. **Logging**: Record all actions with timestamps

## Troubleshooting

### Connection Issues
- Verify PACS/Orthanc server is accessible and running
- Check firewall rules and network connectivity
- Use `--test-connection` to diagnose DICOM connectivity

### Google API Errors
- Verify credentials.json is in correct location
- Check spreadsheet and folder IDs are correct
- Ensure APIs are enabled in Google Cloud Console
- Delete token.json to force re-authentication

### Webhook Issues
- Verify webhook URL is accessible from the internet
- Check firewall/NAT rules if behind firewall
- Use ngrok or similar tool for external access in development
- Check application logs for detailed error messages

### File Processing Errors
- Verify RAR/ZIP tools are installed (for compressed files)
- Check write permissions on processing directory
- Ensure sufficient disk space
- Review detailed logs in ./logs directory

## Performance Considerations

### Optimization Tips
- Use webhook mode instead of polling for real-time processing
- Adjust `max_workers` for Orthanc to match server capacity
- Configure appropriate `retry_delay_seconds` for your network
- Use local monitoring for high-frequency uploads
- Implement database caching for frequently accessed data

### Monitoring
- Check log files in `./logs` for processing status
- Use webhook status endpoint: `GET /webhook/status`
- Monitor disk usage due to temporary file storage
- Track email notifications for error alerts

## Security Considerations

### Best Practices
- Keep credentials.json and config.json private
- Use environment variables for sensitive data
- Enable webhook signature verification in production
- Rotate Google OAuth credentials regularly
- Restrict DICOM AET access via firewall rules
- Use HTTPS for webhook endpoints in production

### Data Privacy
- DICOM files are automatically anonymized
- Patient identifiers are removed from metadata
- Temporary files are securely deleted
- Source files are removed after successful transmission
- Enable email encryption for notifications

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/YourFeature`)
3. Commit changes (`git commit -m 'Add YourFeature'`)
4. Push to branch (`git push origin feature/YourFeature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see [LICENSE](LICENSE) file for details.

## Support & Acknowledgments

- DICOM processing powered by [pydicom](https://github.com/pydicom/pydicom)
- Network communication via [pynetdicom](https://github.com/pydicom/pynetdicom)
- Google APIs via [google-api-python-client](https://github.com/googleapis/google-api-python-client)
- Webhook server powered by [Flask](https://flask.palletsprojects.com/)

## ngrok Community License

This project uses [ngrok](https://ngrok.com/) for secure webhook tunneling in development environments. We're grateful for ngrok's community license support.

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for version history and updates.

## Contact

For issues, questions, or suggestions:
- Open an issue on GitHub
- Check existing issues and discussions
- Review documentation and troubleshooting guide

---

**Note**: This system is designed for healthcare environments and must comply with HIPAA, DICOM standards, and local healthcare data protection regulations. Ensure proper validation and testing before production deployment.
