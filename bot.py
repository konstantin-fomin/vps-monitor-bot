import html
import json
import os
import platform
import re
import time
from datetime import datetime

import docker
import psutil
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)


BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
ALLOWED_CHAT_ID = os.environ.get("ALLOWED_CHAT_ID", "").strip()
DEVICE_NAMES_RAW = os.environ.get("DEVICE_NAMES", "").strip()
CLIENT_ALIASES_RAW = os.environ.get("CLIENT_ALIASES", "").strip()
ONLINE_SECONDS_THRESHOLD = int(os.environ.get("ONLINE_SECONDS_THRESHOLD", "180").strip() or "180")

VPN_CONTAINER_NAME = "amnezia-awg2"
BOT_CONTAINER_NAME = "vps-monitor-bot"
CLIENTS_TABLE_PATH = "/opt/amnezia/awg/clientsTable"


def parse_mapping(raw: str) -> dict[str, str]:
    result = {}

    if not raw:
        return result

    for item in raw.split(";"):
        if "=" not in item:
            continue

        key, value = item.split("=", 1)
        key = key.strip()
        value = value.strip()

        if key and value:
            result[key] = value

    return result


DEVICE_NAMES = parse_mapping(DEVICE_NAMES_RAW)
CLIENT_ALIASES = parse_mapping(CLIENT_ALIASES_RAW)


def html_escape(value: object) -> str:
    return html.escape(str(value), quote=False)


def human_bytes(num: float) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if num < 1024:
            return f"{num:.1f} {unit}"
        num /= 1024
    return f"{num:.1f} PB"


def is_allowed(update: Update) -> bool:
    if not ALLOWED_CHAT_ID:
        return True

    chat_id = update.effective_chat.id if update.effective_chat else None
    return str(chat_id) == ALLOWED_CHAT_ID


def get_docker_client():
    return docker.from_env()


def main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🟢 Health", callback_data="health"),
            InlineKeyboardButton("🔐 VPN", callback_data="vpn"),
        ],
        [
            InlineKeyboardButton("📊 Status", callback_data="status"),
            InlineKeyboardButton("🐳 Containers", callback_data="containers"),
        ],
        [
            InlineKeyboardButton("🔄 Refresh", callback_data="refresh"),
        ],
    ])


def format_percent_bar(percent: float) -> str:
    filled = int(round(percent / 10))
    filled = max(0, min(10, filled))
    empty = 10 - filled
    return "█" * filled + "░" * empty


def parse_handshake_seconds(value: str) -> int | None:
    if not value:
        return None

    text = value.lower().strip()

    if text in {"never", "none", "no data"}:
        return None

    text = text.replace("ago", "").strip()
    total = 0

    patterns = [
        (r"(\d+)\s*d", 86400),
        (r"(\d+)\s*day", 86400),
        (r"(\d+)\s*h", 3600),
        (r"(\d+)\s*hour", 3600),
        (r"(\d+)\s*m", 60),
        (r"(\d+)\s*minute", 60),
        (r"(\d+)\s*s", 1),
        (r"(\d+)\s*second", 1),
    ]

    found = False

    for pattern, multiplier in patterns:
        for match in re.finditer(pattern, text):
            total += int(match.group(1)) * multiplier
            found = True

    if found:
        return total

    if text.isdigit():
        return int(text)

    return None


def is_online_handshake(handshake: str) -> bool:
    seconds = parse_handshake_seconds(handshake)
    return seconds is not None and seconds <= ONLINE_SECONDS_THRESHOLD


def extract_single_ip(allowed_ips: str) -> str:
    if not allowed_ips:
        return "unknown"

    first = allowed_ips.split(",")[0].strip()
    return first.split("/")[0].strip()


def parse_vpn_peers(raw_output: str) -> list[dict[str, str]]:
    peers = []
    current = None

    for line in raw_output.splitlines():
        stripped = line.strip()

        if stripped.startswith("peer: "):
            if current:
                peers.append(current)

            current = {
                "peer": stripped.replace("peer: ", "", 1).strip(),
                "allowed_ips": "",
                "endpoint": "",
                "latest_handshake": "",
                "transfer": "",
            }
            continue

        if current is None:
            continue

        if stripped.startswith("endpoint: "):
            current["endpoint"] = stripped.replace("endpoint: ", "", 1).strip()
        elif stripped.startswith("allowed ips: "):
            current["allowed_ips"] = stripped.replace("allowed ips: ", "", 1).strip()
        elif stripped.startswith("latest handshake: "):
            current["latest_handshake"] = stripped.replace("latest handshake: ", "", 1).strip()
        elif stripped.startswith("transfer: "):
            current["transfer"] = stripped.replace("transfer: ", "", 1).strip()

    if current:
        peers.append(current)

    return peers


