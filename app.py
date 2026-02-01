import streamlit as st

# ============================================================================
# PAGE CONFIGURATION - MUST BE FIRST STREAMLIT COMMAND
# ============================================================================
st.set_page_config(
    page_title="DAV Project Form",
    page_icon="🎓",
    layout="centered",
    initial_sidebar_state="collapsed"
)

# ============================================================================
# IMPORTS
# ============================================================================
import re
from firebase_admin import credentials, firestore, initialize_app
import firebase_admin
from typing import Dict, Tuple, List, Optional
import time
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import logging

# ============================================================================
# LOGGING CONFIGURATION
# ============================================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================================================
# FIREBASE INITIALIZATION
# ============================================================================

@st.cache_resource
def init_firebase():
    """
    Initialize Firebase and return the Firestore client.
    Works with both local secrets.toml and environment variables.
    """
    if not firebase_admin._apps:
        try:
            fb_creds = st.secrets["firebase"]
            private_key = fb_creds["private_key"].replace("\\n", "\n")
            
            cred_dict = {
                "type": fb_creds["type"],
                "project_id": fb_creds["project_id"],
                "private_key_id": fb_creds["private_key_id"],
                "private_key": private_key,
                "client_email": fb_creds["client_email"],
                "client_id": fb_creds["client_id"],
                "auth_uri": fb_creds["auth_uri"],
                "token_uri": fb_creds["token_uri"],
                "auth_provider_x509_cert_url": fb_creds["auth_provider_x509_cert_url"],
                "client_x509_cert_url": fb_creds["client_x509_cert_url"]
            }
            
            cred = credentials.Certificate(cred_dict)
            firebase_admin.initialize_app(cred)
            logger.info("Firebase initialized successfully")
            
        except Exception as e:
            logger.error(f"Firebase initialization failed: {e}")
            st.error("⚠️ Database connection failed. Please contact support.")
            st.stop()
    
    return firestore.client()

# ============================================================================
# VALIDATION FUNCTIONS
# ============================================================================

class ValidationError(Exception):
    """Custom exception for validation errors"""
    pass

class Validator:
    """Centralized validation class with all validation methods"""
    
    @staticmethod
    def validate_email(email: str) -> Tuple[bool, str]:
        """Validate email format"""
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        email = email.strip()
        
        if not email:
            return False, "Email ID is required"
        if not re.match(pattern, email):
            return False, "Invalid email format (e.g., user@example.com)"
        if len(email) > 254:  # RFC 5321
            return False, "Email address is too long"
        return True, ""

    @staticmethod
    def validate_enrollment(enrollment: str) -> Tuple[bool, str]:
        """Validate enrollment number"""
        pattern = r'^\d{12}$'
        enrollment = enrollment.strip()
        
        if not enrollment:
            return False, "Enrollment Number is required"
        if not re.match(pattern, enrollment):
            return False, "Enrollment Number must be exactly 12 digits"
        return True, ""

    @staticmethod
    def validate_name(name: str) -> Tuple[bool, str]:
        """Validate full name"""
        pattern = r'^[a-zA-Z\s]+$'
        name = name.strip()
        
        if not name:
            return False, "Full Name is required"
        if not re.match(pattern, name):
            return False, "Full Name can only contain letters and spaces"
        if len(name) < 2:
            return False, "Full Name must be at least 2 characters"
        if len(name) > 100:
            return False, "Full Name is too long (max 100 characters)"
        return True, ""

    @staticmethod
    def validate_contact(contact: str) -> Tuple[bool, str]:
        """Validate contact number"""
        pattern = r'^\d{10}$'
        contact = contact.strip()
        
        if not contact:
            return False, "Contact Number is required"
        if not re.match(pattern, contact):
            return False, "Contact Number must be exactly 10 digits"
        # Check if all digits are the same (invalid)
        if len(set(contact)) == 1:
            return False, "Contact Number appears to be invalid"
        return True, ""

    @staticmethod
    def validate_project_name(project_name: str) -> Tuple[bool, str]:
        """Validate project name"""
        project_name = project_name.strip()
        
        if not project_name:
            return False, "Project Name is required"
        if len(project_name) < 3:
            return False, "Project Name must be at least 3 characters"
        if len(project_name) > 200:
            return False, "Project Name is too long (max 200 characters)"
        return True, ""

    @staticmethod
    def validate_url(url: str) -> Tuple[bool, str]:
        """Validate source URL"""
        pattern = r'^https?://[^\s/$.?#].[^\s]*$'
        url = url.strip()
        
        if not url:
            return False, "Source URL is required"
        if not re.match(pattern, url, re.IGNORECASE):
            return False, "URL must start with http:// or https://"
        if len(url) > 2048:
            return False, "URL is too long"
        return True, ""
    
    @classmethod
    def validate_all(cls, data: Dict) -> Tuple[bool, List[str]]:
        """Validate all fields at once and return all errors"""
        errors = []
        
        validations = [
            ("Email", cls.validate_email(data.get('email', ''))),
            ("Enrollment", cls.validate_enrollment(data.get('enrollment_number', ''))),
            ("Name", cls.validate_name(data.get('full_name', ''))),
            ("Contact", cls.validate_contact(data.get('contact_number', ''))),
            ("Project Name", cls.validate_project_name(data.get('project_name', ''))),
            ("URL", cls.validate_url(data.get('source_url', '')))
        ]
        
        for field_name, (valid, error_msg) in validations:
            if not valid and error_msg:
                errors.append(f"{field_name}: {error_msg}")
        
        return len(errors) == 0, errors

