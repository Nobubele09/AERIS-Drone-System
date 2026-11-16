import os
from io import BytesIO
from functools import wraps
from datetime import datetime

import mysql.connector
from mysql.connector import Error

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
    send_file
)

from werkzeug.security import (
    generate_password_hash,
    check_password_hash
)

# PDF GENERATION
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle
)


# ==================================================
# AERIS APPLICATION CONFIGURATION
# ==================================================

app = Flask(__name__)

app.secret_key = os.environ.get(
    "AERIS_SECRET_KEY",
    "development-only-change-this-secret"
)

app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": os.environ.get("AERIS_DB_PASSWORD", ""),
    "database": "aeris"
}


# ==================================================
# DATABASE CONNECTION
# ==================================================

def get_db_connection():
    """Create a new MySQL connection when needed."""
    return mysql.connector.connect(**DB_CONFIG)


def record_login(user_id, fullname, email, role):
    """Record a successful user login in the login_history table."""

    db = None
    cursor = None

    try:
        db = get_db_connection()
        cursor = db.cursor()

        cursor.execute(
            """
            INSERT INTO login_history
                (user_id, fullname, email, role)
            VALUES (%s, %s, %s, %s)
            """,
            (user_id, fullname, email, role)
        )

        db.commit()

    except Error:
        if db is not None:
            db.rollback()

        # Keep the login available even if audit logging fails.
        app.logger.exception("Could not record login activity.")

    finally:
        if cursor is not None:
            cursor.close()

        if db is not None and db.is_connected():
            db.close()



