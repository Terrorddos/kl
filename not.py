import logging
import sqlite3
import time
import re
from datetime import datetime, timedelta
from telegram import (
    Update,
    ChatPermissions,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    BotCommand,
    BotCommandScopeChat
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
    CallbackQueryHandler
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot_logs.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Database setup
def init_db():
    conn = sqlite3.connect('bot_db.sqlite')
    cursor = conn.cursor()
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS approved_channels (
        channel_id TEXT PRIMARY KEY,
        channel_title TEXT,
        added_by INTEGER,
        date_added TEXT,
        has_admin_permissions BOOLEAN DEFAULT FALSE,
        valid_until TEXT
    )''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS pending_groups (
        group_id TEXT PRIMARY KEY,
        group_title TEXT,
        invited_by INTEGER,
        date_added TEXT,
        admin_request_sent BOOLEAN DEFAULT FALSE
    )''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS channel_admins (
        channel_id TEXT,
        user_id INTEGER,
        PRIMARY KEY (channel_id, user_id)
    )''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS muted_users (
        user_id INTEGER,
        chat_id TEXT,
        muted_until TEXT,
        muted_by INTEGER,
        mute_message_id INTEGER,
        mute_reason TEXT,
        PRIMARY KEY (user_id, chat_id)
    )''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS command_usage (
        user_id INTEGER,
        timestamp TEXT,
        count INTEGER DEFAULT 1,
        PRIMARY KEY (user_id)
    )''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS filtered_words (
        channel_id TEXT,
        word TEXT,
        added_by INTEGER,
        date_added TEXT,
        PRIMARY KEY (channel_id, word)
    )''')
    
    conn.commit()
    conn.close()

def execute_db(query, params=(), fetch=False):
    conn = sqlite3.connect('bot_db.sqlite')
    cursor = conn.cursor()
    cursor.execute(query, params)
    if fetch:
        result = cursor.fetchall()
    else:
        result = None
    conn.commit()
    conn.close()
    return result

# Configuration
DEVELOPER_ID = 1760943918
DEVELOPER_USERNAME = "@ABHISHEEK163"
MUTE_DURATION_MINUTES = 3
BOT_USERNAME = "LinkRemoverT_bot"  # Without @

# Spam protection configuration
SPAM_PROTECTION = {
    'MAX_COMMANDS': 5,
    'COOLDOWN': 60,
    'ADMIN_LIMIT': 10
}

BOT_ART = """
✨━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━✨
       𝓜𝓸𝓭𝓮𝓻𝓪𝓽𝓲𝓸𝓷 𝓑𝓸𝓽
✨━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━✨
"""

# Emoji constants
EMOJI_WARNING = "⚠️"
EMOJI_SUCCESS = "✅"
EMOJI_ERROR = "❌"
EMOJI_INFO = "ℹ️"
EMOJI_LOCK = "🔒"
EMOJI_MUTE = "🔇"
EMOJI_UNMUTE = "🔊"
EMOJI_STATS = "📊"
EMOJI_LIST = "📋"
EMOJI_ADD = "➕"
EMOJI_REMOVE = "➖"
EMOJI_GROUP = "👥"
EMOJI_CHANNEL = "📢"
EMOJI_DEVELOPER = "👨‍💻"
EMOJI_ADMIN = "👮"
EMOJI_HELP = "🛠"
EMOJI_ALIVE = "🤖"
EMOJI_BROADCAST = "📢"
EMOJI_CLOCK = "⏱"
EMOJI_WAITING = "⏳"
EMOJI_CALENDAR = "📅"
EMOJI_LINK = "🔗"

# Link detection pattern
LINK_PATTERN = re.compile(
    r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+',
    re.IGNORECASE
)

# Helper functions
async def has_admin_permissions(chat_id: str, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Check if bot has necessary admin permissions in the chat"""
    try:
        bot_member = await context.bot.get_chat_member(chat_id, context.bot.id)
        return (bot_member.status == 'administrator' and
                bot_member.can_delete_messages and
                bot_member.can_restrict_members)
    except Exception as e:
        logger.error(f"Error checking admin permissions: {e}")
        return False

async def is_admin_or_owner(chat_id: str, user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    try:
        chat_member = await context.bot.get_chat_member(chat_id, user_id)
        return chat_member.status in ['administrator', 'creator']
    except Exception as e:
        logger.error(f"Error checking admin status: {e}")
        return False

async def is_developer(user_id: int) -> bool:
    return user_id == DEVELOPER_ID

async def check_spam(user_id: int, is_admin: bool = False) -> bool:
    """Check if user is spamming commands"""
    now = datetime.now().isoformat()
    max_commands = SPAM_PROTECTION['ADMIN_LIMIT'] if is_admin else SPAM_PROTECTION['MAX_COMMANDS']
    
    usage = execute_db(
        "SELECT timestamp, count FROM command_usage WHERE user_id = ?",
        (user_id,),
        fetch=True
    )
    
    if usage:
        last_time = datetime.fromisoformat(usage[0][0])
        count = usage[0][1]
        time_diff = (datetime.now() - last_time).total_seconds()
        
        if time_diff < SPAM_PROTECTION['COOLDOWN'] and count >= max_commands:
            return True
        
        if time_diff < SPAM_PROTECTION['COOLDOWN']:
            execute_db(
                "UPDATE command_usage SET count = count + 1 WHERE user_id = ?",
                (user_id,)
            )
        else:
            execute_db(
                "UPDATE command_usage SET count = 1, timestamp = ? WHERE user_id = ?",
                (now, user_id)
            )
    else:
        execute_db(
            "INSERT INTO command_usage (user_id, timestamp) VALUES (?, ?)",
            (user_id, now)
        )
    return False

def spam_protected(handler):
    """Decorator for spam protection"""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.effective_user:
            return
        
        user_id = update.effective_user.id
        is_admin = await is_admin_or_owner(str(update.effective_chat.id), user_id, context) if update.effective_chat else False
        
        if await check_spam(user_id, is_admin):
            warning_msg = f"{EMOJI_WARNING} You're sending commands too fast. Please wait a minute before trying again."
            if update.message:
                await update.message.reply_text(warning_msg)
            return
        
        return await handler(update, context)
    return wrapper

async def mute_user(chat_id: str, user_id: int, context: ContextTypes.DEFAULT_TYPE, reason: str) -> bool:
    """Mute a user in the specified chat"""
    try:
        mute_until = datetime.now() + timedelta(minutes=MUTE_DURATION_MINUTES)
        await context.bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=ChatPermissions(
                can_send_messages=False,
                can_send_media_messages=False,
                can_send_other_messages=False,
                can_add_web_page_previews=False
            ),
            until_date=mute_until
        )
        
        execute_db(
            "INSERT OR REPLACE INTO muted_users VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, chat_id, mute_until.isoformat(), context.bot.id, None, reason)
        )
        return True
    except Exception as e:
        logger.error(f"Error muting user {user_id} in {chat_id}: {e}")
        return False

async def handle_unauthorized_content(update: Update, context: ContextTypes.DEFAULT_TYPE, violation_type: str, details: str = ""):
    """Handle unauthorized content (links or filtered words)"""
    chat_id = str(update.effective_chat.id)
    user_id = update.effective_user.id
    user_name = update.effective_user.username or update.effective_user.full_name
    
    try:
        await update.message.delete()
    except Exception as e:
        logger.warning(f"Could not delete message: {e}")
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"{EMOJI_WARNING} Could not delete message from @{user_name}",
            reply_to_message_id=update.message.message_id
        )
        return
    
    mute_reason = f"Posted {violation_type}"
    if details:
        mute_reason += f": {details}"
    
    if await mute_user(chat_id, user_id, context, mute_reason):
        mute_msg = f"""
🚨 <b>User Muted</b> 🚨

👤 <b>User:</b> @{user_name}
⏳ <b>Duration:</b> {MUTE_DURATION_MINUTES} minutes
📝 <b>Reason:</b> {mute_reason}

<i>Admins can unmute using the button below</i>
"""
        keyboard = [[InlineKeyboardButton(f"{EMOJI_UNMUTE} Unmute User", callback_data=f"unmute:{chat_id}:{user_id}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        mute_message = await context.bot.send_message(
            chat_id=chat_id,
            text=mute_msg,
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
        
        execute_db(
            "UPDATE muted_users SET mute_message_id = ? WHERE user_id = ? AND chat_id = ?",
            (mute_message.message_id, user_id, chat_id)
        )

async def check_channel_permissions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Check if channel is approved, has admin permissions, and is within validation period"""
    if not update.effective_chat:
        return False
    
    chat_id = str(update.effective_chat.id)
    is_approved = execute_db(
        "SELECT has_admin_permissions, valid_until FROM approved_channels WHERE channel_id = ?",
        (chat_id,),
        fetch=True
    )
    
    if not is_approved:
        if update.message:
            await update.message.reply_text(
                f"{EMOJI_ERROR} This channel is not approved. Contact the developer {DEVELOPER_USERNAME}"
            )
        return False
    
    # Check if validation period has expired
    if is_approved[0][1]:  # valid_until exists
        valid_until = datetime.fromisoformat(is_approved[0][1])
        if datetime.now() > valid_until:
            if update.message:
                await update.message.reply_text(
                    f"{EMOJI_WARNING} This channel's approval has expired!\n\n"
                    f"Please contact the developer {DEVELOPER_USERNAME} for renewal."
                )
            execute_db(
                "DELETE FROM approved_channels WHERE channel_id = ?",
                (chat_id,)
            )
            return False
    
    if is_approved[0][0]:  # has_admin_permissions is TRUE
        return True
    
    has_perms = await has_admin_permissions(chat_id, context)
    if has_perms:
        execute_db(
            "UPDATE approved_channels SET has_admin_permissions = TRUE WHERE channel_id = ?",
            (chat_id,)
        )
        return True
    else:
        if update.message:
            await update.message.reply_text(
                f"{EMOJI_WARNING} I don't have admin permissions in this chat!\n\n"
                "Please make me admin with:\n"
                "- Delete messages permission\n"
                "- Restrict users permission"
            )
        return False

# Command handlers
@spam_protected
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_chat:
        return
    
    if update.effective_chat.type == "private":
        welcome_msg = f"""
{BOT_ART}
👋 Hello! I'm an advanced moderation bot.

{EMOJI_ADMIN} <b>Features:</b>
• Auto-link removal
• Custom word filtering
• Admin controls
• Mute management

{EMOJI_GROUP} <b>To add me to your group/channel:</b>
1. Add me as admin with delete messages permission
2. Use /id in your group to get its ID
3. Ask admin to approve it with /add group_id
4. Use /addwords to set filtered words

{EMOJI_HELP} Use /help for available commands
"""
        keyboard = [
            [
                InlineKeyboardButton(f"{EMOJI_ADD} Add to Group", url=f"https://t.me/{BOT_USERNAME}?startgroup=true"),
                InlineKeyboardButton(f"{EMOJI_CHANNEL} Add to Channel", url=f"https://t.me/{BOT_USERNAME}?startchannel=true")
            ],
            [
                InlineKeyboardButton(f"{EMOJI_HELP} Help", callback_data="help_command"),
                InlineKeyboardButton(f"{EMOJI_DEVELOPER} Contact Developer", url=f"https://t.me/{DEVELOPER_USERNAME[1:]}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(welcome_msg, parse_mode='HTML', reply_markup=reply_markup)
    else:
        chat = update.effective_chat
        inviter = update.effective_user
        
        if chat.type in ["group", "supergroup"]:
            existing = execute_db(
                "SELECT 1 FROM pending_groups WHERE group_id = ?",
                (chat.id,),
                fetch=True
            )
            
            if existing:
                await update.message.reply_text(f"{EMOJI_INFO} This group is already pending approval.")
                return
            
            admin_request_msg = f"""
{BOT_ART}
👋 Thanks for adding me to <b>{chat.title}</b>!

{EMOJI_WARNING} <b>Before I can work, you need to:</b>
1. Make me admin
2. Grant these permissions:
   - {EMOJI_LOCK} Delete messages
   - {EMOJI_MUTE} Ban users

{EMOJI_INFO} Then ask the developer to approve this group with:
<code>/add {chat.id} days</code> (e.g., /add {chat.id} 7 for 7 days)

{EMOJI_DEVELOPER} Contact: {DEVELOPER_USERNAME}
"""
            sent_message = await update.message.reply_text(admin_request_msg, parse_mode='HTML')
            
            try:
                invite_link = await chat.export_invite_link() if chat.invite_link else "No invite link"
                await context.bot.send_message(
                    chat_id=DEVELOPER_ID,
                    text=f"""📥 <b>New group added for approval</b>

{EMOJI_GROUP} <b>Group:</b> {chat.title}
{EMOJI_INFO} <b>ID:</b> <code>{chat.id}</code>
{EMOJI_ADD} <b>Added by:</b> @{inviter.username if inviter.username else inviter.full_name}
{EMOJI_LINK} <b>Invite:</b> {invite_link}

{EMOJI_WARNING} Use <code>/add {chat.id} days</code> to approve""",
                    parse_mode='HTML',
                    disable_web_page_preview=True
                )
            except Exception as e:
                logger.error(f"Error notifying developer: {e}")
                
            execute_db(
                "INSERT INTO pending_groups VALUES (?, ?, ?, datetime('now'), ?)",
                (chat.id, chat.title, inviter.id, sent_message.message_id)
            )

@spam_protected
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user:
        return
    
    if await is_developer(update.effective_user.id):
        help_text = f"""
{BOT_ART}
{EMOJI_HELP} <b>Developer Commands</b>:

• /add <channel_id> <days> - Approve new channel/group for X days
• /channel - List approved channels
• /pending - List pending groups
• /stats - Show bot statistics
• /broadcast - Send message to all channels

{EMOJI_ADMIN} <b>Admin Commands</b>:
• /addwords - Add filtered words
• /removeword - Remove filtered word
• /listwords - List filtered words
• /help - Show this help message
• /alive - Check bot status
"""
    else:
        help_text = f"""
{BOT_ART}
{EMOJI_HELP} <b>Admin Commands</b>:

• /addwords word1 word2 - Add filtered words
• /removeword word - Remove filtered word
• /listwords - List filtered words
• /help - Show this help message
• /alive - Check bot status
• /stats - Show channel statistics
"""
    await update.message.reply_text(help_text, parse_mode='HTML')

async def help_button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the help button callback"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "help_command":
        if await is_developer(query.from_user.id):
            help_text = f"""
{BOT_ART}
{EMOJI_HELP} <b>Developer Commands</b>:

• /add <channel_id> <days> - Approve new channel/group for X days
• /channel - List approved channels
• /pending - List pending groups
• /stats - Show bot statistics
• /broadcast - Send message to all channels

{EMOJI_ADMIN} <b>Admin Commands</b>:
• /addwords - Add filtered words
• /removeword - Remove filtered word
• /listwords - List filtered words
• /help - Show this help message
• /alive - Check bot status
"""
        else:
            help_text = f"""
{BOT_ART}
{EMOJI_HELP} <b>Admin Commands</b>:

• /addwords word1 word2 - Add filtered words
• /removeword word - Remove filtered word
• /listwords - List filtered words
• /help - Show this help message
• /alive - Check bot status
• /stats - Show channel statistics
"""
        
        await query.edit_message_text(
            text=help_text,
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"{EMOJI_ADD} Back to Start", callback_data="back_to_start")]
            ])
        )
    elif query.data == "back_to_start":
        welcome_msg = f"""
{BOT_ART}
👋 Hello! I'm an advanced moderation bot.

{EMOJI_ADMIN} <b>Features:</b>
• Auto-link removal
• Custom word filtering
• Admin controls
• Mute management

{EMOJI_GROUP} <b>To add me to your group/channel:</b>
1. Add me as admin with delete messages permission
2. Use /id in your group to get its ID
3. Ask admin to approve it with /add group_id
4. Use /addwords to set filtered words

{EMOJI_HELP} Use /help for available commands
"""
        keyboard = [
            [
                InlineKeyboardButton(f"{EMOJI_ADD} Add to Group", url=f"https://t.me/{BOT_USERNAME}?startgroup=true"),
                InlineKeyboardButton(f"{EMOJI_CHANNEL} Add to Channel", url=f"https://t.me/{BOT_USERNAME}?startchannel=true")
            ],
            [
                InlineKeyboardButton(f"{EMOJI_HELP} Help", callback_data="help_command"),
                InlineKeyboardButton(f"{EMOJI_DEVELOPER} Contact Developer", url=f"https://t.me/{DEVELOPER_USERNAME[1:]}")
            ]
        ]
        await query.edit_message_text(
            text=welcome_msg,
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

@spam_protected
async def add_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Developer command to approve a new channel/group with validation period"""
    if not await is_developer(update.effective_user.id):
        await update.message.reply_text(f"{EMOJI_ERROR} Only the developer can use this command!")
        return
    
    if len(context.args) < 2:
        await update.message.reply_text(f"{EMOJI_INFO} Usage: /add <channel_id> <days>")
        await update.message.reply_text("Example: /add -100123456789 7 (approves for 7 days)")
        return
    
    channel_id = context.args[0]
    
    try:
        days = int(context.args[1])
        if days <= 0:
            await update.message.reply_text(f"{EMOJI_ERROR} Days must be a positive number")
            return
    except ValueError:
        await update.message.reply_text(f"{EMOJI_ERROR} Days must be a number")
        return
    
    try:
        chat = await context.bot.get_chat(channel_id)
    except Exception as e:
        await update.message.reply_text(f"{EMOJI_ERROR} Error: {e}")
        return
    
    existing = execute_db(
        "SELECT 1 FROM approved_channels WHERE channel_id = ?",
        (channel_id,),
        fetch=True
    )
    
    if existing:
        await update.message.reply_text(f"{EMOJI_INFO} {chat.title} ({channel_id}) is already approved.")
        return
    
    has_perms = await has_admin_permissions(channel_id, context)
    if not has_perms:
        await update.message.reply_text(
            f"""{EMOJI_WARNING} I don't have admin permissions in {chat.title}!
Please make me admin with:
- Delete messages permission
- Restrict users permission"""
        )
        return
    
    valid_until = (datetime.now() + timedelta(days=days)).isoformat()
        
    execute_db(
        "INSERT INTO approved_channels VALUES (?, ?, ?, datetime('now'), ?, ?)",
        (channel_id, chat.title, update.effective_user.id, 1, valid_until)
    )
    
    execute_db(
        "DELETE FROM pending_groups WHERE group_id = ?",
        (channel_id,)
    )
    
    try:
        await context.bot.send_message(
            chat_id=channel_id,
            text=f"""{BOT_ART}
{EMOJI_SUCCESS} <b>This {chat.type} has been approved for {days} days!</b>

You can now use these commands:
• /addwords - Add filtered words
• /listwords - View filtered words
• /stats - View channel stats

{EMOJI_ADMIN} Only admins can use these commands""",
            parse_mode='HTML'
        )
    except Exception as e:
        logger.warning(f"Could not notify channel {channel_id}: {e}")
    
    await update.message.reply_text(
        f"{EMOJI_SUCCESS} {chat.title} ({channel_id}) has been approved for {days} days!",
        parse_mode='HTML'
    )

@spam_protected
async def list_channels(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List all approved channels (developer only)"""
    if not await is_developer(update.effective_user.id):
        await update.message.reply_text(f"{EMOJI_ERROR} Only the developer can use this command!")
        return
    
    channels = execute_db(
        "SELECT channel_id, channel_title, date_added, has_admin_permissions, valid_until FROM approved_channels ORDER BY date_added",
        fetch=True
    )
    
    if not channels:
        await update.message.reply_text(f"{EMOJI_INFO} No channels approved yet.")
        return
    
    message = f"{EMOJI_LIST} <b>Approved channels/groups:</b>\n\n"
    for channel in channels:
        status = f"{EMOJI_SUCCESS} (Active)" if channel[3] else f"{EMOJI_WARNING} (Missing permissions)"
        valid_until = datetime.fromisoformat(channel[4]).strftime("%Y-%m-%d") if channel[4] else "Permanent"
        days_left = (datetime.fromisoformat(channel[4]) - datetime.now()).days if channel[4] else "∞"
        message += f"""• <b>{channel[1]}</b> (<code>{channel[0]}</code>)
Added: {channel[2]}
Status: {status}
Valid until: {valid_until} ({days_left} days left)

"""
    
    await update.message.reply_text(message, parse_mode='HTML')

@spam_protected
async def pending_groups(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List pending groups waiting for approval (developer only)"""
    if not await is_developer(update.effective_user.id):
        await update.message.reply_text(f"{EMOJI_ERROR} Only the developer can use this command!")
        return
    
    groups = execute_db(
        "SELECT group_id, group_title, invited_by, date_added FROM pending_groups ORDER BY date_added",
        fetch=True
    )
    
    if not groups:
        await update.message.reply_text(f"{EMOJI_INFO} No pending groups.")
        return
    
    message = f"{EMOJI_LIST} <b>Pending groups:</b>\n\n"
    for group in groups:
        message += f"""• <b>{group[1]}</b> (<code>{group[0]}</code>)
Added by: {group[2]} on {group[3]}

"""
    
    await update.message.reply_text(message, parse_mode='HTML')

@spam_protected
async def alive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Check bot status"""
    uptime = timedelta(seconds=time.time() - context.bot_data.get('start_time', time.time()))
    
    if await is_developer(update.effective_user.id):
        channel_count = len(execute_db("SELECT channel_id FROM approved_channels WHERE has_admin_permissions = TRUE", fetch=True))
        pending_count = len(execute_db("SELECT group_id FROM pending_groups", fetch=True))
        muted_users = len(execute_db("SELECT user_id FROM muted_users", fetch=True))
        
        # Count expiring soon channels (within 3 days)
        expiring_soon = len(execute_db(
            "SELECT channel_id FROM approved_channels WHERE valid_until < datetime('now', '+3 days') AND valid_until > datetime('now')",
            fetch=True
        ))
        
        status_msg = f"""
{BOT_ART}
{EMOJI_ALIVE} <b>Bot Status</b>

{EMOJI_SUCCESS} <b>Online</b>
{EMOJI_CLOCK} <b>Uptime:</b> {str(uptime).split('.')[0]}
{EMOJI_STATS} <b>Active Channels:</b> {channel_count}
{EMOJI_WAITING} <b>Pending Groups:</b> {pending_count}
{EMOJI_MUTE} <b>Muted Users:</b> {muted_users}
{EMOJI_WARNING} <b>Channels expiring soon:</b> {expiring_soon}

{EMOJI_DEVELOPER} <b>Developer:</b> {DEVELOPER_USERNAME}
{EMOJI_CALENDAR} <b>Last Check:</b> {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
"""
    else:
        status_msg = f"""
{BOT_ART}
{EMOJI_ALIVE} <b>Bot Status</b>

{EMOJI_SUCCESS} <b>Online</b>
{EMOJI_CLOCK} <b>Uptime:</b> {str(uptime).split('.')[0]}

{EMOJI_CALENDAR} <b>Last Check:</b> {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
"""
    await update.message.reply_text(status_msg, parse_mode='HTML')

@spam_protected
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show statistics for the current channel"""
    if not update.effective_chat or not update.effective_user:
        return
    
    chat_id = str(update.effective_chat.id)
    user_id = update.effective_user.id
    
    if not await is_admin_or_owner(chat_id, user_id, context) and not await is_developer(user_id):
        await update.message.reply_text(f"{EMOJI_ERROR} Only admins can view statistics!")
        return
    
    channel_info = execute_db(
        "SELECT date_added, valid_until FROM approved_channels WHERE channel_id = ?",
        (chat_id,),
        fetch=True
    )
    
    muted_users = len(execute_db(
        "SELECT user_id FROM muted_users WHERE chat_id = ?",
        (chat_id,),
        fetch=True
    ))
    
    filtered_words = len(execute_db(
        "SELECT word FROM filtered_words WHERE channel_id = ?",
        (chat_id,),
        fetch=True
    ))
    
    if channel_info:
        added_date = datetime.fromisoformat(channel_info[0][0]).strftime("%Y-%m-%d")
        valid_until = datetime.fromisoformat(channel_info[0][1]).strftime("%Y-%m-%d") if channel_info[0][1] else "Permanent"
        days_left = (datetime.fromisoformat(channel_info[0][1]) - datetime.now()).days if channel_info[0][1] else "∞"
    else:
        added_date = "Not approved"
        valid_until = "N/A"
        days_left = "0"
    
    stats_msg = f"""
{BOT_ART}
{EMOJI_STATS} <b>Channel Statistics</b>

{EMOJI_CALENDAR} <b>Added on:</b> {added_date}
{EMOJI_CLOCK} <b>Valid until:</b> {valid_until} ({days_left} days left)
{EMOJI_MUTE} <b>Currently Muted Users:</b> {muted_users}
{EMOJI_LIST} <b>Filtered Words:</b> {filtered_words}

{EMOJI_CALENDAR} <b>Last Updated:</b> {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
"""
    await update.message.reply_text(stats_msg, parse_mode='HTML')

@spam_protected
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Developer command to broadcast message to all channels"""
    if not await is_developer(update.effective_user.id):
        await update.message.reply_text(f"{EMOJI_ERROR} Only the developer can use this command!")
        return
    
    if not context.args:
        await update.message.reply_text(f"{EMOJI_INFO} Usage: /broadcast <message>")
        return
    
    message = ' '.join(context.args)
    channels = execute_db(
        "SELECT channel_id, channel_title FROM approved_channels WHERE has_admin_permissions = TRUE AND (valid_until > datetime('now') OR valid_until IS NULL)",
        fetch=True
    )
    
    if not channels:
        await update.message.reply_text(f"{EMOJI_INFO} No channels with proper permissions available for broadcasting.")
        return
    
    success = 0
    failed = 0
    results = []
    
    broadcast_msg = f"""
{BOT_ART}
{EMOJI_BROADCAST} <b>Broadcast Message</b> {EMOJI_BROADCAST}

{message}

<i>Sent by developer</i>
"""
    
    for channel in channels:
        try:
            await context.bot.send_message(
                chat_id=channel[0],
                text=broadcast_msg,
                parse_mode='HTML'
            )
            success += 1
            results.append(f"{EMOJI_SUCCESS} {channel[1]}")
        except Exception as e:
            logger.error(f"Failed to send to {channel[0]}: {e}")
            failed += 1
            results.append(f"{EMOJI_ERROR} {channel[1]} (failed)")
    
    report_msg = f"""
{EMOJI_BROADCAST} <b>Broadcast Report</b>

{EMOJI_SUCCESS} <b>Successful:</b> {success}
{EMOJI_ERROR} <b>Failed:</b> {failed}

<b>Details:</b>
""" + "\n".join(results)
    
    await update.message.reply_text(report_msg, parse_mode='HTML')

@spam_protected
async def add_words(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Add words to filter list"""
    if not update.effective_chat or not update.effective_user:
        return
    
    chat_id = str(update.effective_chat.id)
    user_id = update.effective_user.id
    
    if not await is_admin_or_owner(chat_id, user_id, context):
        await update.message.reply_text(f"{EMOJI_ERROR} Only channel admins can use this command.")
        return
    
    if not await check_channel_permissions(update, context):
        return
    
    if not context.args:
        await update.message.reply_text(f"{EMOJI_INFO} Usage: /addwords word1 word2 word3")
        return
    
    added_words = []
    skipped_words = []
    
    for word in context.args:
        word_lower = word.lower()
        try:
            execute_db(
                "INSERT OR IGNORE INTO filtered_words VALUES (?, ?, ?, datetime('now'))",
                (chat_id, word_lower, user_id)
            )
            if execute_db("SELECT changes()", fetch=True)[0][0] > 0:
                added_words.append(word_lower)
            else:
                skipped_words.append(word_lower)
        except Exception as e:
            logger.error(f"Error adding word {word}: {e}")
            skipped_words.append(word_lower)
    
    response_msg = ""
    if added_words:
        response_msg += f"{EMOJI_SUCCESS} Added words: {', '.join(added_words)}\n"
    if skipped_words:
        response_msg += f"{EMOJI_INFO} Already exists: {', '.join(skipped_words)}"
    
    await update.message.reply_text(response_msg)

@spam_protected
async def remove_word(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Remove word from filter list"""
    if not update.effective_chat or not update.effective_user:
        return
    
    chat_id = str(update.effective_chat.id)
    user_id = update.effective_user.id
    
    if not await is_admin_or_owner(chat_id, user_id, context):
        await update.message.reply_text(f"{EMOJI_ERROR} Only channel admins can use this command.")
        return
    
    if not await check_channel_permissions(update, context):
        return
    
    if not context.args:
        await update.message.reply_text(f"{EMOJI_INFO} Usage: /removeword word")
        return
    
    word = context.args[0].lower()
    changes = execute_db(
        "DELETE FROM filtered_words WHERE channel_id = ? AND word = ?",
        (chat_id, word)
    )
    
    if changes:
        await update.message.reply_text(f"{EMOJI_SUCCESS} Removed word: {word}")
    else:
        await update.message.reply_text(f"{EMOJI_INFO} Word not found: {word}")

@spam_protected
async def list_words(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List all filtered words for the current channel"""
    if not update.effective_chat or not update.effective_user:
        return
    
    chat_id = str(update.effective_chat.id)
    user_id = update.effective_user.id
    
    if not await is_admin_or_owner(chat_id, user_id, context):
        await update.message.reply_text(f"{EMOJI_ERROR} Only channel admins can use this command.")
        return
    
    words = execute_db(
        "SELECT word, added_by, date_added FROM filtered_words WHERE channel_id = ? ORDER BY date_added",
        (chat_id,),
        fetch=True
    )
    
    if not words:
        await update.message.reply_text(f"{EMOJI_INFO} No filtered words for this channel.")
        return
    
    message = f"{EMOJI_LIST} <b>Filtered words:</b>\n\n"
    for word in words:
        message += f"""• <b>{word[0]}</b>
Added by: {word[1]} on {word[2]}

"""
    
    await update.message.reply_text(message, parse_mode='HTML')

@spam_protected
async def id_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Get the chat ID"""
    if not update.effective_chat:
        return
    
    chat = update.effective_chat
    await update.message.reply_text(f"{EMOJI_INFO} Chat ID: <code>{chat.id}</code>", parse_mode='HTML')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle all messages and check for violations"""
    if not update.message or not update.effective_chat or not update.effective_user:
        return
    
    chat_id = str(update.effective_chat.id)
    user_id = update.effective_user.id
    message_text = update.message.text or update.message.caption or ""
    
    # Skip if message is from bot or admin
    if user_id == context.bot.id or await is_admin_or_owner(chat_id, user_id, context):
        return
    
    # Check if channel is approved and has permissions
    if not await check_channel_permissions(update, context):
        return
    
    # Check for links
    if LINK_PATTERN.search(message_text):
        await handle_unauthorized_content(update, context, "unauthorized link")
        return
    
    # Check for filtered words
    filtered_words = execute_db(
        "SELECT word FROM filtered_words WHERE channel_id = ?",
        (chat_id,),
        fetch=True
    )
    
    if filtered_words:
        message_lower = message_text.lower()
        for word in filtered_words:
            if word[0] in message_lower:
                await handle_unauthorized_content(update, context, "filtered word", word[0])
                return

async def unmute_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle unmute button callback"""
    query = update.callback_query
    await query.answer()
    
    if not query.data.startswith("unmute:"):
        return
    
    _, chat_id, user_id = query.data.split(":")
    user_id = int(user_id)
    
    # Check if the user clicking is an admin
    if not await is_admin_or_owner(chat_id, query.from_user.id, context):
        await query.edit_message_text(f"{EMOJI_ERROR} Only admins can unmute users!")
        return
    
    try:
        # Restore full permissions
        await context.bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=ChatPermissions(
                can_send_messages=True,
                can_send_media_messages=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True
            )
        )
        
        # Remove from database
        execute_db(
            "DELETE FROM muted_users WHERE user_id = ? AND chat_id = ?",
            (user_id, chat_id)
        )
        
        # Update the message
        await query.edit_message_text(
            text=f"{EMOJI_SUCCESS} User has been unmuted by @{query.from_user.username or query.from_user.full_name}",
            reply_markup=None
        )
    except Exception as e:
        logger.error(f"Error unmuting user {user_id} in {chat_id}: {e}")
        await query.edit_message_text(
            text=f"{EMOJI_ERROR} Failed to unmute user!",
            reply_markup=None
        )

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log errors and send them to developer"""
    logger.error(msg="Exception while handling an update:", exc_info=context.error)
    
    if update and isinstance(update, Update) and update.effective_message:
        text = "An error occurred while processing your request. The developer has been notified."
        await update.effective_message.reply_text(text)
    
    # Notify developer
    error_msg = f"""
{EMOJI_ERROR} <b>Error occurred</b> {EMOJI_ERROR}

<b>Update:</b> <code>{update}</code>

<b>Error:</b>
<code>{context.error}</code>
"""
    try:
        await context.bot.send_message(
            chat_id=DEVELOPER_ID,
            text=error_msg,
            parse_mode='HTML'
        )
    except Exception as e:
        logger.error(f"Could not send error message to developer: {e}")

async def post_init(application):
    """Post initialization tasks"""
    # Set bot commands
    await application.bot.set_my_commands([
        BotCommand("start", "Start the bot"),
        BotCommand("help", "Show help message"),
        BotCommand("addwords", "Add words to filter list"),
        BotCommand("removeword", "Remove word from filter list"),
        BotCommand("listwords", "List filtered words"),
        BotCommand("stats", "Show channel statistics"),
        BotCommand("alive", "Check bot status"),
        BotCommand("id", "Get chat ID")
    ])
    
    # Set developer commands
    await application.bot.set_my_commands([
        BotCommand("add", "Approve new channel"),
        BotCommand("channel", "List approved channels"),
        BotCommand("pending", "List pending groups"),
        BotCommand("broadcast", "Broadcast message to all channels")
    ], scope=BotCommandScopeChat(DEVELOPER_ID))
    
    # Store bot start time
    application.bot_data['start_time'] = time.time()

def main() -> None:
    """Start the bot"""
    init_db()
    
    application = ApplicationBuilder().token("7949936346:AAEJ8SA4vPH4Gveq2NBSDXY2vbC1jZ9WFdw").post_init(post_init).build()
    
    # Command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("add", add_channel))
    application.add_handler(CommandHandler("channel", list_channels))
    application.add_handler(CommandHandler("pending", pending_groups))
    application.add_handler(CommandHandler("alive", alive))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("broadcast", broadcast))
    application.add_handler(CommandHandler("addwords", add_words))
    application.add_handler(CommandHandler("removeword", remove_word))
    application.add_handler(CommandHandler("listwords", list_words))
    application.add_handler(CommandHandler("id", id_command))
    
    # Callback handlers
    application.add_handler(CallbackQueryHandler(help_button_callback, pattern="^(help_command|back_to_start)$"))
    application.add_handler(CallbackQueryHandler(unmute_callback, pattern="^unmute:"))
    
    # Message handler
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Error handler
    application.add_error_handler(error_handler)
    
    # Start the bot
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()