# ============================================================================
# DUPLICATE CHECK RESULT CLASS
# ============================================================================

class DuplicateCheckResult:
    """Data class to hold duplicate check results"""
    def __init__(self):
        self.is_duplicate = False
        self.duplicate_fields = []
        self.messages = []
        self.existing_data = {}
    
    def add_duplicate(self, field_name: str, field_value: str, existing_value: str = None):
        """Add a duplicate field to the result"""
        self.is_duplicate = True
        self.duplicate_fields.append(field_name)
        display_value = existing_value if existing_value else field_value
        self.messages.append(f"**{field_name}**: `{display_value}` already exists")
        if existing_value:
            self.existing_data[field_name] = existing_value

# ============================================================================
# DATABASE OPERATIONS
# ============================================================================

class DatabaseManager:
    """Handle all database operations"""
    
    def __init__(self, db):
        self.db = db
        self.collection = 'project_submissions'
    
    def check_for_duplicates(self, data: Dict) -> DuplicateCheckResult:
        """
        Comprehensive duplicate checking across multiple fields.
        Checks: enrollment_number, email, contact_number
        Returns DuplicateCheckResult with detailed information
        """
        result = DuplicateCheckResult()
        
        try:
            # Normalize inputs for case-insensitive comparison
            full_name = data.get('full_name', '').strip().lower()
            source_url = data.get('source_url', '').strip().lower()
            enrollment = data.get('enrollment_number', '').strip()
            email = data.get('email', '').strip().lower()
            contact = data.get('contact_number', '').strip()
            source_url = data.get('source_url', '').strip().lower()
            
            # Skip if fields are empty
            if not enrollment or not email or not contact or not full_name or not source_url:
                logger.warning("Empty fields provided for duplicate check")
                return result
            
            logger.info(f"Checking for duplicates: enrollment={enrollment}, email={email}, contact={contact}, source_url={source_url}, name={full_name}")
            
            # Get all documents from collection
            docs = self.db.collection(self.collection).stream()
            
            for doc in docs:
                doc_data = doc.to_dict()

                # Check full name (case-insensitive)
                existing_name = doc_data.get('full_name', '').strip().lower()
                if existing_name == full_name:
                    result.add_duplicate('Full Name', full_name, doc_data.get('full_name'))
                    logger.warning(f"Duplicate name found: {full_name}")

                # Check source URL (case-insensitive)
                existing_url = doc_data.get('source_url', '').strip().lower()
                if existing_url == source_url:
                    result.add_duplicate('Source URL', source_url, doc_data.get('source_url'))
                    logger.warning(f"Duplicate URL found: {source_url}")

                # Check enrollment number (exact match)
                if doc_data.get('enrollment_number', '').strip() == enrollment:
                    result.add_duplicate('Enrollment Number', enrollment)
                    logger.warning(f"Duplicate enrollment found: {enrollment}")
                
                # Check email (case-insensitive)
                existing_email = doc_data.get('email', '').strip().lower()
                if existing_email == email:
                    result.add_duplicate('Email ID', email, doc_data.get('email'))
                    logger.warning(f"Duplicate email found: {email}")
                
                # Check contact number (exact match)
                if doc_data.get('contact_number', '').strip() == contact:
                    result.add_duplicate('Contact Number', contact)
                    logger.warning(f"Duplicate contact found: {contact}")
                

                # If we found duplicates, no need to check further
                if result.is_duplicate:
                    break
            
            if result.is_duplicate:
                logger.warning(f"Duplicates detected - Fields: {', '.join(result.duplicate_fields)}")
            else:
                logger.info("No duplicates found - submission can proceed")
                
        except Exception as e:
            logger.error(f"Error checking for duplicates: {e}")
            # In case of error, we'll allow submission to proceed
            # but log the error for investigation
            result.is_duplicate = False
        
        return result
    
    def save_submission(self, data: Dict) -> Tuple[bool, str]:
        """
        Save submission to Firestore with atomic check for duplicates
        """
        try:
            doc_ref = self.db.collection(self.collection).document(data['enrollment_number'])
            
            # Atomic check: create fails if document exists
            doc_ref.create(data)
            logger.info(f"Submission saved: {data['enrollment_number']}")
            return True, ""
            
        except Exception as e:
            error_str = str(e).lower()
            if "409" in str(e) or "already exists" in error_str:
                logger.warning(f"Duplicate submission attempt: {data['enrollment_number']}")
                return False, "This Enrollment Number has already been submitted."
            
            logger.error(f"Database error: {e}")
            return False, "Database error occurred. Please try again later."
    
    def check_enrollment_exists(self, enrollment_number: str) -> bool:
        """Check if enrollment number already exists"""
        try:
            doc_ref = self.db.collection(self.collection).document(enrollment_number)
            return doc_ref.get().exists
        except Exception as e:
            logger.error(f"Error checking enrollment: {e}")
            return False