def record_activity(user_id, fullname, role, action, description):
    """Record an action in the system_activity table."""

    db = None
    cursor = None

    try:
        db = get_db_connection()
        cursor = db.cursor()

        cursor.execute(
            """
            INSERT INTO system_activity
                (user_id, fullname, role, action, description)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (user_id, fullname, role, action, description)
        )

        db.commit()

    except Error:
        if db is not None:
            db.rollback()

        app.logger.exception("Could not record system activity.")

    finally:
        if cursor is not None:
            cursor.close()

        if db is not None and db.is_connected():
            db.close()


# ==================================================
# LOGIN PROTECTION
# ==================================================

def login_required(view_function):
    """Require a logged-in user before opening a page."""

    @wraps(view_function)
    def wrapped_view(*args, **kwargs):

        if "user_id" not in session:
            flash(
                "Please log in to access this feature.",
                "warning"
            )
            return redirect(url_for("login"))

        return view_function(*args, **kwargs)

    return wrapped_view


# ==================================================
# STAFF ROLE PROTECTION
# ==================================================

def staff_required(view_function):
    """Allow only authorised staff to access a page."""

    @wraps(view_function)
    @login_required
    def wrapped_view(*args, **kwargs):

        if session.get("role") not in {
            "Super Admin",
            "Admin",
            "Operations Manager",
            "Drone Operator",
            "Emergency Response Officer",
            "Monitoring Officer"
        }:
            flash(
                "You are not authorised to access this feature.",
                "danger"
            )
            return redirect(url_for("dashboard"))

        return view_function(*args, **kwargs)

    return wrapped_view


def super_admin_required(view_function):
    """Allow only the Super Admin to download management reports."""

    @wraps(view_function)
    @login_required
    def wrapped_view(*args, **kwargs):
        if session.get("role") != "Super Admin":
            flash("Only the Super Admin can access these reports.", "danger")
            return redirect(url_for("dashboard"))
        return view_function(*args, **kwargs)

    return wrapped_view


# ==================================================
# HOME PAGE
# ==================================================

@app.route("/")
def home():
    return render_template("index.html")


# ==================================================
# ACCOUNT REGISTRATION
# ==================================================

@app.route("/signup", methods=["GET", "POST"])
def signup():

    if request.method == "POST":

        fullname = request.form.get("fullname", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not fullname or not email or not password:
            flash(
                "Please complete all the required fields.",
                "danger"
            )
            return render_template("signup.html")

        if len(fullname) > 150:
            flash("Your full name is too long.", "danger")
            return render_template("signup.html")

        if len(email) > 254 or "@" not in email:
            flash("Please enter a valid email address.", "danger")
            return render_template("signup.html")

        if len(password) < 8:
            flash(
                "Your password must contain at least 8 characters.",
                "danger"
            )
            return render_template("signup.html")

        db = None
        cursor = None

        try:
            db = get_db_connection()
            cursor = db.cursor()

            cursor.execute(
                "SELECT id FROM users WHERE email = %s",
                (email,)
            )

            if cursor.fetchone():
                flash(
                    "An account with this email already exists.",
                    "warning"
                )
                return render_template("signup.html")

            password_hash = generate_password_hash(password)

            # Public registration cannot assign staff roles.
            cursor.execute(
                """
                INSERT INTO users (fullname, email, password, role)
                VALUES (%s, %s, %s, %s)
                """,
                (fullname, email, password_hash, "Public")
            )

            db.commit()

            cursor.execute(
                """
                SELECT id, fullname, role
                FROM users
                WHERE email = %s
                """,
                (email,)
            )

            user = cursor.fetchone()

            session.clear()
            session["user_id"] = user[0]
            session["fullname"] = user[1]
            session["role"] = user[2]

            flash(
                "Your AERIS account was created successfully!",
                "success"
            )

            return redirect(url_for("dashboard"))

        except Error:
            if db is not None:
                db.rollback()

            app.logger.exception("Account registration failed.")

            flash(
                "We could not create your account. "
                "Please check the database configuration and try again.",
                "danger"
            )

        finally:
            if cursor is not None:
                cursor.close()

            if db is not None and db.is_connected():
                db.close()

    return render_template("signup.html")


# ==================================================
# LOGIN
# ==================================================

@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not email or not password:
            flash(
                "Enter your email and password.",
                "danger"
            )
            return render_template("login.html")

        db = None
        cursor = None

        try:
            db = get_db_connection()
            cursor = db.cursor()

            cursor.execute(
                """
                SELECT id, fullname, email, password, role
                FROM users
                WHERE email = %s
                """,
                (email,)
            )

            user = cursor.fetchone()

            if user and check_password_hash(user[3], password):

                session.clear()
                session["user_id"] = user[0]
                session["fullname"] = user[1]
                session["role"] = user[4]

                # Save the successful login date and time.
                record_login(
                    user[0],
                    user[1],
                    user[2],
                    user[4]
                )

                record_activity(
                    user[0], user[1], user[4],
                    "LOGIN", "User successfully logged in."
                )

                return redirect(url_for("dashboard"))

            flash(
                "Invalid email or password.",
                "danger"
            )

        except Error:
            app.logger.exception("Login database operation failed.")

            flash(
                "Login is temporarily unavailable. "
                "Please check the database connection.",
                "danger"
            )

        finally:
            if cursor is not None:
                cursor.close()

            if db is not None and db.is_connected():
                db.close()

    return render_template("login.html")


# ==================================================
# AERIS DASHBOARD WITH INCIDENT FILTERING
# ==================================================

@app.route("/dashboard")
@login_required
def dashboard():

    db = None
    cursor = None

    selected_status = request.args.get(
        "status", ""
    ).strip()

    selected_type = request.args.get(
        "incident_type", ""
    ).strip()

    selected_severity = request.args.get(
        "severity", ""
    ).strip().lower()

    allowed_statuses = {
        "Active",
        "In Progress",
        "Resolved",
        "Closed"
    }

    allowed_severities = {
        "low",
        "medium",
        "high",
        "critical"
    }

    if selected_status not in allowed_statuses:
        selected_status = ""

    if selected_severity not in allowed_severities:
        selected_severity = ""

    try:
        db = get_db_connection()
        cursor = db.cursor()

        # TOTAL INCIDENTS
        cursor.execute("SELECT COUNT(*) FROM incidents")
        total = cursor.fetchone()[0]

        # INCIDENT STATISTICS
        cursor.execute(
            """
            SELECT incident_type, COUNT(*)
            FROM incidents
            GROUP BY incident_type
            """
        )

        incident_counts = cursor.fetchall()

        fires = 0
        floods = 0
        accidents = 0

        for incident_type, count in incident_counts:

            incident_name = (
                incident_type or ""
            ).strip().lower()

            if "fire" in incident_name:
                fires += count

            elif "flood" in incident_name:
                floods += count

            elif (
                "accident" in incident_name
                or "collision" in incident_name
            ):
                accidents += count

        # AVAILABLE INCIDENT TYPES
        cursor.execute(
            """
            SELECT DISTINCT incident_type
            FROM incidents
            ORDER BY incident_type
            """
        )

        incident_types = [
            row[0] for row in cursor.fetchall()
        ]

        # FILTERED INCIDENT QUERY
        query = """
            SELECT id, incident_type, location, severity,
                   status, detected_at
            FROM incidents
            WHERE 1 = 1
        """

        parameters = []

        if selected_status:
            query += " AND status = %s"
            parameters.append(selected_status)

        if selected_type:

            if selected_type in incident_types:
                query += " AND incident_type = %s"
                parameters.append(selected_type)

            else:
                selected_type = ""

        if selected_severity:
            query += " AND LOWER(severity) = %s"
            parameters.append(selected_severity)

        query += " ORDER BY detected_at DESC"

        cursor.execute(query, tuple(parameters))

        recent_incidents = cursor.fetchall()

        return render_template(
            "dashboard.html",
            fullname=session.get("fullname", "User"),
            role=session.get("role", "Public"),
            total=total,
            fires=fires,
            floods=floods,
            accidents=accidents,
            recent_incidents=recent_incidents,
            incident_types=incident_types,
            selected_status=selected_status,
            selected_type=selected_type,
            selected_severity=selected_severity
        )

    except Error:
        app.logger.exception(
            "Dashboard database operation failed."
        )

        flash(
            "The dashboard could not load its information. "
            "Please check your database connection.",
            "danger"
        )

        return render_template(
            "dashboard.html",
            fullname=session.get("fullname", "User"),
            role=session.get("role", "Public"),
            total=0,
            fires=0,
            floods=0,
            accidents=0,
            recent_incidents=[],
            incident_types=[],
            selected_status=selected_status,
            selected_type=selected_type,
            selected_severity=selected_severity
        )

    finally:
        if cursor is not None:
            cursor.close()

        if db is not None and db.is_connected():
            db.close()


# ==================================================
# MANAGEMENT REPORTS PAGE
# ==================================================

@app.route("/reports")
@super_admin_required
def reports_page():
    """Display the downloadable PDF reports page."""
    return render_template(
        "reports.html",
        fullname=session.get("fullname", "User"),
        role=session.get("role", "Super Admin")
    )


# ==================================================
# ADMINISTRATOR MANAGEMENT (SUPER ADMIN ONLY)
# ==================================================

@app.route("/admin-management")
@super_admin_required
def admin_management():
    """Show administrator accounts. Only the Super Admin can manage them."""
    db = None
    cursor = None
    try:
        db = get_db_connection()
        cursor = db.cursor()
        cursor.execute(
            """
            SELECT id, fullname, email
            FROM users
            WHERE role = %s
            ORDER BY fullname ASC
            """,
            ("Admin",)
        )
        administrators = cursor.fetchall()
        return render_template(
            "admin_management.html",
            fullname=session.get("fullname", "Super Admin"),
            role=session.get("role", "Super Admin"),
            administrators=administrators
        )
    except Error:
        app.logger.exception("Could not load administrator accounts.")
        flash("Administrator accounts could not be loaded.", "danger")
        return redirect(url_for("dashboard"))
    finally:
        if cursor is not None:
            cursor.close()
        if db is not None and db.is_connected():
            db.close()


@app.route("/admin-management/add", methods=["POST"])
@super_admin_required
def add_administrator():
    """Create a standard Admin account; public signup cannot assign this role."""
    fullname = request.form.get("fullname", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    if not fullname or not email or not password:
        flash("Complete all fields to add an administrator.", "danger")
        return redirect(url_for("admin_management"))

    # The existing MySQL users table uses fullname/email columns of 100 chars.
    if len(fullname) > 100 or len(email) > 100 or "@" not in email:
        flash("Enter a valid name and email address (maximum 100 characters each).", "danger")
        return redirect(url_for("admin_management"))

    if len(password) < 8:
        flash("The temporary password must contain at least 8 characters.", "danger")
        return redirect(url_for("admin_management"))

    db = None
    cursor = None
    try:
        db = get_db_connection()
        cursor = db.cursor()
        cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
        if cursor.fetchone():
            flash("An account with that email address already exists.", "warning")
            return redirect(url_for("admin_management"))

        password_hash = generate_password_hash(password)
        cursor.execute(
            """
            INSERT INTO users (fullname, email, password, role)
            VALUES (%s, %s, %s, %s)
            """,
            (fullname, email, password_hash, "Admin")
        )
        new_admin_id = cursor.lastrowid
        db.commit()

        record_activity(
            session.get("user_id"), session.get("fullname", "Super Admin"),
            session.get("role", "Super Admin"), "ADMIN_CREATED",
            f"Created Admin account for {fullname} ({email}), user ID {new_admin_id}."
        )
        flash(f"Administrator account created for {fullname}.", "success")
    except Error:
        if db is not None:
            db.rollback()
        app.logger.exception("Could not create administrator account.")
        flash("The administrator account could not be created.", "danger")
    finally:
        if cursor is not None:
            cursor.close()
        if db is not None and db.is_connected():
            db.close()

    return redirect(url_for("admin_management"))


@app.route("/admin-management/remove/<int:user_id>", methods=["POST"])
@super_admin_required
def remove_administrator(user_id):
    """Remove a standard Admin account; never delete Super Admin accounts."""
    db = None
    cursor = None
    try:
        db = get_db_connection()
        cursor = db.cursor()
        cursor.execute(
            "SELECT fullname, email, role FROM users WHERE id = %s",
            (user_id,)
        )
        target = cursor.fetchone()

        if not target:
            flash("That user account could not be found.", "warning")
            return redirect(url_for("admin_management"))

        if target[2] != "Admin":
            flash("Only standard Admin accounts can be removed here.", "danger")
            return redirect(url_for("admin_management"))

        if user_id == session.get("user_id"):
            flash("You cannot remove the account you are currently using.", "danger")
            return redirect(url_for("admin_management"))

        cursor.execute("DELETE FROM users WHERE id = %s AND role = %s", (user_id, "Admin"))
        db.commit()

        record_activity(
            session.get("user_id"), session.get("fullname", "Super Admin"),
            session.get("role", "Super Admin"), "ADMIN_REMOVED",
            f"Removed Admin account {target[0]} ({target[1]}), user ID {user_id}."
        )
        flash(f"Administrator access removed for {target[0]}.", "success")
    except Error:
        if db is not None:
            db.rollback()
        app.logger.exception("Could not remove administrator account.")
        flash("The administrator account could not be removed.", "danger")
    finally:
        if cursor is not None:
            cursor.close()
        if db is not None and db.is_connected():
            db.close()

    return redirect(url_for("admin_management"))



# ==================================================
# REPORT AN EMERGENCY INCIDENT
# ==================================================

from pathlib import Path
import math
import json
import tempfile


def get_mission_bridge_folder():
    """Find the shared mission_bridge folder inside AERIS_Project."""

    app_directory = Path(__file__).resolve().parent

    for parent in app_directory.parents:
        bridge_folder = parent / "mission_bridge"

        if bridge_folder.is_dir():
            return bridge_folder

    raise FileNotFoundError(
        "Could not find the mission_bridge folder."
    )


def create_drone_mission(
    incident_id,
    incident_type,
    location,
    severity,
    x_coordinate,
    z_coordinate
):
    """Write a mission for the Webots controller."""

    bridge_folder = get_mission_bridge_folder()
    bridge_folder.mkdir(parents=True, exist_ok=True)

    mission = {
        "incident_id": incident_id,
        "incident_type": incident_type,
        "location": location,
        "severity": severity,
        "x_coordinate": x_coordinate,
        "z_coordinate": z_coordinate,
        "status": "Pending"
    }

    mission_file = bridge_folder / "mission.txt"
    temporary_file = bridge_folder / "mission.tmp"

    with open(temporary_file, "w", encoding="utf-8") as file:
        json.dump(mission, file, indent=4)

    os.replace(temporary_file, mission_file)

    app.logger.info(
        "Drone mission created: %s",
        mission_file
    )

@app.route("/report", methods=["GET", "POST"])
@login_required
def report():

    if request.method == "POST":

        incident_type = request.form.get(
            "incident_type", ""
        ).strip()

        severity = request.form.get(
            "severity", ""
        ).strip().lower()

        # AERIS uses Tembisa as its default response location.
        location = "Tembisa"

        # Webots destination coordinates for each incident marker.
        incident_destinations = {
            "Fire": (-48.0, 18.0),
            "Flood": (48.0, 18.0),
            "Accident": (0.0, -78.0)
        }

        # Validate incident type.
        if incident_type not in incident_destinations:
            flash(
                "Select Fire, Flood or Accident.",
                "danger"
            )
            return render_template("report_incident.html")

        # Validate severity.
        allowed_severities = {
            "low",
            "medium",
            "high",
            "critical"
        }

        if severity not in allowed_severities:
            flash(
                "Select a valid incident severity.",
                "danger"
            )
            return render_template("report_incident.html")

        # Automatically assign the Webots destination.
        x_coordinate, z_coordinate = incident_destinations[
            incident_type
        ]

        db = None
        cursor = None

        try:
            db = get_db_connection()
            cursor = db.cursor()

            cursor.execute(
                """
                INSERT INTO incidents
                    (
                        incident_type,
                        location,
                        severity,
                        reported_by,
                        x_coordinate,
                        z_coordinate
                    )
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    incident_type,
                    location,
                    severity,
                    session.get("user_id"),
                    x_coordinate,
                    z_coordinate
                )
            )

            incident_id = cursor.lastrowid
            db.commit()

            record_activity(
                session.get("user_id"),
                session.get("fullname", "Unknown"),
                session.get("role", "Public"),
                "INCIDENT REPORTED",
                f"Reported {incident_type} incident at {location} "
                f"with {severity} severity."
            )

            # Prepare the autonomous drone mission.
            try:
                create_drone_mission(
                    incident_id,
                    incident_type,
                    location,
                    severity,
                    x_coordinate,
                    z_coordinate
                )

                flash(
                    "Incident recorded and drone mission prepared!",
                    "success"
                )

            except OSError:
                app.logger.exception(
                    "Could not write the Webots mission file."
                )

                flash(
                    "Incident recorded, but the drone mission "
                    "could not be prepared.",
                    "warning"
                )

            return redirect(url_for("dashboard"))

        except Error:
            if db is not None:
                db.rollback()

            app.logger.exception(
                "Incident registration failed."
            )

            flash(
                "The incident could not be saved. Please try again.",
                "danger"
            )

        finally:
            if cursor is not None:
                cursor.close()

            if db is not None and db.is_connected():
                db.close()

    return render_template("report_incident.html")

