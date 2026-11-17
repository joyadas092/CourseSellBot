# 🎓 Premium Course & Subscription Selling Telegram Bot

A production-ready Telegram Bot built with **Aiogram 3.x** and **MongoDB (Motor)** for selling digital courses, premium channels, and VIP subscription groups. 

---

## 🌟 Key Features

### 1. 🛍️ Dynamic `/start` Storefront & Button Mapping (As shown in Screenshot 1)
- Admin can map any button text on `/start` to point to specific course content (e.g. `💥 Jio hotstar ad-free 4kplan ₹29`, `📺 Prime Video`, `🟢 Spotify ₹45`).
- Supports **Full-Row (1-col)** and **Half-Row (2-col)** layouts configured per folder.
- Dynamic store headers, review channel links, and privacy policy pages.

### 2. 📖 Rich Course Details & Multi-tier Pricing (As shown in Screenshot 2)
- Photo / Banner support.
- Detailed content description rendered in clean quote blocks (`<blockquote>...</blockquote>`).
- Demo channel/video preview button.
- Multi-tier duration buttons: e.g. **7 Days - ₹49**, **1 Month - ₹99**, **3 Months - ₹199**, **Lifetime - ₹499**.
- Dedicated support handle button.

### 3. 🎁 2-Minute Free Demo Plan (Lifetime Limit 1x per User)
- **Claim Free Demo**: Users can tap `🎁 Claim Free Demo (2 Mins)` on any course folder.
- **Clear User Notice**: When tapped, the bot informs the user that this trial is active for exactly 2 minutes and they will be kicked automatically upon completion.
- **Strict 1-Time Lifetime Lock**: Each Telegram user ID can consume the free demo trial **only once in their lifetime**.
- **Alert on Re-trial**: If a user attempts to claim the demo again, the bot immediately triggers an alert popup: *"⚠️ You have already consumed your demo plan! Lifetime limit is 1 trial per user."*
- **Exact 2-Minute Countdown & Auto-Kick**: The 2-minute timer begins when the user joins the private channel/group. When the 2 minutes end, the bot automatically removes (bans then unbans) the user and dispatches a completion DM with a button to view regular paid plans.
- **Admin Reset Control**: Admins can reset a user's demo access anytime via `/resetdemo <user_id>`.

### 4. 💳 Multi-Gateway Payment System (Reused from AutoForwarderBot)
- **📱 Razorpay UPI QR (Scan & Pay)**: Generates instant dynamic UPI QR codes compatible with PhonePe, Google Pay, Paytm, and BHIM. Automatically verifies transactions when users tap `✅ I Have Paid`.
- **💳 Razorpay Hosted Link**: Supports Credit/Debit Cards, NetBanking, and Wallets.
- **⭐ Telegram Stars**: Native in-app payment with instant automated checkout approval.
- **🪙 Crypto**: Direct USDT (BEP-20) and TON wallet payments.
- **⚡ Direct Manual UPI**: Allows users to submit UTR or payment screenshots with 1-click Admin Approve/Reject buttons.
- **⏳ 15-Minute Auto-Deletion**: Automatically removes payment QR codes from the chat after 15 minutes or immediately after successful verification for security and cleanliness.

### 4. 🔒 High-Security Single-Use Invite Links & Intruder Protection
- Generates private single-use invite links with `creates_join_request=True`.
- Strictly binds the invite link to the buyer's Telegram user ID (`user_id`).
- When the legitimate buyer taps the link:
  1. The bot automatically approves their join request.
  2. The bot immediately revokes the invite link so it can never be used again.
  3. Records join timestamp and sends a welcoming confirmation.
- **If an intruder attempts to join using the buyer's link**:
  1. The bot automatically **REJECTS** the join request.
  2. The bot immediately dispatches a **Security Alert** to the buyer with the intruder's ID, name, and username!

### 5. ⏳ Expiry Monitor, Auto-Kick & Reminder Notifications
- Periodic background worker monitors active subscriptions:
  - **72 Hours Before**: Sends advance reminder with a 1-tap renewal button.
  - **24 Hours Before**: Sends urgent reminder.
  - **2 Hours Before**: Sends final countdown reminder.
  - **Upon Expiry**: Automatically kicks the user from the private group/channel (`ban_chat_member` then `unban_chat_member`), marks subscription expired, and sends an alert with a renewal link.

### 6. 👑 Full Admin Dashboard (`/admin`)
- **Add New Course/Folder**: Step-by-step wizard to set Title, Button Text, Layout Width, Description, Demo URL, Target Channel ID, Banner Image, and Pricing Plans.
- **Edit Existing Courses**: Change Title, Button Text, Description, Banner, Channel ID, Demo URL, Width, or Active status anytime.
- **Pricing Plans Manager**: Add, edit, or remove duration tiers for each course.
- **Subscribers Manager**: View active subscribers, remaining days, and join status.
- **Transactions Log**: View latest transactions with status and gateway.
- **📡 Real-Time Progress Broadcast**:
  - Segment target audience: **All Users**, **Active Paid Subscribers**, **Expired Subscribers**, or **Demo Trial Users**.
  - Interactive live UI updating every 2 seconds with Unicode progress bar (`[████████░░░░] 65.4%`), delivery speed (`msg/s`), elapsed time, and estimated time remaining (ETA).
  - Pin message toggle (`🔔 YES / 🔕 NO`) to automatically pin the broadcast in recipient chats.
  - Emergency **`[ ⏹️ Abort / Stop Broadcast ]`** button to safely interrupt broadcast midway.
  - Automatic Telegram FloodWait handling and rate-limiting pacing (~28 msg/sec).
- **Store Settings**: Customize `/start` welcome header and support username.

---

## 🚀 Quick Setup & Running

### 1. Requirements
Ensure Python 3.10+ is installed:
```powershell
pip install -r requirements.txt
```

### 2. Configure Environment (`.env`)
The `.env` file is pre-configured with MongoDB and payment gateway credentials from AutoForwarderBot. You only need to insert your **`BOT_TOKEN`**:

```env
BOT_TOKEN=your_bot_token_from_botfather
ADMIN_IDS=5886397642,6417700277,8725349820
SUPPORT_USERNAME=woxic_01
MONGODB_URI=mongodb+srv://linksdunia:Shashwat123@cluster0.8faxppl.mongodb.net/?appName=Cluster0
MONGODB_DB_NAME=CourseSellingBot
RAZORPAY_KEY_ID=rzp_live_Sja1tUvNe3nVEV
RAZORPAY_KEY_SECRET=RolxSo3jFzTJ1Fk1BW2Ue6TB
```

### 3. Setup Private Telegram Group/Channel
1. Create your private Telegram Channel or Group where your premium courses/content are stored.
2. Add your Bot to the channel/group as an **Administrator** with the following permissions:
   - ✅ **Invite Users via Link**
   - ✅ **Manage Voice Chats / Restrict Members / Ban Users**
3. Copy the numeric Chat ID (e.g. `-1002345678901`) and enter it in the Admin Panel (`/admin`) when adding or editing a course folder.

### 4. Start the Bot
```powershell
python main.py
```
