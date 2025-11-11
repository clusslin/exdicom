/**
 * Google Apps Script - Upload Page Backend
 *
 * Functionality:
 * 1. Provides web application interface (index.html)
 * 2. Handles file uploads to Google Drive
 * 3. Records upload information to Google Sheets
 * 4. Automatically triggers webhook notification system for processing
 *
 * Deployment Instructions:
 * 1. Place this file with index.html in Apps Script project
 * 2. Deploy as Web Application
 * 3. Access: "Anyone" or "Anyone with the link"
 * 4. Execute as: "User accessing the web app" or "Me"
 */

// ========== Configuration Section ==========

// Google Drive Folder ID (for storing uploaded files)
const DRIVE_FOLDER_ID = 'YOUR_DRIVE_FOLDER_ID';

// Google Sheets ID (for recording upload information)
const SPREADSHEET_ID = 'YOUR_SPREADSHEET_ID';

// Worksheet name
const SHEET_NAME = 'upload_history';

// Webhook URL (for triggering automated processing)
const WEBHOOK_URL = 'https://your-webhook-url.com/webhook/upload';
const WEBHOOK_SECRET = 'your-webhook-secret-key';

// Administrator Email
const ADMIN_EMAIL = 'admin@example.com';

// ========== Main Web Application Functions ==========

/**
 * Handle GET requests - Display upload page
 */
function doGet(e) {
  const template = HtmlService.createTemplateFromFile('index');

  return template.evaluate()
    .setTitle('Medical Image Emergency Upload System')
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL)
    .addMetaTag('viewport', 'width=device-width, initial-scale=1');
}

/**
 * Get Google Drive API access token
 */
function getAccessToken() {
  return ScriptApp.getOAuthToken();
}

/**
 * Get Drive folder ID
 */
function getDriveFolderId() {
  return DRIVE_FOLDER_ID;
}

/**
 * Handle Resumable Upload Completion
 *
 * @param {Object} formData - Form data
 * @param {string} fileId - Google Drive file ID
 * @param {string} screenshotFileId - Screenshot file ID (optional)
 */
function handleResumableUploadComplete(formData, fileId, screenshotFileId) {
  try {
    Logger.log('Processing upload completion - File ID: ' + fileId);
    Logger.log('Screenshot ID: ' + (screenshotFileId || 'None'));
    Logger.log('Form data: ' + JSON.stringify(formData));

    // 1. Generate unique identifier
    const identifier = generateIdentifier();
    Logger.log('Generated identifier: ' + identifier);

    // 2. Rename Drive file to identifier.extension format
    try {
      const file = DriveApp.getFileById(fileId);
      const originalName = file.getName();
      // Extract file extension
      const extension = originalName.includes('.') ? originalName.substring(originalName.lastIndexOf('.')) : '';
      // New filename format: identifier.extension (e.g., 6D7CBQQK.zip)
      const newName = identifier + extension;
      file.setName(newName);
      Logger.log('File renamed: ' + originalName + ' → ' + newName);
    } catch (e) {
      Logger.log('Failed to rename file: ' + e.toString());
      // Continue execution, don't interrupt flow
    }

    // 2.5. Rename screenshot file if available
    if (screenshotFileId) {
      try {
        const screenshotFile = DriveApp.getFileById(screenshotFileId);
        const screenshotNewName = identifier + '_upload_evidence.png';
        screenshotFile.setName(screenshotNewName);
        screenshotFile.setDescription('Upload proof - Identifier: ' + identifier);
        Logger.log('Screenshot file renamed: ' + screenshotNewName);
      } catch (e) {
        Logger.log('Failed to rename screenshot file: ' + e.toString());
        // Continue execution, don't interrupt flow
      }
    }

    // 3. Record to Google Sheets
    const recordResult = recordUploadToSheet(formData, identifier, fileId);

    if (!recordResult.success) {
      Logger.log('Warning: Failed to record to spreadsheet - ' + recordResult.error);
      return {
        success: true,
        message: 'File upload successful! Identifier: ' + identifier + '\n(Recording storage encountered issues, but file was uploaded)',
        identifier: identifier,
        fileId: fileId,
        warning: recordResult.error
      };
    }

    // 4. Send email notification to uploader
    try {
      if (formData.uploaderEmail) {
        sendNotificationEmail(formData.uploaderEmail, identifier, formData.hospitalName);
        Logger.log('Email notification sent');
      }
    } catch (emailError) {
      Logger.log('Email send failed: ' + emailError.toString());
      // Don't interrupt flow, continue execution
    }

    // 5. Send webhook notification (trigger automated processing)
    try {
      sendWebhookNotificationFromUpload(formData, identifier, recordResult.rowNumber);
      Logger.log('Webhook notification sent');
    } catch (webhookError) {
      Logger.log('Webhook notification send failed: ' + webhookError.toString());
      // Don't interrupt flow, system will process in next polling cycle
    }

    // 6. Return success message
    return {
      success: true,
      message: 'Upload successful!\n\nYour identifier: ' + identifier + '\n\nThe file will be automatically anonymized and transmitted to the PACS system.\nAfter processing, it will be automatically deleted from Google Drive.\n\nConfirmation email has been sent to your inbox.',
      identifier: identifier,
      fileId: fileId,
      rowNumber: recordResult.rowNumber
    };

  } catch (error) {
    Logger.log('Error processing upload: ' + error.toString());
    Logger.log(error.stack);

    return {
      success: false,
      message: 'Error during upload processing: ' + error.message,
      error: error.toString()
    };
  }
}

