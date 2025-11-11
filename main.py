"""
DICOM Automated Processing System
Main program integrating all components for a complete workflow
"""

import os
import sys
import json
import time
import logging
import argparse
import signal
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List

# Import custom modules
from local_drive_monitor import LocalDriveMonitor
from google_sheets_monitor import GoogleSheetsMonitor
from dicom_processor import DicomProcessor
from dicom_sender import DicomSender
from orthanc_uploader import OrthancUploader
from transfer_manager import TransferManager


class DicomWorkflowManager:
    def __init__(self, config_file: str = 'config.json', use_sheets_mode: bool = True):
        """
        Initialize DICOM workflow manager

        Args:
            config_file: Path to configuration file
            use_sheets_mode: Whether to use Google Sheets mode (default True)
        """
        self.config_file = config_file
        self.config = self.load_config()
        self.use_sheets_mode = use_sheets_mode

        # Continuous operation control variables
        self.running = True
        self.total_processed = 0
        self.total_successful = 0
        self.total_failed = 0

        # Setup logging
        self.setup_logging()
        self.logger = logging.getLogger(__name__)

        # Register signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

        # Initialize components
        self.init_components()

        self.logger.info("DICOM automated processing system initialization complete")

    def signal_handler(self, signum, frame):
        """Handle interrupt signal"""
        self.logger.info(f"Received signal {signum}, shutting down gracefully...")
        self.running = False

    def load_config(self) -> Dict:
        """Load configuration file"""
        if not os.path.exists(self.config_file):
            self.create_default_config()

        with open(self.config_file, 'r', encoding='utf-8') as f:
            return json.load(f)

    def create_default_config(self):
        """Create default configuration file"""
        default_config = {
            "dicom_server": {
                "station_name": "EXDICOM",
                "aet": "EXDICOM",
                "ip": "localhost",
                "port": 11112
            },
            "google": {
                "spreadsheet_id": "YOUR_SPREADSHEET_ID",
                "drive_folder_id": "YOUR_DRIVE_FOLDER_ID",
                "credentials_file": "credentials.json",
                "token_file": "token.json"
            },
            "email": {
                "enable_notifications": False,
                "sender_email": "",
                "admin_email": "admin@example.com",
                "smtp_server": "smtp.gmail.com",
                "smtp_port": 587,
                "use_tls": True,
                "smtp_username": "",
                "smtp_password": ""
            },
            "directories": {
                "downloads": "./downloads",
                "processing": "./processing",
                "logs": "./logs"
            },
            "local_drive": {
                "monitor_folder": "./monitor",
                "auto_delete_after_processing": True
            },
            "processing": {
                "max_retry_attempts": 1,
                "retry_delay_seconds": 30,
                "verification_timeout_minutes": 10,
                "cleanup_old_files_days": 7
            },
            "logging": {
                "level": "INFO",
                "max_file_size_mb": 10,
                "backup_count": 5
            }
        }

        with open(self.config_file, 'w', encoding='utf-8') as f:
            json.dump(default_config, f, indent=2, ensure_ascii=False)

        print(f"Default configuration file created: {self.config_file}")
        print("Please update the configuration file with your settings and run again")

    def setup_logging(self):
        """Setup logging system"""
        log_dir = Path(self.config['directories']['logs'])
        log_dir.mkdir(exist_ok=True)

        log_file = log_dir / f"dicom_workflow_{datetime.now().strftime('%Y%m%d')}.log"

        # Setup log format
        log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

        # Setup log level
        log_level = getattr(logging, self.config['logging']['level'], logging.INFO)

        # Configure logging
        logging.basicConfig(
            level=log_level,
            format=log_format,
            handlers=[
                logging.FileHandler(log_file, encoding='utf-8'),
                logging.StreamHandler(sys.stdout)
            ]
        )

    def init_components(self):
        """Initialize all components"""
        try:
            if self.use_sheets_mode:
                # Use Google Sheets monitoring mode
                self.downloader = GoogleSheetsMonitor(
                    credentials_file=self.config['google']['credentials_file'],
                    spreadsheet_id=self.config['google']['spreadsheet_id'],
                    drive_folder_id=self.config['google']['drive_folder_id'],
                    download_folder=self.config['directories']['downloads']
                )
                self.logger.info("Google Sheets monitor initialized")
            else:
                # Use local Google Drive monitoring mode
                monitor_folder = self.config.get('local_drive', {}).get(
                    'monitor_folder',
                    "./monitor"
                )
                self.downloader = LocalDriveMonitor(
                    monitor_folder=monitor_folder,
                    download_folder=self.config['directories']['downloads']
                )
                self.logger.info(f"Local Drive monitor initialized, monitoring directory: {monitor_folder}")

            # Initialize processor
            self.processor = DicomProcessor(
                work_folder=self.config['directories']['processing']
            )

            # Initialize sender (choose between Orthanc or traditional DICOM sender)
            self.use_orthanc = self.config.get('use_orthanc', False)

            if self.use_orthanc:
                orthanc_config = self.config.get('orthanc', {})
                self.sender = OrthancUploader(
                    orthanc_url=orthanc_config.get('url', 'http://localhost:8042'),
                    username=orthanc_config.get('username') or None,
                    password=orthanc_config.get('password') or None,
                    orthanc_import_path=orthanc_config.get('orthanc_import_path') or None,
                    max_workers=orthanc_config.get('max_workers', 10)
                )
                self.logger.info(f"Using Orthanc upload mode (worker threads: {orthanc_config.get('max_workers', 10)})")
            else:
                self.sender = DicomSender(self.config['dicom_server'])
                self.logger.info("Using traditional DICOM C-STORE mode")

            # Initialize transfer manager
            email_config = self.config['email'] if self.config['email']['enable_notifications'] else None

            self.transfer_manager = TransferManager(
                server_config=self.config['dicom_server'],
                google_config=self.config['google'],
                email_config=email_config,
                credentials_file=self.config['google']['credentials_file'],
                token_file=self.config['google']['token_file']
            )

            self.logger.info("All components initialized successfully")

        except Exception as e:
            self.logger.error(f"Component initialization failed: {e}")
            raise

    def process_single_workflow(self, file_info: Dict) -> bool:
        """
        Process a single workflow

        Args:
            file_info: File information

        Returns:
            Whether processing was successful
        """
        patient_id = file_info['record']['id']
        filename = file_info['original_filename']

        self.logger.info(f"Starting workflow - Patient ID: {patient_id}, File: {filename}")

        try:
            # 1. Process file (extract, anonymize)
            processing_result = self.processor.process_file(file_info)

            if not processing_result['success']:
                self.logger.error(f"File processing failed: {processing_result.get('error_message', 'Unknown error')}")
                self.transfer_manager.send_error_notification(
                    "File processing failed",
                    processing_result.get('error_message', 'Unknown error'),
                    file_info['record']
                )
                return False

            # 2. Send DICOM files
            processed_files = [item['output_path'] for item in processing_result['processed_files']]

            if not processed_files:
                self.logger.error("No files available to send")
                return False

            # Retry mechanism
            max_retries = self.config['processing']['max_retry_attempts']
            retry_delay = self.config['processing']['retry_delay_seconds']

            send_success = False
            for attempt in range(max_retries):
                self.logger.info(f"Attempting to send files ({attempt + 1}/{max_retries})")

                send_result = self.sender.send_batch(processed_files)

                if send_result['successful'] == send_result['total_files']:
                    self.logger.info("All files sent successfully")
                    send_success = True
                    break
                else:
                    self.logger.warning(
                        f"Send failed - Successful: {send_result['successful']}, "
                        f"Failed: {send_result['failed']}"
                    )

                    if attempt < max_retries - 1:
                        self.logger.info(f"Waiting {retry_delay} seconds before retry...")
                        time.sleep(retry_delay)

            if not send_success:
                self.logger.error("File send failed after all attempts")
                self.transfer_manager.send_error_notification(
                    "DICOM file send failed",
                    f"Failed after {max_retries} attempts",
                    file_info['record']
                )
                return False

            # 3. Complete transfer process (verify, cleanup)
            if self.transfer_manager.complete_transfer_process(processing_result):
                self.logger.info(f"Workflow completed - Patient ID: {patient_id}")

                # Delete source file to save space
                try:
                    self.downloader.delete_source_file(file_info)
                    self.logger.info(f"Source file deleted to save space: {file_info['original_filename']}")
                except Exception as delete_error:
                    self.logger.warning(f"Error deleting source file: {delete_error}")

                # Cleanup processing directory
                self.logger.info("Cleaning up processing directory...")
                try:
                    processing_folder = Path(self.config['directories']['processing'])
                    if processing_folder.exists() and processing_folder.is_dir():
                        shutil.rmtree(processing_folder)
                        processing_folder.mkdir(parents=True)
                        self.logger.info(f"Processing directory cleaned: {processing_folder}")
                except Exception as e:
                    self.logger.warning(f"Error cleaning processing directory: {e}")

                return True
            else:
                self.logger.error(f"Transfer process completion failed - Patient ID: {patient_id}")
                return False

        except Exception as e:
            self.logger.error(f"Error processing workflow: {e}")
            self.transfer_manager.send_error_notification(
                "Workflow execution error",
                str(e),
                file_info['record']
            )
            return False

    def process_sheets_application(self, application: Dict) -> bool:
        """
        Process a single application from Google Sheets

        Args:
            application: Application information

        Returns:
            Whether processing was successful
        """
        identifier = application['identifier']
        filename = application['filename']

        self.logger.info(f"Starting application processing - ID: {identifier}, File: {filename}")

        try:
            # 1. Find file in Google Drive
            self.logger.info(f"Finding file in Google Drive...")
            file_id = self.downloader.find_file_in_drive(identifier)
            if not file_id:
                self.logger.error(f"File not found in Google Drive: {identifier}")
                return False

            self.logger.info(f"File found, starting download...")

            # 2. Download file locally
            local_path = self.downloader.download_file_from_drive(file_id, filename, identifier)
            if not local_path:
                self.logger.error(f"File download failed: {filename}")
                return False

            self.logger.info(f"File download complete, starting DICOM processing...")

            # 3. Create file processing information
            file_info = self.downloader.create_file_info_for_processing(application, local_path)
            file_info['drive_file_id'] = file_id

            # 4. Process file (extract, anonymize)
            self.logger.info(f"Starting file processing...")
            processing_result = self.processor.process_file(file_info)

            if not processing_result['success']:
                self.logger.error(f"File processing failed: {processing_result.get('error_message', 'Unknown error')}")
                self.downloader.cleanup_local_file(local_path)
                return False

            # 5. Send DICOM files
            processed_files = [item['output_path'] for item in processing_result['processed_files']]

            if not processed_files:
                self.logger.error("No files available to send")
                self.downloader.cleanup_local_file(local_path)
                return False

            self.logger.info(f"File processing complete, {len(processed_files)} DICOM files ready for transmission...")

            # Retry mechanism
            max_retries = self.config['processing']['max_retry_attempts']
            retry_delay = self.config['processing']['retry_delay_seconds']

            send_success = False
            for attempt in range(max_retries):
                if attempt == 0:
                    if self.use_orthanc:
                        self.logger.info(f"Starting DICOM upload to Orthanc...")
                    else:
                        self.logger.info(f"Starting DICOM send to PACS server...")
                else:
                    self.logger.info(f"Retrying file send ({attempt + 1}/{max_retries})")

                # Choose send method based on mode
                if self.use_orthanc:
                    send_result = self.sender.upload_batch_via_api(processed_files)
                else:
                    send_result = self.sender.send_batch(processed_files)

                if send_result['successful'] == send_result['total_files']:
                    if self.use_orthanc:
                        self.logger.info(f"All DICOM files uploaded to Orthanc successfully ({send_result['successful']}/{send_result['total_files']})")
                    else:
                        self.logger.info(f"All DICOM files sent successfully ({send_result['successful']}/{send_result['total_files']})")
                    send_success = True
                    break
                elif send_result['successful'] > 0:
                    # If some files succeeded, consider it partial success
                    success_rate = (send_result['successful'] / send_result['total_files']) * 100
                    if success_rate >= 80:  # 80% success rate is acceptable
                        if self.use_orthanc:
                            self.logger.info(f"Most DICOM files uploaded to Orthanc successfully ({send_result['successful']}/{send_result['total_files']}, {success_rate:.1f}%)")
                        else:
                            self.logger.info(f"Most DICOM files sent successfully ({send_result['successful']}/{send_result['total_files']}, {success_rate:.1f}%)")
                        send_success = True
                        break
                    else:
                        self.logger.warning(
                            f"Partial send failure - Successful: {send_result['successful']}/{send_result['total_files']}, "
                            f"Success rate: {success_rate:.1f}%"
                        )
                else:
                    self.logger.warning(
                        f"File send failed - Successful: {send_result['successful']}/{send_result['total_files']}, "
                        f"Failed: {send_result['failed']}"
                    )

                    # Show failed files
                    if send_result['failed_files']:
                        self.logger.warning("Failed files:")
                        for failed_file in send_result['failed_files'][:3]:
                            self.logger.warning(f"  - {failed_file}")
                        if len(send_result['failed_files']) > 3:
                            self.logger.warning(f"  ... and {len(send_result['failed_files']) - 3} more files")

                    if attempt < max_retries - 1:
                        self.logger.info(f"Waiting {retry_delay} seconds before retry...")
                        time.sleep(retry_delay)

            if not send_success:
                self.logger.error("File send failed after all attempts")
                self.downloader.cleanup_local_file(local_path)
                return False

            # 6. Update Google Sheets transmission time
            self.logger.info("Updating Google Sheets transmission time...")
            if not self.downloader.update_transmission_time(application['row_number'], identifier):
                self.logger.warning("Update transmission time failed, but files were sent successfully")

            # 7. Clean up Google Drive files
            self.logger.info("Cleaning up Google Drive files...")
            try:
                self._delete_drive_file_with_user_auth(file_id, identifier)
            except Exception as cleanup_error:
                self.logger.warning(f"Could not delete Google Drive file: {cleanup_error}")

            # 8. Clean up local temporary files
            self.logger.info("Cleaning up local temporary files...")
            self.downloader.cleanup_local_file(local_path)

            # Clean up processing work directory
            if 'output_directory' in processing_result:
                try:
                    shutil.rmtree(processing_result['output_directory'])
                    self.logger.info(f"Processing work directory cleaned: {processing_result['output_directory']}")
                except Exception as e:
                    self.logger.warning(f"Error cleaning processing work directory: {e}")

            # Clean up entire processing directory
            self.logger.info("Cleaning up entire processing directory...")
            try:
                processing_folder = Path(self.config['directories']['processing'])
                if processing_folder.exists() and processing_folder.is_dir():
                    shutil.rmtree(processing_folder)
                    processing_folder.mkdir(parents=True)
                    self.logger.info(f"Processing directory cleaned: {processing_folder}")
            except Exception as e:
                self.logger.warning(f"Error cleaning processing directory: {e}")

            self.logger.info("=" * 50)
            self.logger.info(f"✓ Application processing complete - ID: {identifier}")
            if self.use_orthanc:
                self.logger.info(f"✓ {len(processed_files)} DICOM files uploaded to Orthanc")
            else:
                self.logger.info(f"✓ {len(processed_files)} DICOM files sent to PACS")
            self.logger.info(f"✓ Google Sheets transmission time updated")
            self.logger.info(f"✓ Google Drive files cleaned up")
            self.logger.info(f"✓ All temporary files cleaned up")
            self.logger.info("=" * 50)
            return True

        except Exception as e:
            self.logger.error(f"Error processing application: {e}")
            return False

    def run_sheets_workflow(self) -> Dict:
        """
        Execute Google Sheets-based workflow

        Returns:
            Execution result statistics
        """
        self.logger.info("Starting Google Sheets workflow execution")

        stats = {
            'start_time': datetime.now(),
            'pending_applications': 0,
            'processed_files': 0,
            'successful_transfers': 0,
            'failed_transfers': 0
        }

        try:
            # 1. Test connection
            if not self.sender.test_connection():
                if self.use_orthanc:
                    raise Exception("Unable to connect to Orthanc server")
                else:
                    raise Exception("Unable to connect to DICOM server")

            # 2. Get pending applications
            pending_applications = self.downloader.get_pending_applications()

            stats['pending_applications'] = len(pending_applications)

            if not pending_applications:
                self.logger.info("No pending applications")
                return stats

            # 3. Process each application
            for application in pending_applications:
                self.logger.info(f"Processing application: {application['identifier']} - {application['filename']}")

                success = self.process_sheets_application(application)

                if success:
                    stats['successful_transfers'] += 1
                else:
                    stats['failed_transfers'] += 1

                stats['processed_files'] += 1

        except Exception as e:
            self.logger.error(f"Critical error during Google Sheets workflow execution: {e}")

        finally:
            stats['end_time'] = datetime.now()
            stats['duration'] = stats['end_time'] - stats['start_time']

            self.log_sheets_statistics(stats)

        return stats

    def log_sheets_statistics(self, stats: Dict):
        """Log Google Sheets workflow statistics"""
        self.logger.info("=" * 60)
        self.logger.info("Google Sheets workflow execution complete")
        self.logger.info("=" * 60)
        self.logger.info(f"Execution time: {stats['duration']}")
        self.logger.info(f"Pending applications: {stats['pending_applications']}")
        self.logger.info(f"Files processed: {stats['processed_files']}")
        self.logger.info(f"Successful transfers: {stats['successful_transfers']}")
        self.logger.info(f"Failed transfers: {stats['failed_transfers']}")
        if stats['processed_files'] > 0:
            success_rate = (stats['successful_transfers'] / stats['processed_files']) * 100
            self.logger.info(f"Success rate: {success_rate:.1f}%")
        self.logger.info("=" * 60)

    def run_full_workflow(self) -> Dict:
        """
        Execute complete workflow

        Returns:
            Execution result statistics
        """
        if self.use_sheets_mode:
            return self.run_sheets_workflow()
        else:
            return self.run_local_workflow()

    def run_local_workflow(self) -> Dict:
        """
        Execute local monitoring workflow (original logic)

        Returns:
            Execution result statistics
        """
        self.logger.info("Starting local DICOM processing workflow")

        stats = {
            'start_time': datetime.now(),
            'downloaded_files': 0,
            'processed_files': 0,
            'successful_transfers': 0,
            'failed_transfers': 0,
            'total_files': 0
        }

        try:
            # 1. Test connection
            if not self.sender.test_connection():
                if self.use_orthanc:
                    raise Exception("Unable to connect to Orthanc server")
                else:
                    raise Exception("Unable to connect to DICOM server")

            # 2. Detect and copy pending files
            downloaded_files = self.downloader.download_pending_files()

            stats['downloaded_files'] = len(downloaded_files)
            stats['total_files'] = len(downloaded_files)

            if not downloaded_files:
                self.logger.info("No pending files to process")
                return stats

            # 3. Process each file
            for file_info in downloaded_files:
                self.logger.info(f"Processing file: {file_info['original_filename']}")

                success = self.process_single_workflow(file_info)

                if success:
                    stats['successful_transfers'] += 1
                else:
                    stats['failed_transfers'] += 1

                stats['processed_files'] += 1

            # 4. Clean up old files
            self.cleanup_old_files()

            # Clean up downloads directory
            if hasattr(self.downloader, 'clean_downloads'):
                self.downloader.clean_downloads(self.config['processing']['cleanup_old_files_days'])

        except Exception as e:
            self.logger.error(f"Critical error during workflow execution: {e}")

            if hasattr(self, 'transfer_manager'):
                self.transfer_manager.send_error_notification(
                    "System critical error",
                    str(e)
                )

        finally:
            stats['end_time'] = datetime.now()
            stats['duration'] = stats['end_time'] - stats['start_time']

            self.log_final_statistics(stats)

        return stats

    def cleanup_old_files(self):
        """Clean up old files"""
        try:
            cleanup_days = self.config['processing']['cleanup_old_files_days']

            # Clean up downloads directory
            if hasattr(self.downloader, 'clean_downloads'):
                self.downloader.clean_downloads(cleanup_days)

            # Clean up processing work directory
            self.processor.cleanup_work_directory(cleanup_days)

            self.logger.info("Old file cleanup complete")

        except Exception as e:
            self.logger.error(f"Error cleaning up old files: {e}")

    def _delete_drive_file_with_user_auth(self, file_id: str, identifier: str):
        """
        Delete Google Drive file using user authentication

        Args:
            file_id: Google Drive file ID
            identifier: Identifier (for logging)
        """
        try:
            import pickle
            from google.auth.transport.requests import Request
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build

            # Set required permissions
            SCOPES = ['https://www.googleapis.com/auth/drive']

            creds = None
            token_file = 'user_token.pickle'
            credentials_file = 'user_credentials.json'

            # Check for saved token
            if os.path.exists(token_file):
                with open(token_file, 'rb') as token:
                    creds = pickle.load(token)

            # If no valid credentials, skip deletion
            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                    # Update token
                    with open(token_file, 'wb') as token:
                        pickle.dump(creds, token)
                else:
                    self.logger.warning("No valid user authentication, skipping Google Drive file deletion")
                    return

            # Build Drive service
            drive_service = build('drive', 'v3', credentials=creds)

            # Try moving to trash
            try:
                drive_service.files().update(
                    fileId=file_id,
                    body={'trashed': True}
                ).execute()
                self.logger.info(f"Google Drive file moved to trash: {identifier}")
                return
            except Exception as trash_error:
                self.logger.debug(f"Move to trash failed: {trash_error}")

            # Try permanent deletion
            try:
                drive_service.files().delete(fileId=file_id).execute()
                self.logger.info(f"Google Drive file permanently deleted: {identifier}")
                return
            except Exception as delete_error:
                self.logger.warning(f"Permanent deletion failed: {delete_error}")

        except ImportError:
            self.logger.warning("Missing required Google authentication packages, skipping Drive file deletion")
        except Exception as e:
            self.logger.warning(f"Error deleting Drive file: {e}")

    def log_final_statistics(self, stats: Dict):
        """Log final statistics"""
        self.logger.info("=" * 60)
        self.logger.info("Workflow execution complete")
        self.logger.info("=" * 60)
        self.logger.info(f"Execution time: {stats['duration']}")
        self.logger.info(f"Files downloaded: {stats['downloaded_files']}")
        self.logger.info(f"Files processed: {stats['processed_files']}")
        self.logger.info(f"Successful transfers: {stats['successful_transfers']}")
        self.logger.info(f"Failed transfers: {stats['failed_transfers']}")
        self.logger.info(f"Success rate: {stats['successful_transfers'] / max(1, stats['total_files']) * 100:.1f}%")
        self.logger.info("=" * 60)

    def run_continuous_mode(self, check_interval: int = 30):
        """
        Run in continuous mode

        Args:
            check_interval: Check interval in seconds (default 30)
        """
        self.logger.info("=" * 60)
        mode_name = "Google Sheets monitoring mode" if self.use_sheets_mode else "Local monitoring mode"
        self.logger.info(f"Starting continuous operation mode - {mode_name}")
        self.logger.info("=" * 60)
        self.logger.info(f"Check interval: {check_interval} seconds ({check_interval/60:.1f} minutes)")
        self.logger.info("Press Ctrl+C to stop the program")
        self.logger.info("=" * 60)

        start_time = datetime.now()
        cycle_count = 0

        while self.running:
            cycle_count += 1
            cycle_start = datetime.now()

            self.logger.info(f"Starting check cycle {cycle_count}")

            try:
                # Execute complete workflow
                stats = self.run_full_workflow()

                # Update statistics
                self.total_processed += stats['processed_files']
                self.total_successful += stats['successful_transfers']
                self.total_failed += stats['failed_transfers']

                # Log results
                if stats['processed_files'] > 0:
                    self.logger.info(
                        f"This cycle processed {stats['processed_files']} files, "
                        f"successful: {stats['successful_transfers']}, "
                        f"failed: {stats['failed_transfers']}"
                    )
                else:
                    self.logger.info("No pending files in this cycle")

            except Exception as e:
                self.logger.error(f"Error during cycle execution: {e}")
                self.total_failed += 1

            if not self.running:
                break

            # Calculate next check time
            cycle_end = datetime.now()
            cycle_duration = (cycle_end - cycle_start).total_seconds()

            if cycle_duration < check_interval:
                sleep_time = check_interval - cycle_duration
                next_check = datetime.now() + timedelta(seconds=sleep_time)

                self.logger.info(
                    f"Cycle completed in {cycle_duration:.1f} seconds, "
                    f"next check at {next_check.strftime('%H:%M:%S')}"
                )

                # Split sleep into 1-second intervals for responsive shutdown
                for _ in range(int(sleep_time)):
                    if not self.running:
                        break
                    time.sleep(1)

                # Handle fractional seconds
                if self.running and (sleep_time % 1) > 0:
                    time.sleep(sleep_time % 1)
            else:
                self.logger.warning(f"Cycle completed in {cycle_duration:.1f} seconds, exceeding interval")

        # Program end statistics
        end_time = datetime.now()
        total_duration = end_time - start_time

        self.logger.info("=" * 60)
        self.logger.info("Continuous operation mode statistics")
        self.logger.info("=" * 60)
        self.logger.info(f"Total runtime: {total_duration}")
        self.logger.info(f"Total cycles: {cycle_count}")
        self.logger.info(f"Total files processed: {self.total_processed}")
        self.logger.info(f"Total successful: {self.total_successful}")
        self.logger.info(f"Total failed: {self.total_failed}")
        if self.total_processed > 0:
            success_rate = (self.total_successful / self.total_processed) * 100
            self.logger.info(f"Overall success rate: {success_rate:.1f}%")
        self.logger.info("=" * 60)