# ==================================================
# UPDATE INCIDENT STATUS
# ==================================================

@app.route(
    "/update_incident/<int:incident_id>",
    methods=["POST"]
)
@staff_required
def update_incident(incident_id):

    new_status = request.form.get(
        "status", ""
    ).strip()

    allowed_statuses = {
        "Active",
        "In Progress",
        "Resolved",
        "Closed"
    }

    if new_status not in allowed_statuses:

        flash(
            "Invalid incident status selected.",
            "danger"
        )

        return redirect(url_for("dashboard"))

    db = None
    cursor = None

    try:
        db = get_db_connection()
        cursor = db.cursor()

        cursor.execute(
            """
            UPDATE incidents
            SET status = %s
            WHERE id = %s
            """,
            (new_status, incident_id)
        )

        if cursor.rowcount == 0:

            flash(
                "Incident not found.",
                "warning"
            )

        else:

            db.commit()

            record_activity(
                session.get("user_id"),
                session.get("fullname", "Unknown"),
                session.get("role", "Staff"),
                "INCIDENT STATUS UPDATED",
                f"Updated incident #{incident_id} status to {new_status}."
            )

            flash(
                "Incident status updated successfully.",
                "success"
            )

    except Error:
        if db is not None:
            db.rollback()

        app.logger.exception(
            "Incident status update failed."
        )

        flash(
            "Could not update the incident status.",
            "danger"
        )

    finally:
        if cursor is not None:
            cursor.close()

        if db is not None and db.is_connected():
            db.close()

    return redirect(url_for("dashboard"))