/**
 * Generate unique identifier
 * Format: 8 random alphanumeric characters (uppercase)
 * Example: 6D7CBQQK
 */
function generateIdentifier() {
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789';
  let identifier = '';

  // Generate 8 random characters
  for (let i = 0; i < 8; i++) {
    const randomIndex = Math.floor(Math.random() * chars.length);
    identifier += chars[randomIndex];
  }

  return identifier;
}

/**
 * Record upload information to Google Sheets
 *
 * @param {Object} formData - Form data
 * @param {string} identifier - Unique identifier
 * @param {string} fileId - Google Drive file ID
 */
function recordUploadToSheet(formData, identifier, fileId) {
  try {
    const ss = SpreadsheetApp.openById(SPREADSHEET_ID);
    const sheet = ss.getSheetByName(SHEET_NAME);

    if (!sheet) {
      throw new Error('Worksheet not found: ' + SHEET_NAME);
    }

    // Prepare data (corresponding to columns A-I)
    const timestamp = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'yyyy-MM-dd HH:mm:ss');

    const rowData = [
      timestamp,                     // A: Creation time
      formData.hospitalName || '',   // B: Hospital name
      formData.examType || '',       // C: Exam type
      formData.uploaderName || '',   // D: Uploader name
      formData.uploaderPhone || '',  // E: Uploader phone
      formData.uploaderEmail || '',  // F: Uploader email
      formData.fileName || '',       // G: File name
      identifier,                    // H: Identifier
      ''                             // I: Transmission time (blank, to be filled after processing)
    ];

    // Append to spreadsheet
    sheet.appendRow(rowData);

    // Get the newly added row number
    const lastRow = sheet.getLastRow();

    Logger.log('Successfully recorded to spreadsheet - Row: ' + lastRow);

    return {
      success: true,
      rowNumber: lastRow
    };

  } catch (error) {
    Logger.log('Error recording to spreadsheet: ' + error.toString());
    return {
      success: false,
      error: error.message
    };
  }
}

/**
 * Send webhook notification (triggered from upload page)
 *
 * @param {Object} formData - Form data
 * @param {string} identifier - Unique identifier
 * @param {number} rowNumber - Spreadsheet row number
 */