# ============================================================================
# EMAIL SERVICE
# ============================================================================

class EmailService:
    """Handle email sending operations"""
    
    def __init__(self):
        try:
            self.sender_email = st.secrets["email"]["sender_email"]
            self.sender_password = st.secrets["email"]["sender_password"]
            self.smtp_server = st.secrets["email"]["smtp_server"]
            self.smtp_port = int(st.secrets["email"]["smtp_port"])
            self.enabled = True
        except Exception as e:
            logger.warning(f"Email configuration not found: {e}")
            self.enabled = False
    
    def send_confirmation_email(self, recipient_email: str, full_name: str, 
                               project_name: str, enrollment_number: str) -> bool:
        """Send confirmation email to the user"""
        
        if not self.enabled:
            logger.warning("Email service not configured")
            return False
        
        logger.info(f"Sending confirmation email to {recipient_email}")
        
        try:
            # Create message
            message = MIMEMultipart("alternative")
            message["Subject"] = "🎉 Project Submission Confirmation - DAV Subject"
            message["From"] = self.sender_email
            message["To"] = recipient_email
            
            # Email body
            html_body = self._generate_html_body(full_name, project_name, 
                                                 recipient_email, enrollment_number)
            text_body = self._generate_text_body(full_name, project_name, 
                                                 recipient_email, enrollment_number)
            
            message.attach(MIMEText(text_body, "plain"))
            message.attach(MIMEText(html_body, "html"))
            
            # Send email
            with smtplib.SMTP(self.smtp_server, self.smtp_port, timeout=30) as server:
                server.starttls()
                server.login(self.sender_email, self.sender_password)
                server.sendmail(self.sender_email, recipient_email, message.as_string())
            
            logger.info(f"Email sent successfully to {recipient_email}")
            return True
            
        except smtplib.SMTPAuthenticationError as e:
            logger.error(f"SMTP Authentication Error: {e}")
            return False
        except Exception as e:
            logger.error(f"Email sending error: {e}")
            return False
    
    def _generate_html_body(self, full_name: str, project_name: str, 
                           email: str, enrollment: str) -> str:
        """Generate HTML email body"""
        return f"""
        <html>
            <body style="font-family: Arial, sans-serif; background-color: #F5FBE6; padding: 20px;">
                <div style="max-width: 600px; margin: 0 auto; background-color: #ffffff; border-radius: 12px; padding: 30px; border: 2px solid #215E61;">
                    <h2 style="color: #233D4D; text-align: center; margin-bottom: 20px;">✅ Submission Successful!</h2>
                    
                    <p style="color: #215E61; font-size: 16px; line-height: 1.6;">
                        Hello <strong>{full_name}</strong>,
                    </p>
                    
                    <p style="color: #215E61; font-size: 16px; line-height: 1.6;">
                        Thank you for submitting your project to the <strong>DAV Project Submission</strong>. Your submission has been successfully recorded in our system.
                    </p>
                    
                    <div style="background-color: #F5FBE6; border-left: 4px solid #215E61; padding: 15px; margin: 20px 0; border-radius: 6px;">
                        <p style="color: #233D4D; margin: 10px 0;"><strong>📋 Submission Details:</strong></p>
                        <p style="color: #233D4D; margin: 8px 0;"><strong>Enrollment Number:</strong> {enrollment}</p>
                        <p style="color: #233D4D; margin: 8px 0;"><strong>Project Name:</strong> {project_name}</p>
                        <p style="color: #233D4D; margin: 8px 0;"><strong>Email:</strong> {email}</p>
                        <p style="color: #233D4D; margin: 8px 0;"><strong>Submission Date:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
                    </div>
                    
                    <p style="color: #215E61; font-size: 16px; line-height: 1.6;">
                        Our team will review your submission shortly. If you have any questions or need to make changes, please don't hesitate to contact MR. PRINCE.
                    </p>
                    
                    <hr style="border: none; height: 2px; background: #215E61; margin: 20px 0;">
                    
                    <p style="color: #6b7280; font-size: 14px; text-align: center;">
                        This is an automated email. Please do not reply to this message.<br>
                        © 2026 DAV Project Submission. All rights reserved.
                    </p>
                </div>
            </body>
        </html>
        """
    
    def _generate_text_body(self, full_name: str, project_name: str, 
                           email: str, enrollment: str) -> str:
        """Generate plain text email body"""
        return f"""
        Submission Successful!
        
        Hello {full_name},
        
        Thank you for submitting your project to the DAV Project Submission. Your submission has been successfully recorded in our system.
        
        Submission Details:
        - Enrollment Number: {enrollment}
        - Project Name: {project_name}
        - Email: {email}
        - Submission Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        
        Our team will review your submission shortly. If you have any questions or need to make changes, please don't hesitate to contact MR. PRINCE.
        
        This is an automated email. Please do not reply to this message.
        © 2026 DAV Project Submission. All rights reserved.
        """

