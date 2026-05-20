# VPS Monitor Bot

A lightweight Telegram bot for monitoring a personal VPS and AmneziaWG VPN server.

## Features

- VPS health summary
- CPU, RAM, disk and network usage
- Docker container status
- AmneziaWG VPN device list
- Online/offline detection by latest handshake
- Telegram inline buttons
- Docker Compose deployment

## Commands

- /start - show main menu
- /health - short health summary
- /status - detailed VPS status
- /vpn - VPN devices
- /containers - Docker containers
- /rawvpn - raw VPN diagnostic output

## Stack

- Python
- python-telegram-bot
- Docker SDK for Python
- psutil
- Docker Compose

## Project structure

bot.py
Dockerfile
docker-compose.yml
requirements.txt
.env.example
.gitignore
README.md

## Deployment

1. Clone the repository.
2. Copy .env.example to .env.
3. Fill BOT_TOKEN and ALLOWED_CHAT_ID.
4. Run: docker compose up -d --build
5. Check logs: docker logs --tail=50 vps-monitor-bot

## Environment variables

BOT_TOKEN - Telegram bot token from BotFather.
ALLOWED_CHAT_ID - Telegram chat ID allowed to use the bot.
DEVICE_NAMES - Optional mapping from VPN IP to readable device name.
CLIENT_ALIASES - Optional mapping from Amnezia client name to readable device name.
ONLINE_SECONDS_THRESHOLD - Online detection threshold in seconds.

## Security notes

Do not commit .env.
Do not expose the bot token.
Use ALLOWED_CHAT_ID to restrict access.
This bot uses Docker socket access to inspect containers and read VPN diagnostics.