function sendWebhookNotificationFromUpload(formData, identifier, rowNumber) {
  try {
    // Prepare payload data (compatible with system format)
    const payload = {
      identifier: identifier,
      filename: formData.fileName,
      row_number: rowNumber,
      creation_time: Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'yyyy-MM-dd HH:mm:ss'),
      hospital_name: formData.hospitalName || '',
      exam_type: formData.examType || '',
      uploader_name: formData.uploaderName || '',
      uploader_phone: formData.uploaderPhone || '',
      uploader_email: formData.uploaderEmail || '',
      timestamp: new Date().toISOString()
    };

    // Calculate signature
    const signature = calculateSignature(JSON.stringify(payload));

    // Set HTTP request options
    const options = {
      method: 'post',
      contentType: 'application/json',
      payload: JSON.stringify(payload),
      headers: {
        'X-Webhook-Signature': signature,
        'User-Agent': 'Google-Apps-Script-Upload-Page/1.0'
      },
      muteHttpExceptions: true
    };

    Logger.log('Sending webhook notification to: ' + WEBHOOK_URL);
    Logger.log('Data: ' + JSON.stringify(payload, null, 2));

    // Send HTTP POST request
    const response = UrlFetchApp.fetch(WEBHOOK_URL, options);
    const responseCode = response.getResponseCode();
    const responseText = response.getContentText();

    Logger.log('Webhook response status: ' + responseCode);
    Logger.log('Webhook response content: ' + responseText);

    if (responseCode === 200 || responseCode === 202) {
      Logger.log('Webhook notification sent successfully');
      return true;
    } else {
      Logger.log('Webhook notification send failed, status code: ' + responseCode);
      return false;
    }

  } catch (error) {
    Logger.log('Error sending webhook: ' + error.toString());
    return false;
  }
}

/**
 * Calculate HMAC-SHA256 signature
 */
function calculateSignature(payload) {
  try {
    const signature = Utilities.computeHmacSha256Signature(payload, WEBHOOK_SECRET);
    return signature.map(function(byte) {
      return ('0' + (byte & 0xFF).toString(16)).slice(-2);
    }).join('');
  } catch (error) {
    Logger.log('Error calculating signature: ' + error.toString());
    return '';
  }
}

// ========== Email Notification Functions ==========

/**
 * Send successful upload notification email to uploader
 *
 * @param {string} email - Uploader email
 * @param {string} identifier - Unique identifier
 * @param {string} hospitalName - Hospital name
 */
function sendNotificationEmail(email, identifier, hospitalName) {
  try {
    const subject = `DICOM Image Upload Confirmation - ID: ${identifier}`;
    const body = `
Dear Uploader,

Your DICOM image has been successfully uploaded!

Upload Information:
- Hospital Name: ${hospitalName}
- Identifier: ${identifier}
- Upload Time: ${Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'yyyy-MM-dd HH:mm:ss')}

Please save this identifier for future reference.
The image will be anonymized and transmitted to the designated server.

Important Notes:
- All uploaded images are automatically anonymized
- Currently supports CT and MRI image uploads only
- For questions, please contact administrator: ${ADMIN_EMAIL}

Thank you for using our service!

Medical Imaging Department
DICOM Image Processing System
    `;

    GmailApp.sendEmail(email, subject, body);
    Logger.log('Email notification sent to: ' + email);
    return true;
  } catch (error) {
    Logger.log('Failed to send email notification: ' + error.toString());
    return false;
  }
}

/**
 * Send error notification email to administrator
 *
 * @param {string} errorType - Error type
 * @param {string} errorMessage - Error message
 * @param {Object} additionalData - Additional data
 */
function sendErrorNotification(errorType, errorMessage, additionalData) {
  try {
    const subject = `[DICOM Upload System] Error Notification - ${errorType}`;
    const body = `
A system error has occurred, please handle it promptly!

Error Type: ${errorType}
Error Message: ${errorMessage}
Occurrence Time: ${Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'yyyy-MM-dd HH:mm:ss')}

Additional Data:
${JSON.stringify(additionalData, null, 2)}

Please log in to Google Apps Script to view detailed logs.

---
DICOM Image Processing System
    `;

    GmailApp.sendEmail(ADMIN_EMAIL, subject, body);
    Logger.log('Error notification email sent to administrator: ' + ADMIN_EMAIL);
    return true;
  } catch (error) {
    Logger.log('Failed to send error notification email: ' + error.toString());
    return false;
  }
}

// ========== Testing and Maintenance Functions ==========

/**
 * Test recording functionality
 */