# ============================================================================
# UI STYLING
# ============================================================================

def apply_custom_css():
    """Apply custom CSS styling"""
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
    
    /* Hide Streamlit Branding */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    .stDeployButton {visibility: hidden;}
    header {visibility: hidden;}
    
    /* Page Background */
    .main {
        background: #112d4e;
        padding: 2.5rem 1rem;
        min-height: 100vh;
    }
    
    /* Typography */
    * {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    }
    
    /* Input Fields */
    .stTextInput > div > div > input,
    .stTextArea > div > div > textarea {
        border: 2px solid #d1d5db;
        border-radius: 10px;
        padding: 0.75rem 1rem;
        font-size: 1rem;
        color: #1a1a1a;
        background: #fafafa;
        transition: all 0.2s ease;
        font-weight: 500;
        caret-color: #0052a3;
        -webkit-text-fill-color: #1a1a1a;
    }
    
    .stTextInput > div > div > input::placeholder,
    .stTextArea > div > div > textarea::placeholder {
        color: #6b7280;
        opacity: 0.7;
    }
    
    .stTextInput > div > div > input:focus,
    .stTextArea > div > div > textarea:focus {
        border-color: #667eea;
        background: #ffffff;
        box-shadow: 0 0 0 4px rgba(102, 126, 234, 0.1);
        outline: none;
        caret-color: #0052a3;
        -webkit-text-fill-color: #1a1a1a;
    }
    
    /* Detail Rows */
    .detail-row {
        background-color: #ffffff;
        padding: 12px 15px;
        margin: 8px 0;
        border-radius: 8px;
        border: 1px solid #e0e0e0;
        border-left: 4px solid #008BFF;
        transition: transform 0.2s;
    }
    
    .detail-row:hover {
        transform: translateX(5px);
        border-left-color: #E4FF30;
    }
    
    .detail-label {
        color: #362F4F;
        font-weight: 700;
        font-size: 0.9rem;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    
    .detail-value {
        color: #5B23FF;
        font-size: 1.05rem;
        margin-top: 3px;
        font-family: monospace;
        word-break: break-word;
    }
    
    /* Submit Button */
    .stButton > button {
        width: 100%;
        background: #0052a3;
        color: #ffffff;
        font-weight: 700;
        font-size: 1.05rem;
        letter-spacing: 0.02em;
        border-radius: 12px;
        padding: 1rem 2rem;
        border: none;
        margin-top: 1rem;
        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        box-shadow: 0 10px 25px rgba(102, 126, 234, 0.3);
        text-transform: uppercase;
    }
    
    .stButton > button:hover {
        transform: translateY(-3px);
        box-shadow: 0 15px 35px rgba(102, 126, 234, 0.4);
        background: #003d7a;
    }
    
    .stButton > button:active {
        transform: translateY(-1px);
    }
    
    .stButton > button:disabled {
        opacity: 0.6;
        cursor: not-allowed;
        transform: none;
    }
    
    /* Alert Messages */
    .element-container .stAlert,
    .stAlert {
        border-radius: 10px;
        border-left: 5px solid;
        padding: 1rem 1.25rem;
        margin-bottom: 1rem;
        font-size: 0.95rem;
        font-weight: 500;
    }
    
    .stSuccess {
        background-color: #f0fdf4;
        border-left-color: #16a34a;
        color: #15803d;
    }
    
    .stError {
        background-color: #fef2f2;
        border-left-color: #dc2626;
        color: #991b1b;
    }
    
    .stWarning {
        background-color: #fffbeb;
        border-left-color: #f59e0b;
        color: #b45309;
    }
    
    .stInfo {
        background-color: #eff6ff;
        border-left-color: #3b82f6;
        color: #1e40af;
    }
    
    /* Duplicate Warning Box */
    .duplicate-warning {
        background: linear-gradient(135deg, #fee2e2 0%, #fecaca 100%);
        border: 2px solid #dc2626;
        border-radius: 12px;
        padding: 1.5rem;
        margin: 1.5rem 0;
        box-shadow: 0 4px 6px rgba(220, 38, 38, 0.1);
    }
    
    .duplicate-warning-title {
        color: #991b1b;
        font-size: 1.3rem;
        font-weight: 700;
        margin-bottom: 1rem;
        display: flex;
        align-items: center;
        gap: 0.5rem;
    }
    
    .duplicate-warning-content {
        color: #7f1d1d;
        font-size: 1rem;
        line-height: 1.6;
        margin-bottom: 1rem;
    }
    
    .duplicate-field-item {
        background-color: #ffffff;
        padding: 0.75rem 1rem;
        margin: 0.5rem 0;
        border-radius: 8px;
        border-left: 4px solid #dc2626;
        font-weight: 500;
    }
    
    .action-box {
        background-color: #fffbeb;
        border-left: 4px solid #f59e0b;
        padding: 1rem;
        margin-top: 1rem;
        border-radius: 8px;
    }
    
    .action-box-title {
        color: #92400e;
        font-weight: 700;
        margin-bottom: 0.5rem;
    }
    
    .action-box ul {
        color: #92400e;
        margin: 0.5rem 0 0 1.5rem;
        padding: 0;
    }
    
    /* Success Animation */
    .success-icon {
        animation: popIn 0.6s cubic-bezier(0.175, 0.885, 0.32, 1.275);
        font-size: 20px;
        text-align: left;
        margin-bottom: 10px;
        text-shadow: 0 0 20px #EEFF1A;
    }
    
    @keyframes popIn {
        0% {
            transform: scale(0);
            opacity: 0;
        }
        100% {
            transform: scale(1);
            opacity: 1;
        }
    }
    
    .required {
        color: #dc2626;
        font-weight: 800;
    }
    
    /* Section Headers */
    .section-header {
        font-size: 1.2rem;
        font-weight: 700;
        color: lightblue;
        margin: 1.5rem 0 1rem 0;
        padding-bottom: 0.5rem;
        border-bottom: 2px solid #215E61;
    }
    
    /* Input Labels */
    .input-label {
        font-size: 0.95rem;
        font-weight: 600;
        color: white;
        margin-bottom: 0.5rem;
        display: block;
    }
    </style>
    """, unsafe_allow_html=True)

# ============================================================================
# UI COMPONENTS
# ============================================================================

def show_duplicate_warning(duplicate_result: DuplicateCheckResult):
    """Display comprehensive duplicate warning"""
    st.markdown("""
    <div class="duplicate-warning">
        <div class="duplicate-warning-title">
            🚫 Duplicate Entry Detected
        </div>
        <div class="duplicate-warning-content">
            <strong>The following information already exists in our database:</strong>
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    # Show each duplicate field
    for message in duplicate_result.messages:
        st.error(f"❌ {message}")
    
    st.markdown("""
    <div class="action-box">
        <div class="action-box-title">⚠️ What to do next:</div>
        <ul>
            <li>If you've already submitted, no further action is needed</li>
            <li>If you need to update your submission, contact <strong>MR. PRINCE</strong></li>
            <li>If this is an error, verify your information and try again</li>
            <li>Make sure you're not accidentally resubmitting the same data</li>
        </ul>
    </div>
    """, unsafe_allow_html=True)

def show_success_page(submission_data: Dict):
    """Display success page after submission"""
    st.markdown(f"""
        <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
                    padding: 2rem; border-radius: 12px; margin-bottom: 2rem; color: white;">
            <div class="success-icon">🎉 Form Submitted Successfully!</div>
            <p style="font-size: 1.1rem; margin-top: 1rem;">
                Thank you, <strong>{submission_data['full_name']}</strong>! 😊<br>
                Your project has been successfully submitted to our system.
            </p>
        </div>
    """, unsafe_allow_html=True)
    
    st.markdown("### 📋 Submission Summary")
    
    details = [
        ("Email", submission_data['email']),
        ("Enrollment Number", submission_data['enrollment_number']),
        ("Full Name", submission_data['full_name']),
        ("Contact Number", submission_data['contact_number']),
        ("Project Name", submission_data['project_name']),
        ("Source URL", submission_data['source_url'])
    ]
    
    for label, value in details:
        st.markdown(
            f'''
            <div class="detail-row">
                <div class="detail-label">{label}</div>
                <div class="detail-value">{value}</div>
            </div>
            ''',
            unsafe_allow_html=True
        )
    
    st.success("✉️ A confirmation email has been sent to your email address.")
    st.info("💬 For any issues, contact MR. PRINCE.")
    st.balloons()

def render_form_field(label: str, key: str, placeholder: str, 
                     help_text: str, max_chars: int = None):
    """Render a form field with consistent styling"""
    st.markdown(f'<label class="input-label">{label} <span class="required">*</span></label>', 
                unsafe_allow_html=True)
    return st.text_input(
        f"{key}_input",
        placeholder=placeholder,
        help=help_text,
        label_visibility="collapsed",
        max_chars=max_chars,
        key=key
    )

# ============================================================================
# SESSION STATE MANAGEMENT
# ============================================================================

def init_session_state():
    """Initialize session state variables"""
    defaults = {
        'submission_complete': False,
        'submitted_data': None,
        'is_submitting': False,
        'last_submission_time': 0,
        'form_data': {},
        'duplicate_check_result': None
    }
    
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

def reset_session_state():
    """Reset session state for new submission"""
    st.session_state.submission_complete = False
    st.session_state.submitted_data = None
    st.session_state.is_submitting = False
    st.session_state.form_data = {}
    st.session_state.duplicate_check_result = None

# ============================================================================
# MAIN APPLICATION
# ============================================================================

def main():
    """Main application logic"""
    
    # Initialize
    apply_custom_css()
    init_session_state()
    
    # Initialize services
    db = init_firebase()
    db_manager = DatabaseManager(db)
    email_service = EmailService()
    
    # Show success page if submission complete
    if st.session_state.submission_complete and st.session_state.submitted_data:
        st.title("🎓 DAV Project Submission")
        show_success_page(st.session_state.submitted_data)
        
        st.markdown("<br><br>", unsafe_allow_html=True)
        if st.button("📝 Submit For Your Friend", use_container_width=True):
            reset_session_state()
            st.rerun()
        return
    
    # Display form
    st.title("🎓 DAV Project Form")
    st.markdown("### Submit your project details below")
    st.info("📧 Please fill in your original Email ID to receive a confirmation email after submission.")
    st.markdown("---")
    
    with st.form("project_submission_form", clear_on_submit=True):
        
        # Personal Information Section
        st.markdown('<div class="section-header">📋 Personal Information</div>', 
                   unsafe_allow_html=True)
        
        email = render_form_field(
            "Email ID", "email",
            "student@university.edu",
            "Your university email address"
        )
        
        enrollment = render_form_field(
            "Enrollment Number", "enrollment",
            "123456789012",
            "12-digit enrollment number",
            max_chars=12
        )
        
        full_name = render_form_field(
            "Full Name", "full_name",
            "Your Full Name",
            "Your complete name as per university records"
        )
        
        contact = render_form_field(
            "Contact Number", "contact",
            "9876543210",
            "10-digit mobile number",
            max_chars=10
        )
        
        st.markdown("---")
        
        # Project Details Section
        st.markdown('<div class="section-header">💻 Project Details</div>', 
                   unsafe_allow_html=True)
        
        project_name = render_form_field(
            "Project Name", "project_name",
            "My Awesome Project",
            "Descriptive name for your project (minimum 3 characters)"
        )
        
        source_url = render_form_field(
            "Source URL", "source_url",
            "https://xyz.com/username/project-name",
            "GitHub, GitLab, or other repository link"
        )
        
        st.markdown("---")
        
        # Submit Button
        submitted = st.form_submit_button(
            "🚀 Submit Project",
            use_container_width=True,
            disabled=st.session_state.is_submitting
        )
        
        if submitted:
            # Rate limiting
            current_time = time.time()
            if current_time - st.session_state.last_submission_time < 3:
                st.warning("⏳ Please wait a moment before submitting again.")
                st.stop()
            
            st.session_state.is_submitting = True
            st.session_state.last_submission_time = current_time
            
            with st.spinner("🔄 Validating your submission... Please wait."):
                
                # Prepare data
                form_data = {
                    'email': email,
                    'enrollment_number': enrollment,
                    'full_name': full_name,
                    'contact_number': contact,
                    'project_name': project_name,
                    'source_url': source_url
                }
                
                # Step 1: Validate all fields (format, length, etc.)
                all_valid, errors = Validator.validate_all(form_data)
                
                if not all_valid:
                    st.error("❌ Please correct the following errors:")
                    for error in errors:
                        st.warning(f"• {error}")
                    st.session_state.is_submitting = False
                else:
                    # Step 2: Check for duplicates in database
                    st.info("🔍 Checking for duplicate entries in database...")
                    time.sleep(0.3)  # Brief pause for UX
                    
                    duplicate_result = db_manager.check_for_duplicates(form_data)
                    
                    if duplicate_result.is_duplicate:
                        # STOP: Duplicates found - show warning and prevent submission
                        st.session_state.is_submitting = False
                        st.markdown("<br>", unsafe_allow_html=True)
                        show_duplicate_warning(duplicate_result)
                        
                    else:
                        # No duplicates - proceed with submission
                        st.success("✅ No duplicates found! Proceeding with submission...")
                        time.sleep(0.3)
                        
                        # Clean and prepare submission data
                        submission_data = {
                            'email': email.strip().lower(),
                            'enrollment_number': enrollment.strip(),
                            'full_name': full_name.strip(),
                            'contact_number': contact.strip(),
                            'project_name': project_name.strip(),
                            'source_url': source_url.strip(),
                            'submitted_at': firestore.SERVER_TIMESTAMP
                        }
                        
                        # Save to database
                        success, error_msg = db_manager.save_submission(submission_data)
                        
                        if success:
                            # Send confirmation email (non-blocking)
                            try:
                                email_sent = email_service.send_confirmation_email(
                                    submission_data['email'],
                                    submission_data['full_name'],
                                    submission_data['project_name'],
                                    submission_data['enrollment_number']
                                )
                                
                                if not email_sent:
                                    st.warning("📝 Submission saved! Email notification could not be sent.")
                                    
                            except Exception as e:
                                logger.error(f"Email error: {e}")
                                st.info("📝 Your submission was saved successfully!")
                            
                            # Show success page
                            st.session_state.submitted_data = submission_data
                            st.session_state.submission_complete = True
                            time.sleep(0.5)
                            st.rerun()
                            
                        else:
                            st.error(f"❌ {error_msg}")
                            st.session_state.is_submitting = False
    
    # Guidelines
    with st.expander("ℹ️ Submission Guidelines & Requirements", expanded=False):
        st.markdown("""
        **📋 Field Requirements:**
        
        **Personal Information:**
        - **Email ID:** Valid email format (e.g., student@university.edu)
        - **Enrollment Number:** Exactly 12 numeric digits
        - **Full Name:** Letters and spaces only, minimum 2 characters
        - **Contact Number:** Exactly 10 numeric digits
        
        **Project Information:**
        - **Project Name:** Minimum 3 characters, be descriptive
        - **Source URL:** Must start with http:// or https://
        
        **⚠️ Important Notes:**
        - All fields marked with * are mandatory
        - Each enrollment number, email, and contact number can only be submitted once
        - The system checks for duplicates before saving to prevent double submissions
        - Double-check all information before submitting
        - You will receive a confirmation email upon successful submission
        - Contact MR. PRINCE for any issues or corrections
        
        **🔒 Privacy & Security:**
        - Your data is securely stored in our database
        - We do not share your information with third parties
        - Email confirmations are sent automatically
        
        **🚫 Duplicate Prevention:**
        - The system automatically checks if your enrollment number, email, or contact number already exists
        - If any field is already registered, your submission will be blocked
        - This prevents accidental duplicate submissions
        - If you need to update existing information, contact MR. PRINCE
        """)

    st.markdown(f"""
        <div style="display:flex;flex-direction:column;align-items:center;gap:0.75rem;">
            <div style="background: linear-gradient(135deg, #66eeea 0%, #764ba2 100%); 
                        padding: 1rem; border-radius: 12px; margin: 0.5rem; color: black; width:100%; max-width:100%;">
                <div class="success-icon" style="font-size: 1.1rem; margin-top: 0.3rem;">Find My GitHub Profile for more fun 😊</div>
            </div>
        </div>
    """, unsafe_allow_html=True)

if __name__ == "__main__":
    main()
