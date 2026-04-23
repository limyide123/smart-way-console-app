# smart-way-console-app

# Smart Waste Collection & Recycling System

## Overview

The Smart Waste Collection & Recycling System is a web-based application designed to improve waste management efficiency and encourage recycling through a reward-based system. The system supports three main user roles: **Resident**, **Waste Collector**, and **Municipal Admin**.

Residents can submit recycling logs and earn reward points, collectors manage collection operations, and admins oversee the entire system including zones, schedules, and system settings.

---

## Features

### Resident

* Register and login
* Submit recycling logs (with waste type, weight, and optional image upload)
* Earn reward points based on recycling weight
* View reward points and streak days
* View pickup schedules based on assigned zone
* View notifications
* Manage profile information

### Waste Collector

* Login to collector dashboard
* View assigned zones
* View assigned routes (auto-updated when admin assigns zones)
* Update collection status (Collected / Pending / Missed)
* Report bin issues (Overflow / Damaged)

### Municipal Admin

* Login to admin dashboard
* View system statistics (total logs, total weight)
* Manage zones (Add / Edit / Delete)
* Assign collectors to zones
* Manage pickup schedules
* View reported bin issues
* Manage system settings (e.g., reward_rate)

---

## System Architecture

The system follows a **client-server architecture**:

* **Frontend:** HTML, CSS, JavaScript (single-page interface)
* **Backend:** Flask (Python)
* **Database:** SQLite

---

## Project Structure

```
smart_waste_console_app/
│
├── app.py                     # Main Flask application
├── database/
│   └── schema.sql            # Database schema
├── subsystems/
│   ├── integration/          # Authentication & shared logic
│   ├── resident/             # Resident features
│   ├── collector/            # Collector features
│   └── admin/                # Admin features
├── static/
│   ├── recycle.css           # Stylesheet
│   └── uploads/              # Uploaded images
├── templates/
│   └── index.html            # Main UI page
└── README.txt
```

---

## Installation & Setup

### 1. Install Requirements

Make sure you have Python 3 installed.

Install required packages:

```
pip install flask werkzeug
```

### 2. Run the Application

```
python app.py
```

### 3. Open in Browser

```
http://127.0.0.1:5000
```

---

## Demo Accounts

Use these accounts for testing:

**Resident**

* Email: [alice@gmail.com](mailto:alice@gmail.com)
* Password: resident123

**Collector**

* Email: [collector@gmail.com](mailto:collector@gmail.com)
* Password: collector123

**Admin**

* Email: [admin@gmail.com](mailto:admin@gmail.com)
* Password: admin123

---

## Key System Settings

* `reward_rate` → Points earned per 1 kg of recycling
  (Example: 10 = 10 points per kg)

---

## Usage Guide

### Resident Flow

1. Login as Resident
2. Submit recycling log
3. Earn reward points automatically
4. View schedule and notifications

### Collector Flow

1. Login as Collector
2. View assigned zones and routes
3. Update collection status
4. Report any bin issues

### Admin Flow

1. Login as Admin
2. Manage zones and schedules
3. Assign collectors
4. Monitor system performance
5. Adjust system settings

---

## Notes

* SQLite is used for simplicity (no external DB required)
* Uploaded images are stored locally in `/static/uploads`
* Routes are dynamically updated when assignments change

---

## Future Improvements

* Real-time notifications (push/email)
* Advanced route optimization (AI-based)
* Mobile app version
* Map integration for routes and zones

---

## Authors

* Lim Yi De
* Lim Ren Liang
* Wong Lei
* Sulaiman

---

## Conclusion

This system demonstrates a complete smart waste management workflow, integrating multiple user roles into a unified platform. It promotes sustainability while improving operational efficiency through automation and data-driven features.