def main():
    """Main program entry point"""
    parser = argparse.ArgumentParser(description='DICOM Automated Processing System')
    parser.add_argument('--config', default='config.json', help='Configuration file path')
    parser.add_argument('--test-connection', action='store_true', help='Test DICOM server connection only')
    parser.add_argument('--download-only', action='store_true', help='Download files only, no processing')
    parser.add_argument('--cleanup-only', action='store_true', help='Cleanup only')
    parser.add_argument('--once', action='store_true', help='Run once (non-continuous mode)')
    parser.add_argument('--interval', type=int, default=30, help='Check interval in seconds (default 30)')
    parser.add_argument('--local-mode', action='store_true', help='Use local monitoring mode (default Google Sheets mode)')
    parser.add_argument('--webhook', action='store_true', help='Enable webhook mode (wait for Google Apps Script push notification)')
    parser.add_argument('--webhook-port', type=int, default=5000, help='Webhook server port (default 5000)')
    parser.add_argument('--webhook-host', type=str, default='0.0.0.0', help='Webhook server host (default 0.0.0.0)')

    args = parser.parse_args()

    try:
        # Create workflow manager
        use_sheets_mode = not args.local_mode  # Default to Google Sheets mode
        workflow_manager = DicomWorkflowManager(args.config, use_sheets_mode=use_sheets_mode)

        if args.test_connection:
            # Test connection
            print("Testing DICOM server connection...")
            if workflow_manager.sender.test_connection():
                print("Connection successful")
                return 0
            else:
                print("Connection failed")
                return 1

        elif args.download_only:
            # Download files only
            print("Running file detection and copy...")
            downloaded_files = workflow_manager.downloader.download_pending_files()
            print(f"Detection complete, {len(downloaded_files)} files found")
            return 0

        elif args.cleanup_only:
            # Cleanup only
            print("Running cleanup...")
            workflow_manager.cleanup_old_files()
            print("Cleanup complete")
            return 0

        elif args.once:
            # Single execution mode
            print("Running single workflow...")
            stats = workflow_manager.run_full_workflow()

            # Decide exit code based on results
            if stats['failed_transfers'] == 0:
                return 0  # All successful
            elif stats['successful_transfers'] > 0:
                return 2  # Partial success
            else:
                return 1  # All failed

        else:
            # Check if webhook mode is enabled
            if args.webhook:
                # Webhook mode: start HTTP server and wait for push notifications
                from webhook_server import create_webhook_server

                print("=" * 60)
                print("Starting webhook mode (push notification mode)")
                print("=" * 60)
                print(f"Webhook server: http://{args.webhook_host}:{args.webhook_port}")
                print("Waiting for Google Apps Script push notifications...")
                print("Press Ctrl+C to stop the program")
                print()

                # Create and start webhook server
                webhook_server = create_webhook_server(
                    port=args.webhook_port,
                    host=args.webhook_host,
                    enable_auth=False
                )

                # Set workflow manager
                webhook_server.set_workflow_manager(workflow_manager)

                # Start server (background thread)
                webhook_server.start()

                # Main thread waits (keeps program running)
                try:
                    while workflow_manager.running:
                        time.sleep(1)
                except KeyboardInterrupt:
                    print("\nProgram interrupted by user")
                    workflow_manager.running = False

                return 0

            else:
                # Default continuous mode (polling mode)
                mode_name = "Google Sheets monitoring mode" if use_sheets_mode else "Local monitoring mode"
                print(f"Starting {mode_name}, check interval: {args.interval} seconds ({args.interval/60:.1f} minutes)")
                print("Press Ctrl+C to stop the program")
                print("For single execution, use --once parameter")
                print()
                print("Tip: Use --webhook mode to avoid frequent polling that may trigger Google rate limits")

                if use_sheets_mode:
                    print("Mode: Check for new applications in Google Sheets every 30 seconds")
                    print("Processing flow: Google Sheets → Find Drive files → Download → Process → Anonymize → Upload → Mark time → Delete Drive files")
                else:
                    monitor_folder = workflow_manager.config.get('local_drive', {}).get(
                        'monitor_folder', "./monitor"
                    )
                    print(f"Monitoring directory: {monitor_folder}")
                    print("Source files will be automatically deleted after processing to save space")

                workflow_manager.run_continuous_mode(args.interval)
                return 0

    except KeyboardInterrupt:
        print("\nProgram interrupted by user")
        return 130

    except Exception as e:
        print(f"Error during program execution: {e}")
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
