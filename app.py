import streamlit as st

# ============================================================================
# PAGE CONFIGURATION - MUST BE FIRST STREAMLIT COMMAND
# ============================================================================
st.set_page_config(
    page_title="DAV Project Submission",
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

# Usage in your app
db = init_firebase()

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
    """
    try:
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        
        # Get email credentials
        try:
            e_creds = st.secrets["email"]
            sender_email = e_creds["sender_email"]
            sender_password = e_creds["sender_password"]
            smtp_server = e_creds["smtp_server"]
            smtp_port = e_creds["smtp_port"]
        except:
            sender_email = os.getenv("EMAIL_SENDER")
            sender_password = os.getenv("EMAIL_PASSWORD")
            smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
            smtp_port = int(os.getenv("SMTP_PORT", "587"))
        
        # Create message
        msg = MIMEMultipart('alternative')
        msg['Subject'] = "Project Submission Confirmation - DAV"
        msg['From'] = sender_email
        msg['To'] = recipient_email
        
        # HTML email body
        html = f"""
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
                        Madam will review your submission shortly. If you have any questions or need to make changes, please don't hesitate to contact Developer MR. PRINCE.
                    </p>
                    
                    <hr style="border: none; height: 2px; background: #215E61; margin: 20px 0;">
                    
                    <p style="color: #6b7280; font-size: 14px; text-align: center;">
                        This is an automated email. Please do not reply to this message.<br>
                        © 2026 Project Form Submission. All rights reserved by MR. PRINCE.
                    </p>
                </div>
            </body>
        </html>
        """
        
        # Attach HTML part
        part = MIMEText(html, 'html')
        msg.attach(part)
        
        # Send email
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, recipient_email, msg.as_string())
        
        return True
        
    except Exception as e:
        print(f"Email sending failed: {str(e)}")
        return False

# ============================================================================
# CSS STYLING
# ============================================================================

def load_css():
    st.markdown("""
        <style>
            /* PALETTE:
               #362F4F (Dark Navy/Purple) - Base/Text
               #5B23FF (Vivid Purple) - Primary/Headers
               #008BFF (Bright Blue) - Borders/Accents
               #E4FF30 (Neon Yellow) - Highlights/Success
            */

            /* ============================================
               STREAMLIT UI CLEANUP
               ============================================ */
            #MainMenu { visibility: hidden; }
            footer { visibility: hidden; }
            .stDeployButton { visibility: hidden; }
            
            /* ============================================
               BACKGROUND & MAIN CONTAINER
               ============================================ */
            
            /* Background gradient */
            .stApp {
                background: rgba(14,17,23,1);
            }
            
            /* Main container styling */
            .main .block-container {
                background-color: rgba(255, 255, 255, 0.97);
                border-radius: 15px;
                padding: 2rem;
                box-shadow: 0 10px 40px rgba(0, 0, 0, 0.5);
                max-width: 800px;
                margin-top: 2rem;
                margin-bottom: 2rem;
                border-top: 5px solid #E4FF30;
            }
            
            /* ============================================
               TYPOGRAPHY
               ============================================ */
            
            /* Main title styling */
            h1 {
                color: #5B23FF !important;
                font-weight: 800 !important;
                text-align: center;
                margin-bottom: 0.5rem !important;
                text-transform: uppercase;
                letter-spacing: 1px;
            }
            
            /* Subtitle styling */
            h3 {
                color: #fffdd0 !important;
                text-align: center;
                font-weight: 600 !important;
            }
            
            /* Section headers */
            .section-header {
                background: linear-gradient(90deg, #5B23FF, #008BFF);
                color: #ffffff;
                padding: 12px 20px;
                border-radius: 8px;
                font-size: 1.1rem;
                font-weight: 700;
                margin: 20px 0 15px 0;
                box-shadow: 0 4px 10px rgba(91, 35, 255, 0.3);
                border-left: 5px solid #E4FF30;
            }
            
            /* ============================================
               FORM INPUTS
               ============================================ */
            
            /* Input labels */
            .stTextInput > label, 
            .stTextArea > label {
                font-weight: 700;
                color: #362F4F;
            }
            
            .input-label {
                color: #6a99ff;
                font-weight: 700;
                font-size: 0.95rem;
                margin-bottom: 5px;
                display: block;
            }
            
            .required {
                color: red;
                font-weight: 800;
            }
            
            /* Text inputs and textareas */
            .stTextInput input,
            .stTextArea textarea {
                border: 2px solid #008BFF !important;
                border-radius: 8px !important;
                padding: 10px !important;
                font-size: 1rem !important;
                transition: all 0.3s ease !important;
                background-color: #F8F9FF !important;
                color: #362F4F !important;
            }
            
            /* Input focus state */
            .stTextInput input:focus,
            .stTextArea textarea:focus {
                border-color: #5B23FF !important;
                box-shadow: 0 0 0 3px rgba(91, 35, 255, 0.2) !important;
                background-color: #ffffff !important;
                outline: none !important;
            }
            
            /* ============================================
               BUTTONS
               ============================================ */
            
            /* Submit button styling */
            .stButton > button {
                width: 100%;
                background: linear-gradient(135deg, #5B23FF, #008BFF) !important;
                color: #E4FF30 !important; /* Neon Yellow Text */
                font-weight: 800 !important;
                font-size: 1.2rem !important;
                border-radius: 10px !important;
                padding: 0.85rem 1.5rem !important;
                border: 2px solid transparent !important;
                box-shadow: 0 5px 15px rgba(91, 35, 255, 0.4) !important;
                transition: all 0.3s ease !important;
                text-transform: uppercase;
                letter-spacing: 1.5px;
            }
            
            /* Button hover state */
            .stButton > button:hover {
                background: linear-gradient(135deg, #6a99ff, #5B23FF) !important;
                color: #E4FF30 !important;
                border: 2px solid #E4FF30 !important;
                transform: translateY(-2px);
                box-shadow: 0 0 20px rgba(228, 255, 48, 0.4) !important;
            }
            
            /* Button disabled state */
            .stButton > button:disabled {
                background: #cfcfcf !important;
                color: #666 !important;
                border-color: transparent !important;
                cursor: not-allowed;
            }
            
            /* ============================================
               ALERT MESSAGES
               ============================================ */
            
            .element-container .stAlert {
                padding: 0.75rem;
                margin-bottom: 0.75rem;
                border-radius: 8px;
                border-left: 5px solid;
            }
            
            /* Success messages - Yellow/Lime Theme */
            .stSuccess {
                background-color: #f9ffe0 !important;
                border-left-color: #E4FF30 !important;
                color: #6a99ff !important;
            }
            
            /* Error messages */
            .stError {
                background-color: #fff0f0 !important;
                border-left-color: #ff3333 !important;
                color: #6a99ff !important;
            }
            
            /* Warning messages */
            .stWarning {
                background-color: #fffbe6 !important;
                border-left-color: #ffcc00 !important;
                color: #6a99ff !important;
            }
            
            /* ============================================
               EXPANDERS
               ============================================ */
            
            .streamlit-expanderHeader {
                background-color: #F8F9FF !important;
                border: 1px solid #008BFF !important;
                border-radius: 8px !important;
                color: #5B23FF !important;
                font-weight: 600 !important;
            }
            
            .streamlit-expanderHeader:hover {
                background-color: #E4FF30 !important;
                color: #6a99ff !important;
            }
            
            /* ============================================
               MISC COMPONENTS
               ============================================ */
            
            /* Spinner */
            .stSpinner > div {
                border-top-color: #E4FF30 !important;
            }
            
            /* Divider */
            hr {
                border-color: #008BFF !important;
                opacity: 0.3;
                margin: 1.5rem 0 !important;
            }
            
            /* ============================================
               SUCCESS PAGE COMPONENTS
               ============================================ */
            
            .success-card {
                background: linear-gradient(135deg, #ffffff, #F0F4FF);
                border: 2px solid #E4FF30;
                border-radius: 15px;
                padding: 30px;
                margin: 20px 0;
                box-shadow: 0 0 30px rgba(91, 35, 255, 0.15);
            }
            
            .success-card h2 {
                color: #5B23FF !important;
                margin-bottom: 15px !important;
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
            
            /* Animation */
            @keyframes popIn {
                0% { transform: scale(0); opacity: 0; }
                80% { transform: scale(1.1); opacity: 1; }
                100% { transform: scale(1); opacity: 1; }
            }
            
            .success-icon {
                animation: popIn 0.6s cubic-bezier(0.175, 0.885, 0.32, 1.275);
                font-size: 5rem;
                text-align: center;
                margin-bottom: 20px;
                text-shadow: 0 0 20px #E4FF30;
            }
        </style>

    """, unsafe_allow_html=True)

# ============================================================================
# SUCCESS PAGE
# ============================================================================

def show_success_page(data: Dict):
    """Display a beautiful success confirmation page"""
    st.markdown(
        '<div class="success-icon">✅</div>',
        unsafe_allow_html=True
    )

    st.markdown("## 🎉 Submission Successful!")
    st.markdown("Your project has been submitted successfully. A confirmation email has been sent to your email address.")
    
    st.markdown("### 📋 Submission Summary")
    
    # Display submission details
    details = [
        ("Email", data['email']),
        ("Enrollment Number", data['enrollment_number']),
        ("Full Name", data['full_name']),
        ("Contact Number", data['contact_number']),
        ("Project Name", data['project_name']),
        ("Source URL", data['source_url'])
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
    st.info("💡 Keep this confirmation for your records.")
    st.balloons()

# ============================================================================
# MAIN APPLICATION
# ============================================================================

def main():
    # Load CSS
    load_css()
    
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
    st.title("🎓 DAV Project Submission Form")
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
                    
                    # 1. NEW SAVE LOGIC
                    success, error_msg = save_submission(db, submission_data)
                    
                    if success:
                        # 2. NEW EMAIL LOGIC
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