function testRecordUpload() {
  Logger.log('========== Testing Recording Function ==========');

  const testFormData = {
    hospitalName: 'Test Hospital',
    examType: 'CT',
    uploaderName: 'Test User',
    uploaderPhone: '0912345678',
    uploaderEmail: 'test@example.com',
    fileName: 'test.zip'
  };

  const testIdentifier = 'TEST-' + Date.now();
  const testFileId = 'test-file-id-12345';

  Logger.log('Test identifier: ' + testIdentifier);

  const result = recordUploadToSheet(testFormData, testIdentifier, testFileId);

  if (result.success) {
    Logger.log('✅ Test successful! Record written to spreadsheet');
    Logger.log('   Row number: ' + result.rowNumber);
  } else {
    Logger.log('❌ Test failed: ' + result.error);
  }

  Logger.log('========================================');
}

/**
 * Test complete upload flow
 */
function testCompleteUpload() {
  Logger.log('========== Testing Complete Upload Flow ==========');

  const testFormData = {
    hospitalName: 'Test Hospital',
    examType: 'MRI',
    uploaderName: 'Test User',
    uploaderPhone: '0987654321',
    uploaderEmail: 'test@example.com',
    fileName: 'test_upload.zip',
    disclaimerAgree: 'true'
  };

  const testFileId = 'test-file-id-' + Date.now();

  Logger.log('Executing complete upload flow test...');

  const result = handleResumableUploadComplete(testFormData, testFileId);

  Logger.log('========================================');
  Logger.log('Test result:');
  Logger.log(JSON.stringify(result, null, 2));
  Logger.log('========================================');

  if (result.success) {
    Logger.log('✅ Test successful!');
    Logger.log('   Identifier: ' + result.identifier);
  } else {
    Logger.log('❌ Test failed: ' + result.error);
  }
}

/**
 * Check configuration
 */
function checkUploadPageConfiguration() {
  Logger.log('========================================');
  Logger.log('🔍 Checking Upload Page Configuration');
  Logger.log('========================================');

  // Check Drive folder
  try {
    const folder = DriveApp.getFolderById(DRIVE_FOLDER_ID);
    Logger.log('✅ Drive folder: ' + folder.getName());
    Logger.log('   Folder ID: ' + DRIVE_FOLDER_ID);
  } catch (e) {
    Logger.log('❌ Drive folder does not exist or no permission');
    Logger.log('   Folder ID: ' + DRIVE_FOLDER_ID);
  }

  // Check Sheets
  try {
    const ss = SpreadsheetApp.openById(SPREADSHEET_ID);
    const sheet = ss.getSheetByName(SHEET_NAME);
    if (sheet) {
      Logger.log('✅ Spreadsheet: ' + ss.getName());
      Logger.log('   Worksheet: ' + SHEET_NAME);
      Logger.log('   Data rows: ' + sheet.getLastRow());
    } else {
      Logger.log('❌ Worksheet not found: ' + SHEET_NAME);
    }
  } catch (e) {
    Logger.log('❌ Spreadsheet does not exist or no permission');
    Logger.log('   Spreadsheet ID: ' + SPREADSHEET_ID);
  }

  // Check Webhook URL
  Logger.log('');
  Logger.log('📡 Webhook Configuration:');
  Logger.log('   URL: ' + WEBHOOK_URL);
  Logger.log('   Secret configured: ' + (WEBHOOK_SECRET ? 'Yes' : 'No'));

  Logger.log('');
  Logger.log('========================================');
  Logger.log('💡 Next steps:');
  Logger.log('1. Deploy as Web Application');
  Logger.log('2. Test upload functionality');
  Logger.log('3. Verify webhook system receives notifications');
  Logger.log('========================================');
}

/**
 * Get deployment information
 */
function getDeploymentInfo() {
  Logger.log('========================================');
  Logger.log('📋 Deployment Information');
  Logger.log('========================================');
  Logger.log('');
  Logger.log('Deployment Steps:');
  Logger.log('1. Click "Deploy" button at top right → "New deployment"');
  Logger.log('2. Type: Select "Web application"');
  Logger.log('3. Description: Enter "DICOM Upload Page"');
  Logger.log('4. Execute as: Select "Me"');
  Logger.log('5. Access: Select "Anyone"');
  Logger.log('6. Click "Deploy"');
  Logger.log('7. Copy the "Web application URL"');
  Logger.log('');
  Logger.log('After deployment, share the URL with users!');
  Logger.log('========================================');
}
