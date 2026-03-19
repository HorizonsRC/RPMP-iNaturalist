# email_notifications.py

# -*- coding: utf-8 -*-

"""
Email notification system for Horizons RPMP iNaturalist observations
Sends immediate alerts for Eradication/Exclusion species
Sends weekly summaries on Fridays including AMZ Progressive Containment
"""

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import json
import os
import sys

# ============================================================================
# Load Config
# ============================================================================
# All sensitive values (email addresses, SMTP server, staff lists) live in
# config.py — excluded from Git via .gitignore.
# If setting up on a new machine, copy config.example.py → config.py.

try:
    import config
except ImportError:
    print("ERROR: config.py not found.")
    print("Copy config.example.py to config.py and fill in your credentials.")
    sys.exit(1)

# ============================================================================
# CONFIGURATION — loaded from config, not hardcoded
# ============================================================================

EMAIL_CONFIG = {
    'smtp_server': config.SMTP_SERVER,
    'sender_email': config.SENDER_EMAIL,
    'sender_name': config.SENDER_NAME
}

ADMIN_EMAIL = config.ADMIN_EMAIL
REFRESH_TOKEN_WARNING_DAYS = 14

STAFF_EMAILS  = config.STAFF_EMAILS
AREA_TO_STAFF = config.AREA_TO_STAFF

TESTING_MODE = False
TEST_EMAIL = None
TEST_OBSERVATION_IDS = []


# ============================================================================
# EMAIL TEMPLATE FUNCTIONS
# ============================================================================

def create_immediate_alert_email(observations, staff_name, operating_area):
    """Create HTML email for immediate Eradication/Exclusion alerts"""
    programme_type = observations[0]['programme']
    
    subject = f"URGENT: {programme_type} Species Detected in {operating_area}"
    
    obs_list = ""
    for obs in observations:
        obs_list += f"""
        <div style="margin: 15px 0; padding: 15px; background-color: #fff3cd; border-left: 4px solid #ff6b6b;">
            <p style="margin: 5px 0;"><strong>Species:</strong> {obs['species_name']} (<em>{obs['taxon_name']}</em>)</p>
            <p style="margin: 5px 0;"><strong>Observed:</strong> {obs['observed_on']}</p>
            <p style="margin: 5px 0;"><strong>Quality:</strong> {obs['quality_grade']}</p>
            {f"<p style='margin: 5px 0;'><strong>Phenology:</strong> {obs['flowers_fruits']}</p>" if obs['flowers_fruits'] else ""}
            {f"<p style='margin: 5px 0;'><strong>Notes:</strong> {obs['description']}</p>" if obs['description'] else ""}
            <p style="margin: 10px 0 5px 0;"><a href="{obs['observation_url']}" style="background-color: #4CAF50; color: white; padding: 8px 15px; text-decoration: none; border-radius: 4px; display: inline-block;">View on iNaturalist</a></p>
        </div>
        """
    
    html_body = f"""
    <html>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="background-color: #d32f2f; color: white; padding: 15px; border-radius: 5px 5px 0 0;">
                <h2 style="margin: 0;">⚠️ URGENT: {programme_type} Species Alert</h2>
            </div>
            
            <div style="background-color: #f5f5f5; padding: 20px; border-radius: 0 0 5px 5px;">
                <p style="font-size: 16px;">Hi {staff_name},</p>
                
                <p><strong>{len(observations)} new {programme_type.lower()} species observation(s)</strong> have been reported on iNaturalist in the <strong>{operating_area}</strong> operating area:</p>
                
                {obs_list}
                
                <p style="margin-top: 20px; padding-top: 20px; border-top: 1px solid #ddd;">
                    <strong>Action Required:</strong><br>
                    Please assess these observations and determine if field verification or control action is needed.
                </p>
                
                <p style="font-size: 12px; color: #666; margin-top: 20px;">
                    This is an automated notification from the Horizons Regional Pest Management Plan iNaturalist monitoring system.
                    Generated on {datetime.now().strftime('%d %B %Y at %I:%M %p')}.
                </p>
            </div>
        </div>
    </body>
    </html>
    """
    
    return subject, html_body