# ==================================================
# PDF REPORT GENERATION
# ==================================================

def generate_incident_pdf(incidents, generated_by):
    """
    Generate a downloadable PDF containing real
    incident records retrieved from MySQL.
    """

    pdf_buffer = BytesIO()

    document = SimpleDocTemplate(
        pdf_buffer,
        pagesize=landscape(A4),
        rightMargin=15 * mm,
        leftMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "AERISTitle",
        parent=styles["Title"],
        alignment=TA_CENTER,
        fontSize=22,
        textColor=colors.HexColor("#102A43"),
        spaceAfter=8
    )

    subtitle_style = ParagraphStyle(
        "AERISSubtitle",
        parent=styles["Normal"],
        alignment=TA_CENTER,
        fontSize=10,
        textColor=colors.HexColor("#52606D"),
        spaceAfter=15
    )

    normal_style = styles["Normal"]

    story = []

    # REPORT HEADING
    story.append(
        Paragraph("AERIS", title_style)
    )

    story.append(
        Paragraph(
            "INCIDENT MANAGEMENT REPORT",
            subtitle_style
        )
    )

    story.append(
        Paragraph(
            "AI Drone System for Autonomous Emergency "
            "Response and Disaster Surveillance",
            subtitle_style
        )
    )

    story.append(Spacer(1, 5 * mm))

    # REPORT INFORMATION
    generated_time = datetime.now().strftime(
        "%d %B %Y at %H:%M"
    )

    story.append(
        Paragraph(
            f"<b>Generated by:</b> {generated_by}",
            normal_style
        )
    )

    story.append(
        Paragraph(
            f"<b>Date generated:</b> {generated_time}",
            normal_style
        )
    )

    story.append(
        Paragraph(
            f"<b>Total incidents:</b> {len(incidents)}",
            normal_style
        )
    )

    story.append(Spacer(1, 8 * mm))

    # TABLE HEADINGS
    table_data = [
        [
            "Incident ID",
            "Incident Type",
            "Location",
            "Severity",
            "Status",
            "Date Recorded"
        ]
    ]

    # TABLE RECORDS
    for incident in incidents:

        incident_date = incident[5]

        if incident_date:
            incident_date = incident_date.strftime(
                "%d/%m/%Y %H:%M"
            )
        else:
            incident_date = "Not available"

        table_data.append([
            str(incident[0]),
            str(incident[1]),
            str(incident[2]),
            str(incident[3]).upper(),
            str(incident[4]),
            incident_date
        ])

    if not incidents:
        table_data.append([
            "No incidents",
            "",
            "",
            "",
            "",
            ""
        ])

    # CREATE TABLE
    report_table = Table(
        table_data,
        repeatRows=1,
        colWidths=[
            25 * mm,
            38 * mm,
            45 * mm,
            25 * mm,
            30 * mm,
            42 * mm
        ]
    )

    report_table.setStyle(
        TableStyle([
            (
                "BACKGROUND",
                (0, 0),
                (-1, 0),
                colors.HexColor("#102A43")
            ),
            (
                "TEXTCOLOR",
                (0, 0),
                (-1, 0),
                colors.white
            ),
            (
                "FONTNAME",
                (0, 0),
                (-1, 0),
                "Helvetica-Bold"
            ),
            (
                "FONTSIZE",
                (0, 0),
                (-1, -1),
                8
            ),
            (
                "GRID",
                (0, 0),
                (-1, -1),
                0.5,
                colors.HexColor("#D9E2EC")
            ),
            (
                "VALIGN",
                (0, 0),
                (-1, -1),
                "MIDDLE"
            ),
            (
                "ROWBACKGROUNDS",
                (0, 1),
                (-1, -1),
                [
                    colors.white,
                    colors.HexColor("#F0F4F8")
                ]
            ),
            (
                "TOPPADDING",
                (0, 0),
                (-1, -1),
                8
            ),
            (
                "BOTTOMPADDING",
                (0, 0),
                (-1, -1),
                8
            )
        ])
    )

    story.append(report_table)

    story.append(Spacer(1, 10 * mm))

    story.append(
        Paragraph(
            "AERIS | Emergency Operations Platform",
            subtitle_style
        )
    )

    # BUILD PDF
    document.build(story)

    pdf_buffer.seek(0)

    return pdf_buffer