def format_transfer(transfer: str) -> str:
    if not transfer:
        return "no data"

    match = re.match(r"(.+?) received,\s*(.+?) sent", transfer)

    if not match:
        return transfer

    received = match.group(1)
    sent = match.group(2)

    return f"↓ {sent}  ↑ {received}"


def get_container(container_name: str):
    client = get_docker_client()
    return client.containers.get(container_name)


def exec_in_container(container_name: str, command: list[str]) -> tuple[int, str]:
    container = get_container(container_name)
    result = container.exec_run(command)
    output = result.output.decode("utf-8", errors="replace").strip()
    return result.exit_code, output


def get_awg_show_output() -> str:
    for command in [["awg", "show"], ["wg", "show"]]:
        code, output = exec_in_container(VPN_CONTAINER_NAME, command)

        if code == 0 and output:
            return output

    return ""


def get_clients_table() -> list[dict]:
    code, output = exec_in_container(VPN_CONTAINER_NAME, ["cat", CLIENTS_TABLE_PATH])

    if code != 0 or not output:
        return []

    try:
        parsed = json.loads(output)
    except json.JSONDecodeError:
        return []

    if isinstance(parsed, list):
        return parsed

    return []


def build_clients_by_key_and_ip() -> tuple[dict[str, dict], dict[str, dict]]:
    by_key = {}
    by_ip = {}

    for item in get_clients_table():
        client_id = item.get("clientId", "")
        user_data = item.get("userData", {}) or {}

        raw_name = user_data.get("clientName", "")
        allowed_ips = user_data.get("allowedIps", "")
        ip = extract_single_ip(allowed_ips) if allowed_ips else ""

        client_info = {
            "client_id": client_id,
            "raw_name": raw_name,
            "ip": ip,
            "creation_date": user_data.get("creationDate", ""),
            "table_received": user_data.get("dataReceived", ""),
            "table_sent": user_data.get("dataSent", ""),
            "table_handshake": user_data.get("latestHandshake", ""),
        }

        if client_id:
            by_key[client_id] = client_info

        if ip:
            by_ip[ip] = client_info

    return by_key, by_ip


def pretty_device_name(ip: str, raw_name: str) -> str:
    if ip in DEVICE_NAMES:
        return DEVICE_NAMES[ip]

    if raw_name in CLIENT_ALIASES:
        return CLIENT_ALIASES[raw_name]

    if raw_name:
        return raw_name

    if ip != "unknown":
        return ip

    return "Unknown device"


def get_vpn_devices() -> list[dict[str, str]]:
    raw_awg = get_awg_show_output()
    peers = parse_vpn_peers(raw_awg)
    clients_by_key, clients_by_ip = build_clients_by_key_and_ip()

    devices = []

    for peer in peers:
        key = peer.get("peer", "")
        ip = extract_single_ip(peer.get("allowed_ips", ""))

        client_info = clients_by_key.get(key) or clients_by_ip.get(ip) or {}
        raw_name = client_info.get("raw_name", "")

        handshake = peer.get("latest_handshake", "") or client_info.get("table_handshake", "") or "never"
        transfer = peer.get("transfer", "")

        devices.append({
            "name": pretty_device_name(ip, raw_name),
            "ip": ip,
            "raw_name": raw_name,
            "handshake": handshake,
            "handshake_seconds": parse_handshake_seconds(handshake),
            "online": is_online_handshake(handshake),
            "transfer": transfer,
            "traffic": format_transfer(transfer),
            "endpoint": peer.get("endpoint", ""),
        })

    devices.sort(key=lambda item: (
        0 if item["online"] else 1,
        item["name"].lower(),
    ))

    return devices


def now_string() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


