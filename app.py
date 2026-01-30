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
from typing import Dict, Optional, Tuple
import json
import time
import threading
import os
# ============================================================================
# FIREBASE INITIALIZATION
# ============================================================================

@st.cache_resource
def init_firebase():
    """
    Initialize Firebase and return the Firestore client.
    Works with both local secrets.toml and Hugging Face environment variables.
    """
    if not firebase_admin._apps:
        try:
            # Try to get from st.secrets first (local development)
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
        except:
            # Fall back to environment variables (Hugging Face deployment)
            private_key = os.getenv("FIREBASE_PRIVATE_KEY", "").replace("\\n", "\n")
            
            cred_dict = {
                "type": os.getenv("FIREBASE_TYPE", "service_account"),
                "project_id": os.getenv("FIREBASE_PROJECT_ID"),
                "private_key_id": os.getenv("FIREBASE_PRIVATE_KEY_ID"),
                "private_key": private_key,
                "client_email": os.getenv("FIREBASE_CLIENT_EMAIL"),
                "client_id": os.getenv("FIREBASE_CLIENT_ID"),
                "auth_uri": os.getenv("FIREBASE_AUTH_URI", "https://accounts.google.com/o/oauth2/auth"),
                "token_uri": os.getenv("FIREBASE_TOKEN_URI", "https://oauth2.googleapis.com/token"),
                "auth_provider_x509_cert_url": os.getenv("FIREBASE_AUTH_PROVIDER_X509_CERT_URL", "https://www.googleapis.com/oauth2/v1/certs"),
                "client_x509_cert_url": os.getenv("FIREBASE_CLIENT_X509_CERT_URL")
            }
        
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred)
    
    return firestore.client()

# ============================================================================
# VALIDATION FUNCTIONS
# ============================================================================

def validate_email(email: str) -> Tuple[bool, str]:
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if not email:
        return False, "Email ID is required"
    if not re.match(pattern, email):
        return False, "Invalid email format (e.g., user@example.com)"
    return True, ""

def validate_enrollment(enrollment: str) -> Tuple[bool, str]:
    pattern = r'^\d{12}$'
    if not enrollment:
        return False, "Enrollment Number is required"
    if not re.match(pattern, enrollment):
        return False, "Enrollment Number must be exactly 12 digits"
    return True, ""

def validate_name(name: str) -> Tuple[bool, str]:
    pattern = r'^[a-zA-Z\s]+$'
    if not name:
        return False, "Full Name is required"
    if not re.match(pattern, name.strip()):
        return False, "Full Name can only contain letters and spaces"
    return True, ""

def validate_contact(contact: str) -> Tuple[bool, str]:
    pattern = r'^\d{10}$'
    if not contact:
        return False, "Contact Number is required"
    if not re.match(pattern, contact):
        return False, "Contact Number must be exactly 10 digits"
    return True, ""

def validate_project_name(project_name: str) -> Tuple[bool, str]:
    if not project_name:
        return False, "Project Name is required"
    if len(project_name.strip()) < 3:
        return False, "Project Name must be at least 3 characters"
    return True, ""

def validate_url(url: str) -> Tuple[bool, str]:
    pattern = r'^https?://[^\s/$.?#].[^\s]*$'
    if not url:
        return False, "Source URL is required"
    if not re.match(pattern, url, re.IGNORECASE):
        return False, "URL must start with http:// or https://"
    return True, ""

# ============================================================================
# DATABASE OPERATIONS
# ============================================================================

def check_duplicate_fields(db, data: Dict) -> Tuple[bool, str]:
    collection_ref = db.collection('project_submissions')
    
    unique_fields = {
        'email': data['email'],
        'enrollment_number': data['enrollment_number'],
        'contact_number': data['contact_number'],
        'project_name': data['project_name'],
        'source_url': data['source_url']
    }
    
    for field_name, field_value in unique_fields.items():
        query = collection_ref.where(field_name, '==', field_value).limit(1)
        docs = query.stream()
        
        for doc in docs:
            field_display_names = {
                'email': 'Email ID',
                'enrollment_number': 'Enrollment Number',
                'contact_number': 'Contact Number',
                'project_name': 'Project Name',
                'source_url': 'Source URL'
            }
            return True, f"This {field_display_names[field_name]} is already taken."
    
    return False, ""