# ==================================================
# DOWNLOAD INCIDENT PDF REPORT
# ==================================================

def generate_table_pdf(report_title, columns, rows, generated_by):
    """Build a formatted PDF report from database records."""

    pdf_buffer = BytesIO()
    document = SimpleDocTemplate(
        pdf_buffer,
        pagesize=landscape(A4),
        rightMargin=12 * mm,
        leftMargin=12 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "AERISTitle",
        parent=styles["Title"],
        alignment=TA_CENTER,
        fontSize=21,
        textColor=colors.HexColor("#102A43"),
        spaceAfter=6
    )
    subtitle_style = ParagraphStyle(
        "AERISSubtitle",
        parent=styles["Normal"],
        alignment=TA_CENTER,
        fontSize=10,
        textColor=colors.HexColor("#52606D"),
        spaceAfter=12
    )

    story = [
        Paragraph("AERIS", title_style),
        Paragraph(report_title.upper(), subtitle_style),
        Paragraph(
            "AI Drone System for Autonomous Emergency Response "
            "and Disaster Surveillance",
            subtitle_style
        ),
        Spacer(1, 4 * mm),
        Paragraph(f"<b>Generated by:</b> {generated_by}", styles["Normal"]),
        Paragraph(
            f"<b>Date generated:</b> {datetime.now().strftime('%d %B %Y at %H:%M:%S')}",
            styles["Normal"]
        ),
        Paragraph(f"<b>Total records:</b> {len(rows)}", styles["Normal"]),
        Spacer(1, 6 * mm)
    ]

    table_data = [columns]
    for row in rows:
        table_data.append([
            str(value) if value is not None else "Not available"
            for value in row
        ])

    if not rows:
        table_data.append(["No records found"] + [""] * (len(columns) - 1))

    available_width = landscape(A4)[0] - 24 * mm
    col_width = available_width / len(columns)
    report_table = Table(
        table_data,
        repeatRows=1,
        colWidths=[col_width] * len(columns)
    )
    report_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#102A43")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D9E2EC")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor("#F0F4F8")]),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(report_table)
    story.append(Spacer(1, 7 * mm))
    story.append(Paragraph(
        "AERIS | Emergency Operations Platform",
        subtitle_style
    ))

    document.build(story)
    pdf_buffer.seek(0)
    return pdf_buffer