def create_weekly_summary_email(observations, staff_name, operating_area):
    """Create HTML email for weekly summary"""
    subject = f"Weekly Summary: iNaturalist Observations in {operating_area}"
    
    prog_cont = [o for o in observations if o['programme'] == 'Progressive Containment']
    eradication = [o for o in observations if o['programme'] == 'Eradication']
    exclusion = [o for o in observations if o['programme'] == 'Exclusion']
    
    def format_obs_section(obs_list, title, color):
        if not obs_list:
            return ""
        
        section = f"""
        <div style="margin: 20px 0;">
            <h3 style="color: {color}; border-bottom: 2px solid {color}; padding-bottom: 5px;">{title} ({len(obs_list)} observation(s))</h3>
        """
        
        for obs in obs_list:
            section += f"""
            <div style="margin: 10px 0; padding: 10px; background-color: #f9f9f9; border-left: 3px solid {color};">
                <p style="margin: 3px 0;"><strong>{obs['species_name']}</strong> (<em>{obs['taxon_name']}</em>)</p>
                <p style="margin: 3px 0; font-size: 14px;">Observed: {obs['observed_on']}</p>
                {f"<p style='margin: 3px 0; font-size: 14px;'>Phenology: {obs['flowers_fruits']}</p>" if obs.get('flowers_fruits') else ""}
                <p style="margin: 5px 0;"><a href="{obs['observation_url']}" style="color: #2196F3;">View Observation →</a></p>
            </div>
            """
        
        section += "</div>"
        return section
    
    html_body = f"""
    <html>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="background-color: #273747; color: white; padding: 15px; border-radius: 5px 5px 0 0;">
                <h2 style="margin: 0;">📊 Weekly iNaturalist Observation Summary</h2>
            </div>
            
            <div style="background-color: #f5f5f5; padding: 20px; border-radius: 0 0 5px 5px;">
                <p style="font-size: 16px;">Hi {staff_name},</p>
                
                <p>Here's your weekly summary of new iNaturalist observations in the <strong>{operating_area}</strong> area:</p>
                
                {format_obs_section(exclusion, "🔴 Exclusion Species (Immediate Action Required)", "#d32f2f")}
                {format_obs_section(eradication, "🟠 Eradication Species (Action Required)", "#f57c00")}
                {format_obs_section(prog_cont, "🟢 Progressive Containment (AMZ only)", "#4CAF50")}
                
                <p style="margin-top: 20px; padding-top: 20px; border-top: 1px solid #ddd;">
                    <strong>Total:</strong> {len(observations)} new observation(s) this week
                </p>
                
                <p style="font-size: 12px; color: #666; margin-top: 20px;">
                    This is an automated weekly summary from the Horizons RPMP iNaturalist monitoring system.
                    Generated on {datetime.now().strftime('%A, %d %B %Y at %I:%M %p')}.
                </p>
            </div>
        </div>
    </body>
    </html>
    """
    
    return subject, html_body


def send_email(to_email, subject, html_body):
    """Send an HTML email via Horizons internal SMTP server"""
    try:
        message = MIMEMultipart('alternative')
        message['Subject'] = subject
        message['From'] = EMAIL_CONFIG['sender_email']
        message['To'] = to_email
        
        html_part = MIMEText(html_body, 'html')
        message.attach(html_part)
        
        mailServer = smtplib.SMTP(EMAIL_CONFIG['smtp_server'])
        mailServer.send_message(message)
        mailServer.quit()
        
        return True
    except Exception as e:
        print(f"  ✗ Email send failed: {e}")
        return False


# ============================================================================
# MAIN FUNCTION
# ============================================================================

