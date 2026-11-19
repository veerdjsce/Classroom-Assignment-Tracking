# Classroom Assignment & Completion Tracker

A full-stack, responsive, and secure classroom assignment tracker built with Python Flask, SQLite, Tailwind CSS, Chart.js, and Lucide Icons. Designed for teachers and students across **Android, iOS, Windows, and macOS**.

---

## 🚀 Key Features

### 1. 🛡️ User Registration & Strict Admin Approval Gate
- **Join Request**: When a student visits the website for the first time, they sign up, choose their batch, and submit a join request with an optional note (e.g. Roll Number / Section).
- **Approval Wall**: Newly registered student accounts are held in a **Pending Approval** state. They cannot see subjects, assignments, or classroom data until the administrator explicitly approves them.
- **Admin Control**: The administrator can:
  - Approve or decline pending registration requests.
  - Suspend or restore access for any student.
  - Promote a student to Administrator or remove an Administrator.
  - View individual submission rosters for every user.

### 2. 🔒 Strict Student Privacy & Data Isolation
- **Complete Privacy**: No student can see any other student's submission status or marks.
- **Personalized View**: Each student only sees their own marked (completed) vs unmarked (incomplete) tasks and progress bars.
- **Full Admin Visibility**: Only administrators have access to aggregate metrics, student submission rosters, and audit trails.

### 3. 📂 Hierarchical Organization
- **Batches / Sections**: Organize classes (e.g., *Computer Science 2024-2028*, *Section A*).
- **Subjects**: Each batch contains color-coded subjects with custom icons.
- **Assignments**: Each subject contains homework and project tasks with detailed instructions and deadlines.

### 4. ⏱️ Assignment Completion & Deadline Notifications
- **Mark / Unmark**: Students can tick or untick tasks with instant AJAX feedback (no page reloads).
- **Live Countdowns**: Assignments display live countdown badges (*"Due in 4 hours"*, *"Due in 30 minutes"*).
- **Deadline Alerts**: Unmarked tasks approaching deadline or overdue show urgent warning banners and notifications.
- **Sort & Filter**:
  - Filter: *All Tasks*, *Incomplete (Unmarked)*, *Completed (Marked)*, *Overdue*.
  - Sort: *Soonest Deadline*, *Latest Deadline*, *Title (A-Z)*.
  - Search by keyword.

### 5. 🔔 Real-Time Admin Notifications
- **Live Submission Feed**: Whenever any student ticks or unticks an assignment, the administrator receives an in-app notification and an unread badge on their bell icon.
- **Audit Log**: Chronological feed recording exact timestamps, student names, and task details.

### 6. 📊 Admin Completion Analytics & Image Export
- **Live Interactive Graph**: Chart.js stacked bar chart showing how many students have completed vs pending each assignment.
- **Filter by Batch**: Easily analyze completion rates for specific classes.
- **Download Graph as Image (PNG)**: 1-click button exports high-resolution pictures of the graph to share on WhatsApp, Discord, or email.
- **Student Roster Drill-Down**: Click *View Roster* on any assignment to see the exact list of who completed it and who hasn't.

### 7. 🗳️ Classroom Polls & 📢 Broadcasts
- **Polls**: Administrators can create polls with multiple options; students vote and see live percentage progress bars.
- **Announcements**: Administrators can broadcast rich announcements, pin critical notices, or share completion summary updates.

### 8. 📱 Cross-Platform (Android, iOS, Windows, Mac)
- Fully responsive mobile-first UI with viewport optimization.
- Mobile bottom navigation bar for touch devices.
- PWA `manifest.json` allowing students to "Add to Home Screen" on iPhone / iPad / Android devices.

---

## 🔑 Default Administrator Credentials

| Role | Username | Password |
|---|---|---|
| **Classroom Administrator** | `admin` | `admin123` |

*(Note: You can change the admin password at any time from the **Profile** page)*

---

## 🏃 Quick Start Guide

### 1. Requirements
- Python 3.10+ (Tested on Python 3.14)
- Dependencies installed via `requirements.txt`:
  ```bash
  python -m pip install -r requirements.txt
  ```

### 2. Start the Server
Run the production WSGI server with LAN detection:
```bash
python run.py
```

Output:
```
=================================================================
 CLASSROOM ASSIGNMENT TRACKER SERVER STARTED
=================================================================
 Local Machine URL : http://localhost:5000
 Mobile / LAN URL  : http://<YOUR-IP>:5000
 (Classmates on Android, iOS, Windows, Mac on same Wi-Fi
  can open http://<YOUR-IP>:5000 on their browser!)
=================================================================
```

### 3. Accessing from Phones & Classmates' Laptops
- Ensure devices are connected to the same Wi-Fi network.
- Have students open `http://<YOUR-LOCAL-IP>:5000` on Chrome, Safari, or Edge.
- They register their account & batch.
- You log into `http://localhost:5000` as `admin` and click **Review Approvals** to grant them access!

---

## 🧪 Automated Testing
Run the comprehensive test suite verifying isolation, security, and workflows:
```bash
python test_app.py
```