def send_database_report(query, columns, filename_prefix, report_title):
    """Run a report query and return its PDF download response."""

    db = None
    cursor = None
    try:
        db = get_db_connection()
        cursor = db.cursor()
        cursor.execute(query)
        rows = cursor.fetchall()

        pdf_file = generate_table_pdf(
            report_title,
            columns,
            rows,
            session.get("fullname", "Super Admin")
        )
        filename = (
            filename_prefix + "_" +
            datetime.now().strftime("%Y%m%d_%H%M%S") + ".pdf"
        )
        return send_file(
            pdf_file,
            mimetype="application/pdf",
            as_attachment=True,
            download_name=filename
        )
    except Error:
        app.logger.exception("AERIS report database query failed.")
        flash(
            "The report could not be generated. Check that the report tables "
            "and incident reporter column have been created.",
            "danger"
        )
        return redirect(url_for("dashboard"))
    except Exception:
        app.logger.exception("AERIS PDF generation failed.")
        flash("The PDF report could not be generated.", "danger")
        return redirect(url_for("dashboard"))
    finally:
        if cursor is not None:
            cursor.close()
        if db is not None and db.is_connected():
            db.close()


@app.route("/reports/logins/pdf")
@super_admin_required
def download_login_report():
    return send_database_report(
        """
        SELECT fullname, email, role, login_time
        FROM login_history
        ORDER BY login_time DESC
        """,
        ["User", "Email", "Role", "Login Date & Time"],
        "AERIS_Login_Activity_Report",
        "User Login Activity Report"
    )


