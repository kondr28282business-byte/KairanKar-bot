import logging
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path

from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# -------------------- Configuration --------------------

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

TOKEN = os.getenv("BOT_TOKEN", "").strip()
GROUP_ID = int(os.getenv("GROUP_ID", "0"))
OWNER_ID = 7987275172
OWNER_USERNAME = "durov2026_off"

DB_PATH = BASE_DIR / "kairankar.db"
APPLICATION = 0

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("kairankar")


# -------------------- Database --------------------

db = sqlite3.connect(DB_PATH)
db.row_factory = sqlite3.Row


def init_db():
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            username TEXT
        );

        CREATE TABLE IF NOT EXISTS applications (
            user_id INTEGER PRIMARY KEY,
            role TEXT NOT NULL,
            codeword TEXT NOT NULL,
            submitted_username TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS roles (
            role TEXT PRIMARY KEY COLLATE NOCASE,
            user_id INTEGER,
            username TEXT
        );

        CREATE TABLE IF NOT EXISTS admins (
            user_id INTEGER PRIMARY KEY,
            username TEXT
        );
        """
    )
    db.execute(
        "INSERT OR IGNORE INTO admins (user_id, username) VALUES (?, ?)",
        (OWNER_ID, OWNER_USERNAME),
    )
    db.commit()


def save_user(user):
    db.execute(
        """
        INSERT INTO users (user_id, name, username)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            name = excluded.name,
            username = excluded.username
        """,
        (user.id, user.full_name, user.username),
    )
    db.commit()


def is_admin(user_id: int) -> bool:
    if user_id == OWNER_ID:
        return True
    return db.execute(
        "SELECT 1 FROM admins WHERE user_id = ?", (user_id,)
    ).fetchone() is not None


async def in_group(update: Update) -> bool:
    return bool(update.effective_chat and update.effective_chat.id == GROUP_ID)


async def require_group_admin(update: Update) -> bool:
    if not await in_group(update):
        await update.effective_message.reply_text(
            "Эта команда работает только в группе KairanKar."
        )
        return False
    if not is_admin(update.effective_user.id):
        await update.effective_message.reply_text(
            "У тебя нет прав для управления ролями."
        )
        return False
    return True


async def resolve_target(update: Update, args):
    """Resolve a target from a replied-to message, numeric ID, or cached @username."""
    message = update.effective_message

    if message.reply_to_message and message.reply_to_message.from_user:
        return message.reply_to_message.from_user, list(args)

    if not args:
        return None, []

    first = args[0]
    if first.isdigit():
        row = db.execute(
            "SELECT user_id, name, username FROM users WHERE user_id = ?",
            (int(first),),
        ).fetchone()
        if row:
            return row, list(args[1:])
        return None, []

    if first.startswith("@"):
        row = db.execute(
            "SELECT user_id, name, username FROM users "
            "WHERE lower(username) = lower(?)",
            (first[1:],),
        ).fetchone()
        if row:
            return row, list(args[1:])

    return None, []


def target_id(target):
    return target.id if hasattr(target, "id") else target["user_id"]


def target_name(target):
    return target.full_name if hasattr(target, "full_name") else target["name"]


def target_username(target):
    return target.username if hasattr(target, "username") else target["username"]


# -------------------- One-message application --------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "Привет! Это бот флуда KairanKar.\n\n"
        "Чтобы получить приглашение в чат, заполни анкету:\n\n"
        "1. Роль\n"
        "2. Кодовое слово\n"
        "3. Юзернейм\n\n"
        "Отправь все три пункта одним сообщением, каждый с новой строки.\n\n"
        "Пример:\n"
        "Сяо\n"
        "КодовоеСлово\n"
        "@username\n\n"
        "Для отмены отправь /cancel."
    )
    return APPLICATION


async def receive_application(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    user = update.effective_user
    lines = [line.strip() for line in update.effective_message.text.splitlines()]

    if len(lines) != 3 or not all(lines):
        await update.effective_message.reply_text(
            "Не получилось разобрать анкету.\n\n"
            "Отправь ровно три непустые строки:\n"
            "1. Роль\n"
            "2. Кодовое слово\n"
            "3. Юзернейм"
        )
        return APPLICATION

    role, codeword, submitted_username = lines

    if len(role) > 70 or len(codeword) > 100 or len(submitted_username) > 50:
        await update.effective_message.reply_text(
            "Один из пунктов слишком длинный. Попробуй заполнить анкету ещё раз."
        )
        return APPLICATION

    if not submitted_username.startswith("@") or len(submitted_username) < 2:
        await update.effective_message.reply_text(
            "Юзернейм нужно указать в формате @username."
        )
        return APPLICATION

    save_user(user)
    db.execute(
        """
        INSERT INTO applications
            (user_id, role, codeword, submitted_username, created_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            role = excluded.role,
            codeword = excluded.codeword,
            submitted_username = excluded.submitted_username,
            created_at = excluded.created_at
        """,
        (
            user.id,
            role,
            codeword,
            submitted_username,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    db.commit()

    await update.effective_message.reply_text(
        "Анкета получена! Создаю персональную ссылку-приглашение..."
    )

    try:
        invite = await context.bot.create_chat_invite_link(
            chat_id=GROUP_ID,
            member_limit=1,
            expire_date=datetime.now(timezone.utc) + timedelta(hours=24),
            name=f"KairanKar user {user.id}",
        )
        await update.effective_message.reply_text(
            "Анкета принята!\n\n"
            f"Роль: {escape(role)}\n"
            f"Юзернейм: {escape(submitted_username)}\n\n"
            "Твоя персональная ссылка для входа в KairanKar:\n"
            f"{invite.invite_link}\n\n"
            "Ссылка действует 24 часа и рассчитана на одно вступление."
        )
    except Exception:
        logger.exception("Не удалось создать ссылку-приглашение")
        await update.effective_message.reply_text(
            "Анкета сохранена, но создать ссылку не удалось. "
            "Проверь права бота в группе и обратись к администрации."
        )

    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "Заполнение анкеты отменено. Чтобы начать заново, отправь /start."
    )
    return ConversationHandler.END


# -------------------- Role management --------------------

async def freeroles(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await in_group(update):
        return

    rows = db.execute(
        "SELECT role FROM roles WHERE user_id IS NULL ORDER BY role COLLATE NOCASE"
    ).fetchall()

    if not rows:
        await update.effective_message.reply_text("Свободных ролей пока нет.")
        return

    text = "Свободные роли KairanKar:\n\n" + "\n".join(
        f"{i}. {escape(row['role'])}" for i, row in enumerate(rows, 1)
    )
    await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)


async def roles(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await in_group(update):
        return

    rows = db.execute(
        """
        SELECT role, user_id, username
        FROM roles
        WHERE user_id IS NOT NULL
        ORDER BY role COLLATE NOCASE
        """
    ).fetchall()

    if not rows:
        await update.effective_message.reply_text("Занятых ролей пока нет.")
        return

    lines = ["Занятые роли KairanKar:\n"]
    for row in rows:
        if row["username"]:
            person = f"@{escape(row['username'])}"
        else:
            person = f'<a href="tg://user?id={row["user_id"]}">Пользователь</a>'
        lines.append(f"• {person} [{escape(row['role'])}]")

    await update.effective_message.reply_text(
        "\n".join(lines), parse_mode=ParseMode.HTML
    )


async def addrole(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_group_admin(update):
        return

    role = " ".join(context.args).strip()
    if not role:
        await update.effective_message.reply_text(
            "Использование: /addrole Имя персонажа"
        )
        return

    try:
        db.execute(
            "INSERT INTO roles (role, user_id, username) VALUES (?, NULL, NULL)",
            (role,),
        )
        db.commit()
        await update.effective_message.reply_text(
            f"Роль [{escape(role)}] добавлена в список свободных.",
            parse_mode=ParseMode.HTML,
        )
    except sqlite3.IntegrityError:
        await update.effective_message.reply_text("Такая роль уже есть в базе.")


async def freerole(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_group_admin(update):
        return

    target, remaining = await resolve_target(update, context.args)
    if target is None or not remaining:
        await update.effective_message.reply_text(
            "Выдача роли:\n"
            "• Ответь на сообщение пользователя: /freerole Имя персонажа\n"
            "• Или укажи известного боту пользователя: "
            "/freerole @username Имя персонажа\n\n"
            "Пользователь должен ранее написать боту или отметиться в группе."
        )
        return

    role = " ".join(remaining).strip()
    role_row = db.execute(
        "SELECT user_id FROM roles WHERE role = ? COLLATE NOCASE", (role,)
    ).fetchone()

    if role_row is None:
        await update.effective_message.reply_text(
            "Такой роли нет в базе. Сначала добавь её через /addrole."
        )
        return

    if role_row["user_id"] is not None:
        await update.effective_message.reply_text("Эта роль уже занята.")
        return

    uid = target_id(target)
    current = db.execute(
        "SELECT role FROM roles WHERE user_id = ?", (uid,)
    ).fetchone()
    if current:
        await update.effective_message.reply_text(
            f"У пользователя уже занята роль [{escape(current['role'])}].",
            parse_mode=ParseMode.HTML,
        )
        return

    username = target_username(target)
    db.execute(
        """
        UPDATE roles SET user_id = ?, username = ?
        WHERE role = ? COLLATE NOCASE
        """,
        (uid, username, role),
    )
    db.commit()

    await update.effective_message.reply_text(
        f'Роль [{escape(role)}] выдана '
        f'<a href="tg://user?id={uid}">{escape(target_name(target))}</a>.',
        parse_mode=ParseMode.HTML,
    )

    try:
        await context.bot.send_message(
            uid, f"Тебе выдали роль [{role}] в KairanKar!"
        )
    except Exception:
        pass


async def unfreerole(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_group_admin(update):
        return

    role = " ".join(context.args).strip()
    if not role:
        await update.effective_message.reply_text(
            "Использование: /unfreerole Имя персонажа"
        )
        return

    result = db.execute(
        """
        UPDATE roles SET user_id = NULL, username = NULL
        WHERE role = ? COLLATE NOCASE
        """,
        (role,),
    )
    db.commit()

    if result.rowcount:
        await update.effective_message.reply_text(
            f"Роль [{escape(role)}] теперь свободна.",
            parse_mode=ParseMode.HTML,
        )
    else:
        await update.effective_message.reply_text("Такая роль не найдена.")


# -------------------- Admin management --------------------

async def adminadd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await in_group(update):
        return
    if update.effective_user.id != OWNER_ID:
        await update.effective_message.reply_text(
            "Только владелец бота может назначать администраторов."
        )
        return

    target, _ = await resolve_target(update, context.args)
    if target is None:
        await update.effective_message.reply_text(
            "Ответь на сообщение пользователя командой /adminadd "
            "или укажи его ID/известный боту @username."
        )
        return

    uid = target_id(target)
    if uid == OWNER_ID:
        await update.effective_message.reply_text(
            "Этот пользователь уже владелец."
        )
        return

    db.execute(
        "INSERT OR REPLACE INTO admins (user_id, username) VALUES (?, ?)",
        (uid, target_username(target)),
    )
    db.commit()
    await update.effective_message.reply_text(
        f"Права администратора ролей выданы пользователю "
        f"{escape(target_name(target))}.",
        parse_mode=ParseMode.HTML,
    )


async def adminremove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await in_group(update):
        return
    if update.effective_user.id != OWNER_ID:
        await update.effective_message.reply_text(
            "Только владелец бота может снимать права администраторов."
        )
        return

    target, _ = await resolve_target(update, context.args)
    if target is None:
        await update.effective_message.reply_text(
            "Ответь на сообщение пользователя командой /adminremove "
            "или укажи его ID/известный боту @username."
        )
        return

    uid = target_id(target)
    if uid == OWNER_ID:
        await update.effective_message.reply_text(
            "Нельзя снять права владельца."
        )
        return

    db.execute("DELETE FROM admins WHERE user_id = ?", (uid,))
    db.commit()
    await update.effective_message.reply_text("Права администратора сняты.")


async def adminlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await in_group(update):
        return

    rows = db.execute(
        "SELECT user_id, username FROM admins ORDER BY user_id"
    ).fetchall()

    lines = [
        "Администрация KairanKar:\n",
        f'OWNER: <a href="tg://user?id={OWNER_ID}">@{escape(OWNER_USERNAME)}</a>',
    ]
    for row in rows:
        if row["user_id"] == OWNER_ID:
            continue
        if row["username"]:
            label = "@" + escape(row["username"])
        else:
            label = f'<a href="tg://user?id={row["user_id"]}">Администратор</a>'
        lines.append(f"ADMIN: {label}")

    await update.effective_message.reply_text(
        "\n".join(lines), parse_mode=ParseMode.HTML
    )


# -------------------- Member registration / welcome --------------------

async def here(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await in_group(update):
        return
    save_user(update.effective_user)
    await update.effective_message.reply_text(
        "Ты добавлен в список участников KairanKar."
    )


async def welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await in_group(update):
        return

    for member in update.effective_message.new_chat_members:
        if member.is_bot:
            continue

        save_user(member)
        rows = db.execute(
            "SELECT user_id, name FROM users ORDER BY name COLLATE NOCASE"
        ).fetchall()

        mentions = [
            f'<a href="tg://user?id={row["user_id"]}">{escape(row["name"])}</a>'
            for row in rows
        ]

        intro = (
            "Добро пожаловать в KairanKar, "
            f'<a href="tg://user?id={member.id}">{escape(member.first_name)}</a>!\n\n'
            "Встречаем нового участника!\n\n"
            "Участники, которых знает бот:\n"
        )
        # Telegram limits a message to 4096 characters. Send mentions in chunks.
        current = intro
        for mention in mentions:
            addition = (", " if current != intro else "") + mention
            if len(current) + len(addition) > 3800:
                await context.bot.send_message(
                    chat_id=GROUP_ID,
                    text=current,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
                current = mention
            else:
                current += addition

        if current:
            await context.bot.send_message(
                chat_id=GROUP_ID,
                text=current,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )


# -------------------- Help --------------------

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "KAIRANKAR BOT\n\n"
        "Анкета:\n"
        "/start — заполнить анкету\n"
        "/cancel — отменить анкету\n\n"
        "Роли:\n"
        "/freeroles — свободные роли\n"
        "/roles — занятые роли\n"
        "/freerole — выдать роль (админ)\n"
        "/addrole — добавить роль (админ)\n"
        "/unfreerole — освободить роль (админ)\n\n"
        "Администрация:\n"
        "/adminadd — назначить администратора (только OWNER)\n"
        "/adminremove — снять администратора (только OWNER)\n"
        "/adminlist — список администрации\n"
        "/here — добавить себя в список упоминаний"
    )


# -------------------- Startup --------------------

def main():
    if not TOKEN:
        raise SystemExit(
            "Не указан BOT_TOKEN. Скопируй .env.example в .env и вставь токен."
        )
    if GROUP_ID == 0:
        raise SystemExit("Не указан GROUP_ID в файле .env.")

    init_db()

    app: Application = ApplicationBuilder().token(TOKEN).build()

    application_conversation = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            APPLICATION: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    receive_application,
                )
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )

    app.add_handler(application_conversation)
    app.add_handler(CommandHandler("freeroles", freeroles))
    app.add_handler(CommandHandler("roles", roles))
    app.add_handler(CommandHandler("addrole", addrole))
    app.add_handler(CommandHandler("freerole", freerole))
    app.add_handler(CommandHandler("unfreerole", unfreerole))
    app.add_handler(CommandHandler("adminadd", adminadd))
    app.add_handler(CommandHandler("adminremove", adminremove))
    app.add_handler(CommandHandler("adminlist", adminlist))
    app.add_handler(CommandHandler("here", here))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(
        MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome)
    )

    logger.info("KairanKar Bot started. OWNER_ID=%s", OWNER_ID)
    app.run_polling()


if __name__ == "__main__":
    main()