def process_notifications(notification_file_path):
    """
    Main function to process and send email notifications
    """
    print("="*70)
    print("EMAIL NOTIFICATION SYSTEM")
    print("="*70)
    
    if TESTING_MODE:
        print(f"\n⚠️  TESTING MODE ENABLED")
        print(f"All emails will be sent to: {TEST_EMAIL}")
        if TEST_OBSERVATION_IDS:
            print(f"Forcing notifications for observation IDs: {TEST_OBSERVATION_IDS}")
        print()
    
    results = {
        'emails_sent': 0,
        'emails_failed': 0,
        'notifications_processed': 0,
        'staff_notifications': {}  # Track which staff members received notifications
    }
    
    if not os.path.exists(notification_file_path):
        print("\n✓ No pending notifications found")
        return results
    
    with open(notification_file_path, 'r') as f:
        notification_data = json.load(f)
    
    notifications = notification_data['notifications']
    
    if TESTING_MODE and TEST_OBSERVATION_IDS:
        notifications = [n for n in notifications if n['observation_id'] in TEST_OBSERVATION_IDS]
        print(f"Filtered to {len(notifications)} test observation(s)")
    
    if len(notifications) == 0:
        print("\n✓ No notifications to send")
        return results
    
    print(f"\n📧 Processing {len(notifications)} notification(s)...")
    results['notifications_processed'] = len(notifications)
    
    is_friday = datetime.now().weekday() == 4
    
    notifications_by_staff = {}
    for notif in notifications:
        staff = notif['staff_member']
        if staff not in notifications_by_staff:
            notifications_by_staff[staff] = []
        notifications_by_staff[staff].append(notif)
    
    for staff_name, staff_notifications in notifications_by_staff.items():
        print(f"\nProcessing notifications for {staff_name}...")
        
        if TESTING_MODE:
            email_address = TEST_EMAIL
            print(f"  Using test email: {email_address}")
        else:
            email_address = STAFF_EMAILS.get(staff_name)
            if not email_address:
                print(f"  ⚠ No email address configured for {staff_name}")
                continue
        
        print(f"  Email: {email_address}")
        print(f"  Observations to notify: {len(staff_notifications)}")
        for notif in staff_notifications:
            print(f"    - {notif['species_name']} ({notif['programme']}) in {notif['operating_area']}")
        
        # Track staff member notifications
        if staff_name not in results['staff_notifications']:
            results['staff_notifications'][staff_name] = {
                'email': email_address,
                'count': 0
            }
        
        immediate_notifications = [
            n for n in staff_notifications 
            if n['programme'] in ['Eradication', 'Exclusion']
        ]
        
        pc_amz_notifications = [
            n for n in staff_notifications
            if n['programme'] == 'Progressive Containment' 
            and n.get('designation') == 'AMZ'
        ]
        
        if immediate_notifications:
            for programme in ['Eradication', 'Exclusion']:
                programme_obs = [n for n in immediate_notifications if n['programme'] == programme]
                
                if programme_obs:
                    operating_area = programme_obs[0]['operating_area']
                    subject, html_body = create_immediate_alert_email(
                        programme_obs, staff_name, operating_area
                    )
                    
                    print(f"  Sending {programme} alert ({len(programme_obs)} obs)...")
                    if send_email(email_address, subject, html_body):
                        print(f"  ✓ Sent to {email_address}")
                        results['emails_sent'] += 1
                        results['staff_notifications'][staff_name]['count'] += len(programme_obs)
                    else:
                        results['emails_failed'] += 1
        
        if is_friday and (pc_amz_notifications or immediate_notifications):
            weekly_obs = immediate_notifications + pc_amz_notifications
            operating_area = weekly_obs[0]['operating_area']
            
            subject, html_body = create_weekly_summary_email(
                weekly_obs, staff_name, operating_area
            )
            
            print(f"  Sending weekly summary ({len(weekly_obs)} obs)...")
            if send_email(email_address, subject, html_body):
                print(f"  ✓ Sent to {email_address}")
                results['emails_sent'] += 1
            else:
                results['emails_failed'] += 1
    
    print(f"\n{'='*70}")
    print(f"NOTIFICATION SUMMARY")
    print(f"{'='*70}")
    print(f"Emails sent successfully: {results['emails_sent']}")
    print(f"Emails failed: {results['emails_failed']}")
    
    if not TESTING_MODE and results['emails_sent'] > 0:
        try:
            os.remove(notification_file_path)
            print(f"\n✓ Cleared pending notifications file")
        except:
            print(f"\n⚠ Could not clear pending notifications file")
    elif TESTING_MODE:
        print(f"\n⚠ Testing mode - pending notifications NOT cleared")
    
    print(f"\n{'='*70}\n")
    
    return results

# ============================================================================
# ADMIN NOTIFICATION FUNCTIONS
# ============================================================================

def send_refresh_token_warning(days_remaining, admin_email):
    """
    Send warning email when refresh token is about to expire
    
    Parameters:
    -----------
    days_remaining : int
        Number of days until refresh token expires
    admin_email : str
        Email address to send warning to
    """
    subject = "⚠️ iNaturalist Refresh Token Expiring Soon"
    
    html_body = f"""
    <html>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="background-color: #ff9800; color: white; padding: 15px; border-radius: 5px 5px 0 0;">
                <h2 style="margin: 0;">⚠️ Action Required: Refresh Token Expiring</h2>
            </div>
            
            <div style="background-color: #f5f5f5; padding: 20px; border-radius: 0 0 5px 5px;">
                <p style="font-size: 16px;">Hi,</p>
                
                <p>The iNaturalist OAuth refresh token will expire in <strong>{days_remaining} days</strong>.</p>
                
                <p style="background-color: #fff3cd; padding: 15px; border-left: 4px solid #ff9800;">
                    <strong>Action Required:</strong><br>
                    You need to manually re-authenticate with iNaturalist before the token expires to keep the automated script running.
                </p>
                
                <p><strong>Steps to re-authenticate:</strong></p>
                <ol>
                    <li>Open the RPMP_iNat.ipynb notebook in ArcGIS Pro</li>
                    <li>Delete the <code>inat_token.json</code> file</li>
                    <li>Run the OAuth Authentication cell</li>
                    <li>Follow the prompts to log in and authorize</li>
                </ol>
                
                <p>Once re-authenticated, the script will run automatically for another ~6 months.</p>
                
                <p style="font-size: 12px; color: #666; margin-top: 20px;">
                    This is an automated notification from the Horizons RPMP iNaturalist monitoring system.
                    Generated on {datetime.now().strftime('%d %B %Y at %I:%M %p')}.
                </p>
            </div>
        </div>
    </body>
    </html>
    """
    
    try:
        send_email(admin_email, subject, html_body)
        return True
    except Exception as e:
        print(f"Failed to send refresh token warning: {e}")
        return False