@app.route("/reports/incidents/pdf")
@super_admin_required
def download_incident_report():
    return send_database_report(
        """
        SELECT
            i.id,
            COALESCE(u.fullname, 'Unknown / historical record'),
            i.incident_type,
            i.location,
            i.severity,
            i.status,
            i.detected_at
        FROM incidents AS i
        LEFT JOIN users AS u ON i.reported_by = u.id
        ORDER BY i.detected_at DESC
        """,
        [
            "Incident ID", "Reported By", "Incident Type", "Location",
            "Severity", "Status", "Date & Time"
        ],
        "AERIS_Incident_Management_Report",
        "Incident Management Report"
    )


@app.route("/reports/activity/pdf")
@super_admin_required
def download_activity_report():
    return send_database_report(
        """
        SELECT fullname, role, action, description, activity_time
        FROM system_activity
        ORDER BY activity_time DESC
        """,
        ["User", "Role", "Action", "Description", "Date & Time"],
        "AERIS_System_Activity_Report",
        "System Activity Report"
    )


# ==================================================
# ==================================================
# LOGOUT
# ==================================================

@app.route("/logout")
def logout():

    if "user_id" in session:
        record_activity(
            session.get("user_id"),
            session.get("fullname", "Unknown"),
            session.get("role", "Public"),
            "LOGOUT",
            "User logged out."
        )

    session.clear()

    flash(
        "You have logged out successfully.",
        "success"
    )

    return redirect(url_for("login"))


# ==================================================
# APPLICATION ENTRY POINT
# ==================================================

if __name__ == "__main__":
    app.run(debug=True)