async def send_or_edit(update: Update, text: str, reply_markup=None) -> None:
    if update.callback_query:
        await update.callback_query.edit_message_text(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup,
            disable_web_page_preview=True,
        )
        return

    await update.message.reply_text(
        text=text,
        parse_mode=ParseMode.HTML,
        reply_markup=reply_markup,
        disable_web_page_preview=True,
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed(update):
        return

    chat_id = update.effective_chat.id if update.effective_chat else "unknown"

    text = (
        "🖥 <b>VPS Monitor</b>\n\n"
        "Бот активен и следит за сервером.\n\n"
        f"👤 <b>Your chat_id:</b> <code>{html_escape(chat_id)}</code>\n\n"
        "Команды:\n"
        "• /health — краткая сводка\n"
        "• /vpn — VPN-устройства\n"
        "• /status — состояние сервера\n"
        "• /containers — Docker-контейнеры\n"
        "• /rawvpn — технический VPN-вывод"
    )

    await send_or_edit(update, text, main_keyboard())


async def health(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed(update):
        return

    cpu = psutil.cpu_percent(interval=1)
    ram = psutil.virtual_memory()
    disk = psutil.disk_usage("/")

    uptime_seconds = int(time.time() - psutil.boot_time())
    uptime_days = uptime_seconds // 86400
    uptime_hours = (uptime_seconds % 86400) // 3600
    uptime_minutes = (uptime_seconds % 3600) // 60

    bot_status = "unknown"
    vpn_status = "unknown"
    docker_error = None

    try:
        client = get_docker_client()
        bot_status = client.containers.get(BOT_CONTAINER_NAME).status
        vpn_status = client.containers.get(VPN_CONTAINER_NAME).status
        devices = get_vpn_devices()
    except Exception as exc:
        docker_error = str(exc)
        devices = []

    total_peers = len(devices)
    online_count = sum(1 for device in devices if device["online"])

    vpn_icon = "🟢" if vpn_status == "running" else "🔴"
    bot_icon = "🟢" if bot_status == "running" else "🔴"

    if total_peers > 0 and online_count == total_peers:
        devices_icon = "🟢"
    elif online_count > 0:
        devices_icon = "🟡"
    else:
        devices_icon = "🔴"

    text = (
        "🟢 <b>Health summary</b>\n\n"
        f"{vpn_icon} <b>VPN:</b> <code>{html_escape(vpn_status)}</code>\n"
        f"{bot_icon} <b>Bot:</b> <code>{html_escape(bot_status)}</code>\n"
        f"{devices_icon} <b>Devices:</b> <code>{online_count}/{total_peers} online</code>\n\n"
        f"🧠 <b>CPU:</b> <code>{cpu}%</code>\n"
        f"💾 <b>RAM:</b> <code>{human_bytes(ram.used)} / {human_bytes(ram.total)} ({ram.percent}%)</code>\n"
        f"🗄 <b>Disk:</b> <code>{human_bytes(disk.used)} / {human_bytes(disk.total)} ({disk.percent}%)</code>\n"
        f"⏱ <b>Uptime:</b> <code>{uptime_days}d {uptime_hours}h {uptime_minutes}m</code>\n\n"
        f"🕒 <b>Updated:</b> <code>{html_escape(now_string())}</code>"
    )

    if docker_error:
        text += f"\n\n⚠️ <b>Docker check error:</b>\n<code>{html_escape(docker_error)}</code>"

    await send_or_edit(update, text, main_keyboard())


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed(update):
        return

    cpu = psutil.cpu_percent(interval=1)
    ram = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    net = psutil.net_io_counters()

    uptime_seconds = int(time.time() - psutil.boot_time())
    uptime_days = uptime_seconds // 86400
    uptime_hours = (uptime_seconds % 86400) // 3600
    uptime_minutes = (uptime_seconds % 3600) // 60

    text = (
        "📊 <b>VPS Status</b>\n\n"
        f"🖥 <b>Host:</b> <code>{html_escape(platform.node())}</code>\n"
        f"🐧 <b>OS:</b> <code>{html_escape(platform.system())} {html_escape(platform.release())}</code>\n"
        f"⏱ <b>Uptime:</b> <code>{uptime_days}d {uptime_hours}h {uptime_minutes}m</code>\n\n"
        f"🧠 <b>CPU:</b> <code>{cpu}%</code>\n"
        f"<code>{format_percent_bar(cpu)}</code>\n\n"
        f"💾 <b>RAM:</b> <code>{human_bytes(ram.used)} / {human_bytes(ram.total)} ({ram.percent}%)</code>\n"
        f"<code>{format_percent_bar(ram.percent)}</code>\n\n"
        f"🗄 <b>Disk:</b> <code>{human_bytes(disk.used)} / {human_bytes(disk.total)} ({disk.percent}%)</code>\n"
        f"<code>{format_percent_bar(disk.percent)}</code>\n\n"
        f"🌐 <b>Network total:</b>\n"
        f"• Sent: <code>{human_bytes(net.bytes_sent)}</code>\n"
        f"• Received: <code>{human_bytes(net.bytes_recv)}</code>\n\n"
        f"🕒 <b>Updated:</b> <code>{html_escape(now_string())}</code>"
    )

    await send_or_edit(update, text, main_keyboard())


async def containers(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed(update):
        return

    try:
        client = get_docker_client()
        containers_list = client.containers.list()
    except Exception as exc:
        await send_or_edit(update, f"❌ <b>Docker API error</b>\n\n<code>{html_escape(exc)}</code>", main_keyboard())
        return

    if not containers_list:
        await send_or_edit(update, "🐳 <b>Docker containers</b>\n\nКонтейнеры не найдены.", main_keyboard())
        return

    lines = ["🐳 <b>Docker containers</b>\n"]

    for container in containers_list:
        name = container.name
        status = container.status
        image = container.image.tags[0] if container.image.tags else container.image.short_id
        icon = "🟢" if status == "running" else "🔴"

        lines.append(
            f"{icon} <b>{html_escape(name)}</b>\n"
            f"   Status: <code>{html_escape(status)}</code>\n"
            f"   Image: <code>{html_escape(image)}</code>"
        )

    text = "\n\n".join(lines)
    text += f"\n\n🕒 <b>Updated:</b> <code>{html_escape(now_string())}</code>"

    if len(text) > 3900:
        text = text[:3900] + "\n\n...output truncated"

    await send_or_edit(update, text, main_keyboard())


async def vpn(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed(update):
        return

    try:
        devices = get_vpn_devices()
    except Exception as exc:
        await send_or_edit(update, f"❌ <b>VPN error</b>\n\n<code>{html_escape(exc)}</code>", main_keyboard())
        return

    if not devices:
        await send_or_edit(update, "🔐 <b>VPN devices</b>\n\nУстройства не найдены.", main_keyboard())
        return

    online_count = sum(1 for device in devices if device["online"])

    blocks = []

    for device in devices:
        status_icon = "🟢" if device["online"] else "⚪"
        status_text = "online" if device["online"] else "offline / idle"

        blocks.append(
            f"{status_icon} <b>{html_escape(device['name'])}</b>\n"
            f"   IP: <code>{html_escape(device['ip'])}</code>\n"
            f"   Status: <code>{status_text}</code>\n"
            f"   Last seen: <code>{html_escape(device['handshake'])}</code>\n"
            f"   Traffic: <code>{html_escape(device['traffic'])}</code>"
        )

    text = (
        "🔐 <b>VPN devices</b>\n\n"
        f"🟢 Online: <code>{online_count}</code>\n"
        f"👥 Total peers: <code>{len(devices)}</code>\n"
        f"⏳ Online threshold: <code>{ONLINE_SECONDS_THRESHOLD}s</code>\n\n"
        + "\n\n".join(blocks)
        + f"\n\n🕒 <b>Updated:</b> <code>{html_escape(now_string())}</code>"
    )

    if len(text) > 3900:
        text = text[:3900] + "\n\n...output truncated"

    await send_or_edit(update, text, main_keyboard())


async def rawvpn(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed(update):
        return

    try:
        output = get_awg_show_output()
    except Exception as exc:
        await send_or_edit(update, f"❌ <b>Raw VPN error</b>\n\n<code>{html_escape(exc)}</code>", main_keyboard())
        return

    if not output:
        output = "No VPN output."

    safe_output = html_escape(output)

    if len(safe_output) > 3500:
        safe_output = safe_output[:3500] + "\n\n...output truncated"

    text = f"🧪 <b>Raw VPN output</b>\n\n<pre>{safe_output}</pre>"

    await send_or_edit(update, text, main_keyboard())


async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed(update):
        return

    query = update.callback_query
    await query.answer()

    if query.data == "health":
        await health(update, context)
    elif query.data == "status":
        await status(update, context)
    elif query.data == "containers":
        await containers(update, context)
    elif query.data == "vpn":
        await vpn(update, context)
    elif query.data == "refresh":
        await health(update, context)
    else:
        await start(update, context)


def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN environment variable is not set")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("health", health))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("containers", containers))
    app.add_handler(CommandHandler("vpn", vpn))
    app.add_handler(CommandHandler("rawvpn", rawvpn))
    app.add_handler(CallbackQueryHandler(on_button))

    app.run_polling()


if __name__ == "__main__":
    main()