def save_submission(db, data: Dict) -> Tuple[bool, str]:
    try:
        # Use Enrollment Number as the Document ID
        doc_ref = db.collection('project_submissions').document(data['enrollment_number'])
        
        # 'create' fails if the document already exists (atomic check)
        doc_ref.create(data) 
        return True, ""
        
    except Exception as e:
        # Check if error is due to document already existing
        if "409" in str(e) or "already exists" in str(e).lower():
            return False, "This Enrollment Number has already been submitted."
        return False, f"Database error: {str(e)}"

def send_confirmation_email(recipient_email: str, full_name: str, project_name: str) -> bool:
    """
    Send confirmation email to the user after successful submission.
    Returns: True if successful, False otherwise
    """
    try:
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        
        # Get email credentials from Streamlit secrets
        sender_email = st.secrets["email"]["sender_email"]
        sender_password = st.secrets["email"]["sender_password"]
        smtp_server = st.secrets["email"]["smtp_server"]
        smtp_port = st.secrets["email"]["smtp_port"]
        
        # Create email message
        message = MIMEMultipart("alternative")
        message["Subject"] = "🎉 Project Submission Confirmation - DAV Subject"
        message["From"] = sender_email
        message["To"] = recipient_email
        
        # HTML email body
        html_body = f"""
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
                        <p style="color: #233D4D; margin: 8px 0;"><strong>Project Name:</strong> {project_name}</p>
                        <p style="color: #233D4D; margin: 8px 0;"><strong>Email:</strong> {recipient_email}</p>
                        <p style="color: #233D4D; margin: 8px 0;"><strong>Submission Date:</strong> {time.strftime('%Y-%m-%d %H:%M:%S')}</p>
                    </div>
                    
                    <p style="color: #215E61; font-size: 16px; line-height: 1.6;">
                        Our team will review your submission shortly. If you have any questions or need to make changes, please don't hesitate to contact MR. RPINCE.
                    </p>
                    
                    <hr style="border: none; height: 2px; background: #215E61; margin: 20px 0;">
                    
                    <p style="color: #6b7280; font-size: 14px; text-align: center;">
                        This is an automated email. Please do not reply to this message.<br>
                        © 2026 Project Form Submission. All rights reserved.
                    </p>
                </div>
            </body>
        </html>
        """
        
        # Plain text alternative
        text_body = f"""
        Submission Successful!
        
        Hello {full_name},
        
        Thank you for submitting your project to the DAV Project Submission. Your submission has been successfully recorded in our system.
        
        Submission Details:
        - Project Name: {project_name}
        - Email: {recipient_email}
        - Submission Date: {time.strftime('%Y-%m-%d %H:%M:%S')}
        
        Our team will review your submission shortly. If you have any questions or need to make changes, please don't hesitate to contact MR. PRINCE.
        
        This is an automated email. Please do not reply to this message.
        © 2026 Project Form Submission. All rights reserved.
        """
        
        part1 = MIMEText(text_body, "plain")
        part2 = MIMEText(html_body, "html")
        message.attach(part1)
        message.attach(part2)
        
        # Send email
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, recipient_email, message.as_string())
        
        return True
        
    except KeyError:
        st.warning("⚠️ Email service not configured. Please set up email credentials in Streamlit secrets.")
        return False
    except Exception as e:
        st.warning(f"⚠️ Could not send confirmation email: {str(e)}")
        return False

# ============================================================================
# PROFESSIONAL CSS WITH HIGH CONTRAST
# ============================================================================