def send_run_summary(summary_data, admin_email):
    """
    Send summary email after each script run
    
    Parameters:
    -----------
    summary_data : dict
        Dictionary containing run summary information:
        {
            'success': bool,
            'total_observations': int,
            'new_observations': int,
            'observations_by_programme': dict,
            'staff_notified': list of dicts with 'name' and 'count',
            'agol_updated': bool,
            'errors': list of str (optional)
        }
    admin_email : str
        Email address to send summary to
    """
    
    # Determine overall status
    if summary_data.get('success', False):
        status_color = "#4CAF50"
        status_icon = "✅"
        status_text = "SUCCESS"
    else:
        status_color = "#f44336"
        status_icon = "❌"
        status_text = "FAILED"
    
    subject = f"iNaturalist Script Run Summary - {status_text}"
    
    # Build programme breakdown
    prog_breakdown = ""
    if summary_data.get('observations_by_programme'):
        prog_breakdown = "<h3>Observations by Programme:</h3><ul>"
        for prog, count in summary_data['observations_by_programme'].items():
            prog_breakdown += f"<li><strong>{prog}:</strong> {count}</li>"
        prog_breakdown += "</ul>"
    
    # Build notification summary
    notification_summary = ""
    if summary_data.get('staff_notified'):
        notification_summary = "<h3>Staff Notified:</h3><ul>"
        for staff in summary_data['staff_notified']:
            notification_summary += f"<li><strong>{staff['name']}:</strong> {staff['count']} observation(s)</li>"
        notification_summary += "</ul>"
    else:
        notification_summary = "<p>✓ No staff notifications sent (no new Eradication/Exclusion observations)</p>"
    
    # Build error list
    error_section = ""
    if summary_data.get('errors'):
        error_section = "<div style='background-color: #ffebee; padding: 15px; border-left: 4px solid #f44336; margin: 15px 0;'>"
        error_section += "<h3 style='color: #c62828; margin-top: 0;'>Errors Encountered:</h3><ul>"
        for error in summary_data['errors']:
            error_section += f"<li>{error}</li>"
        error_section += "</ul></div>"
    
    html_body = f"""
    <html>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="background-color: {status_color}; color: white; padding: 15px; border-radius: 5px 5px 0 0;">
                <h2 style="margin: 0;">{status_icon} iNaturalist Script Run Summary</h2>
            </div>
            
            <div style="background-color: #f5f5f5; padding: 20px; border-radius: 0 0 5px 5px;">
                <p style="font-size: 16px;"><strong>Run completed:</strong> {datetime.now().strftime('%A, %d %B %Y at %I:%M %p')}</p>
                
                <div style="background-color: white; padding: 15px; border-radius: 5px; margin: 15px 0;">
                    <h3 style="margin-top: 0;">📊 Observation Summary</h3>
                    <table style="width: 100%; border-collapse: collapse;">
                        <tr>
                            <td style="padding: 8px; border-bottom: 1px solid #ddd;"><strong>Total Observations:</strong></td>
                            <td style="padding: 8px; border-bottom: 1px solid #ddd; text-align: right;">{summary_data.get('total_observations', 0)}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px; border-bottom: 1px solid #ddd;"><strong>New Observations:</strong></td>
                            <td style="padding: 8px; border-bottom: 1px solid #ddd; text-align: right; color: #4CAF50; font-weight: bold;">{summary_data.get('new_observations', 0)}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px;"><strong>AGOL Updated:</strong></td>
                            <td style="padding: 8px; text-align: right;">{'✅ Yes' if summary_data.get('agol_updated', False) else '❌ No'}</td>
                        </tr>
                    </table>
                </div>
                
                {prog_breakdown}
                
                <div style="background-color: white; padding: 15px; border-radius: 5px; margin: 15px 0;">
                    <h3 style="margin-top: 0;">📧 Notifications</h3>
                    {notification_summary}
                </div>
                
                {error_section}
                
                <p style="font-size: 12px; color: #666; margin-top: 20px;">
                    This is an automated summary from the Horizons RPMP iNaturalist monitoring system.
                </p>
            </div>
        </div>
    </body>
    </html>
    """
    
    try:
        send_email(admin_email, subject, html_body)
        return True
    except Exception as e:
        print(f"Failed to send run summary: {e}")
        return False

