SMART WASTE COLLECTION & RECYCLING SYSTEM
README (Testing Credentials + User Manual)
Version: 3.3+ (Flask + SQLite)

============================================================
1) HOW TO RUN
============================================================
1. Open a terminal in the project folder.
2. (Optional but recommended) Create and activate a virtual environment.
3. Install dependencies (if requirements.txt exists):
   py -m pip install flask werkzeug

4. Initialize / migrate database (creates tables + seeds demo accounts):
   python migrate_db.py

5. Start the Flask app:
   python app.py

6. Open in browser:
   http://127.0.0.1:5000

Notes:
- Database file: smart_waste.db
- Uploaded images are stored under: static/uploads/

============================================================
2) TEST LOGIN CREDENTIALS (Different Roles)
============================================================

[RESIDENT ACCOUNT]
Role: resident
Email: alice@gmail.com
Password: resident123
Name: Alice Tan (seed)
Default points: 0
Default zone: Zone A (zone_id = 1)

[COLLECTOR ACCOUNT]
Role: collector
Email: john.collector@mail.com
Password: collector123
Name: John Lim (seed)
Default assigned zones: none (admin must assign in Zone Management)

[ADMIN ACCOUNT]
Role: admin
Email: admin@municipal.gov
Password: admin123
Name: Admin One (seed)

============================================================
3) USER MANUAL (BY ROLE)
============================================================

------------------------------------------------------------
A) RESIDENT USER MANUAL
------------------------------------------------------------
A1. Login
- Go to Login page
- Enter resident credentials
- You will land on the Resident Dashboard (card navigation)

A2. Profile (Zone + Address + Map)
- Open “Profile” card
- Update:
  - Name
  - Phone (digits only)
  - Zone (dropdown from database)
  - Address (text)
- Map:
  - Use My Location to pin your current location
  - Address auto-fills based on your map location (saved to DB)
- Save Profile

A3. Notifications
- Open “Notifications” card
- View system/admin notifications:
  - Admin assigned collector + collection date
  - Collector verified collection
  - Admin approved/rejected recycling log (points awarded only after admin approval)
  - Reward redemption approved/rejected (refund on reject)
- Badge on dashboard shows unread count

A4. Submit Recycling Log (with image upload)
- Open “Submit Recycling Log” card
- Fill:
  - Waste type
  - Weight
  - Upload photo proof (image file)
- Submit
- Status starts as: Submitted

A5. Track Recycling Status
- Open “Recycling Status/History” card (if available in your UI)
- View statuses:
  Submitted -> Assigned -> PendingAdmin -> Approved / Rejected

A6. Reward Store / Redeem Points
- Open “Reward Store / Redeem Points” card
- Click “Load Store” to see items
- Redeem rules:
  - If you do NOT have an address saved, the system will ask you to fill your address first
  - Redeem creates status “Processing” and deducts points immediately
  - If Admin rejects redemption: points are refunded automatically
  - If Admin approves redemption: you will receive notification:
    “Item will be delivered to your house within 7 working days”

------------------------------------------------------------
B) COLLECTOR USER MANUAL
------------------------------------------------------------
B1. Login
- Login using collector credentials
- You will land on Collector Dashboard

B2. Profile
- Open “Profile” card
- View:
  - user_id, name, phone
  - assigned zone(s) (added by admin via Manage Zones / assignments)

B3. View Assigned Tasks
- Open “Assigned Tasks” card
- See recycling logs assigned to you by admin (with optional collect_date)

B4. Verify Collection (Proof Photo Required)
- Open “Verify Collection” card
- Choose the assigned log
- Upload proof photo showing the resident handed over recyclable items
- Submit verification
- Log moves to admin review (PendingAdmin)
- Resident receives notification that collector has collected and uploaded proof

B5. Update Collection Status
- Open “Update Status” card
- Select status (e.g., On the way / Collecting / Completed)
- Save
- Admin can view your latest status in Admin -> Collectors list

B6. Optimized Route (If enabled)
- Open “Optimized Route” card
- The system orders assigned stops using resident lat/lng and distance calculation
- Use My Location as start point (if available)

------------------------------------------------------------
C) ADMIN USER MANUAL
------------------------------------------------------------
C1. Login
- Login using admin credentials
- You will land on Admin Dashboard

C2. Manage Zones (Card Navigation)
- Open “Manage Zones”
- Zones are shown as clickable cards
- Click a zone to open Zone Detail page

C3. Zone Detail (Edit + Assign Collector + Schedules)
Inside a zone page:
1) Edit Zone: update name/description
2) Assign Collector to Zone:
   - Choose collector from dropdown
   - Duplicate assignments are blocked (same collector cannot be assigned same zone twice)
3) Pickup Schedule Management:
   - Day dropdown (prevents invalid day typing)
   - Time dropdown (prevents invalid time typing)
   - Add/Delete schedule
4) Delete Zone (at bottom of zone page)

C4. Assign Collector to Recycling Log (+ Collect Date)
- Open “Approvals / Recycling Management” (name may vary by UI)
- For new submissions:
  - Assign a collector to collect the resident’s log
  - Optionally set collect_date
- Resident receives notification with collection date

C5. Review Collector Proof & Approve/Reject Recycling Log
- After collector verifies (uploads proof), log enters PendingAdmin
- Admin sees:
  - resident photo
  - collector proof photo
- Approve:
  - awards points to resident (updates rewards table)
  - sends notification
- Reject:
  - records reject reason (if used)
  - sends notification
  - NO points awarded

C6. Reward Management
- Reward Items:
  - Add / Update reward store items
  - Deactivate item (soft delete)
- Redemptions:
  - View redemptions list
  - Approve -> Claimed + notify “deliver within 7 working days”
  - Reject -> Rejected + refund points + notify resident

C7. Residents List / Collectors List
- Admin Dashboard shows 2 cards with counts:
  - Total Residents
  - Total Collectors
- Click card to view user list loaded from database
- Collector list includes latest collector status (if updated by collector)

C8. Send Notification (Residents Only)
- Open “Send Notification” card
- Send message to:
  - All residents, OR
  - A specific resident by user_id
- Notifications appear in resident notification center (unread badge increases)

C9. System Settings
- Open “System Settings” card
- Manage:
  - reward_rate
  - pickup_reminders_enabled
- Save changes (stored in system_settings table)

============================================================
4) QUICK TEST SCENARIO (END-TO-END)
============================================================
1) Login as Resident (alice@gmail.com)
   - Set Profile zone + address (use map)
   - Submit Recycling Log with photo

2) Login as Admin
   - Assign collector to Zone A if not already
   - Assign collector to the new recycling log (+ collect date)

3) Login as Collector (john.collector@mail.com)
   - Verify the assigned log with proof photo upload

4) Login as Admin
   - Approve the log -> points awarded -> resident notification

5) Login as Resident
   - Check notifications + points
   - Redeem an item (requires address)
   - Admin approves/rejects redemption and resident receives notification

============================================================
5) TROUBLESHOOTING
============================================================
- If images do not appear:
  - Make sure static/uploads exists and app has permission to write.
- If database errors occur:
  - Re-run: python migrate_db.py
  - Or delete smart_waste.db and run migrate again (this resets all data).
- If login fails:
  - Ensure you are using the seeded credentials listed above.

END OF README