def apply_custom_css():
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
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 2.5rem 1rem;
        min-height: 100vh;
    }
    
    /* Typography */
    * {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    }
    
    /* Custom styling for labels */
    .stTextInput > label, .stTextArea > label {
        font-weight: 600;
        color: #1a1a1a !important;
        font-size: 0.9rem;
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
    }
    
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
    }
                
    /* Submit button styling */
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
    }
    
    .stButton > button:active {
        transform: translateY(-1px);
    }
    
    /* Warning messages - HIGH CONTRAST */
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
    
    .success-icon {
        animation: popIn 0.6s cubic-bezier(0.175, 0.885, 0.32, 1.275);
        font-size: 20px;
        text-align: left;
        margin-bottom: 10px;
        text-shadow: 0 0 20px #E4FF30;
    }                

    .required {
        color: red;
        font-weight: 800;
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
    </style>
""", unsafe_allow_html=True)

# ============================================================================
# SUCCESS PAGE
# ============================================================================

def show_success_page(submission_data: Dict):
    """Display a beautiful success page after form submission"""
    st.markdown(f"""
        <div class="success-container">
            <div><div class="success-icon">🎉 Form Submit Successfully!</div>
            </div>
                <p class="success-message">
                Thank you, <strong>{submission_data['full_name']}</strong> 😊<br>
                Your project data has been successfully submitted to our system.
            </p>
        </div>
    """, unsafe_allow_html=True)
    st.markdown("### 📋 Submission Summary")
    
    # Display submission details
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
    
    st.markdown('</div>', unsafe_allow_html=True)
    
    st.success("✉️ Please check your email for confirmation.")
    st.info("💬 for any issues contact MR. PRINCE.")
    st.balloons()

# ============================================================================
# MAIN APPLICATION
# ============================================================================

def main():
    apply_custom_css()
    db = init_firebase()
    
    # Initialize session state
    if 'submission_complete' not in st.session_state:
        st.session_state.submission_complete = False
    if 'submitted_data' not in st.session_state:
        st.session_state.submitted_data = None
    if 'is_submitting' not in st.session_state:
        st.session_state.is_submitting = False
    if 'last_submission_time' not in st.session_state:
        st.session_state.last_submission_time = 0
    
    # Show success page if submission is complete
    if st.session_state.submission_complete and st.session_state.submitted_data:
        st.title("🎓 DAV Project Submission")
        show_success_page(st.session_state.submitted_data)
        
        # Add reset button
        st.markdown("<br><br>", unsafe_allow_html=True)
        if st.button("📝 Submit Another Project", use_container_width=True):
            st.session_state.submission_complete = False
            st.session_state.submitted_data = None
            st.session_state.is_submitting = False
            st.rerun()
        return
    
    # Display form
    st.title("🎓 DAV Project Form")
    st.markdown("### Submit your project details below")
    st.markdown("Please fill Original Email ID for Getting Confirmation Email after Submission.")
    st.markdown("---")
    
    with st.form("project_submission_form", clear_on_submit=True):
        # Personal Information Section
        st.markdown('<div class="section-header">📋 Personal Information</div>', unsafe_allow_html=True)
        
        st.markdown('<label class="input-label">Email ID <span class="required">*</span></label>', unsafe_allow_html=True)
        email = st.text_input(
            "email_input",
            placeholder="student@university.edu",
            help="Your university email address",
            label_visibility="collapsed"
        )
        
        st.markdown('<label class="input-label">Enrollment Number <span class="required">*</span></label>', unsafe_allow_html=True)
        enrollment = st.text_input(
            "enrollment_input",
            placeholder="123456789012",
            max_chars=12,
            help="12-digit enrollment number",
            label_visibility="collapsed"
        )
        
        st.markdown('<label class="input-label">Full Name <span class="required">*</span></label>', unsafe_allow_html=True)
        full_name = st.text_input(
            "name_input",
            placeholder="Your Full Name",
            help="Your complete name as per university records",
            label_visibility="collapsed"
        )
        
        st.markdown('<label class="input-label">Contact Number <span class="required">*</span></label>', unsafe_allow_html=True)
        contact = st.text_input(
            "contact_input",
            placeholder="9876543210",
            max_chars=10,
            help="10-digit mobile number",
            label_visibility="collapsed"
        )
        
        st.markdown("---")
        
        # Project Details Section
        st.markdown('<div class="section-header">💻 Project Details</div>', unsafe_allow_html=True)
        
        st.markdown('<label class="input-label">Project Name <span class="required">*</span></label>', unsafe_allow_html=True)
        project_name = st.text_input(
            "project_input",
            placeholder="Project Name",
            help="Descriptive name for your project (minimum 3 characters)",
            label_visibility="collapsed"
        )
        
        st.markdown('<label class="input-label">Source URL <span class="required">*</span></label>', unsafe_allow_html=True)
        source_url = st.text_input(
            "url_input",
            placeholder="https://xyz.com/project-name",
            help="GitHub, GitLab, or other repository link",
            label_visibility="collapsed"
        )
        
        st.markdown("---")
        
        # Submit Button
        submitted = st.form_submit_button(
            "🚀 Submit Project",
            use_container_width=True,
            disabled=st.session_state.is_submitting
        )
        
        if submitted:
            # Prevent rapid double-clicks
            current_time = time.time()
            if current_time - st.session_state.last_submission_time < 3:
                st.warning("⏳ Please wait a moment before submitting again.")
                st.stop()
            
            # Set submitting state immediately
            st.session_state.is_submitting = True
            st.session_state.last_submission_time = current_time
            
            with st.spinner("🔄 Processing your submission... Please wait."):
                # Validation
                validations = [
                    validate_email(email),
                    validate_enrollment(enrollment),
                    validate_name(full_name),
                    validate_contact(contact),
                    validate_project_name(project_name),
                    validate_url(source_url)
                ]
                
                all_valid = all(valid for valid, _ in validations)
                
                if not all_valid:
                    st.error("❌ Please correct the following errors:")
                    for valid, error_msg in validations:
                        if not valid and error_msg:
                            st.warning(f"• {error_msg}")
                    st.session_state.is_submitting = False
                else:
                    # Prepare submission data
                    submission_data = {
                        'email': email.strip().lower(),
                        'enrollment_number': enrollment.strip(),
                        'full_name': full_name.strip(),
                        'contact_number': contact.strip(),
                        'project_name': project_name.strip(),
                        'source_url': source_url.strip(),
                        'submitted_at': firestore.SERVER_TIMESTAMP
                    }
                    
                    # --- REPLACEMENT CODE STARTS HERE ---
                    
                    # 1. NEW SAVE LOGIC (Replaces check_duplicate_fields)
                    # We try to create the document directly. If the ID exists, it fails automatically.
                    success, error_msg = save_submission(db, submission_data)
                    
                    if success:
                        # 2. NEW EMAIL LOGIC (Replaces blocking email call)
                        # We start a background thread so the user doesn't have to wait.
                        email_thread = threading.Thread(
                            target=send_confirmation_email,
                            args=(
                                submission_data['email'],
                                submission_data['full_name'],
                                submission_data['project_name']
                            )
                        )
                        email_thread.start()
                        
                        # 3. Success Message
                        st.session_state.submitted_data = submission_data
                        st.session_state.submission_complete = True
                        time.sleep(0.5)
                        st.rerun()
                    else:
                        # This catches the duplicate enrollment error from save_submission
                        st.error(f"❌ {error_msg}")
                        st.session_state.is_submitting = False
    
    # Validation hints
    with st.expander("ℹ️ Submission Guidelines & Requirements", expanded=False):
        st.markdown("""
        **📋 Field Requirements:**
        
        **Personal Information:**
        - **Email ID:** Valid email format (e.g., student@university.edu)
        - **Enrollment Number:** Exactly 12 numeric digits
        - **Full Name:** Letters and spaces only, no special characters
        - **Contact Number:** Exactly 10 numeric digits
        
        **Project Information:**
        - **Project Name:** Minimum 3 characters, be descriptive
        - **Source URL:** Must start with http:// or https://
        
        **⚠️ Important Notes:**
        - All fields marked with * are mandatory
        - Each field must contain unique information (no duplicates allowed)
        - Double-check all information before submitting
        - You will receive a confirmation upon successful submission
        """)

if __name__ == "__main__":
    main()

