# Discord Music Bot

A simple Discord music bot that plays YouTube/search results in a voice channel. It supports a compact now-playing embed, queue playback, and useful player controls.

## Features

- Play songs from a search query or URL
- Queue multiple songs
- Compact now-playing message
- Buttons for pause/resume, skip, and stop
- Auto-disconnect when inactive

## Commands

Use `!` before every command.

| Command | Description |
| --- | --- |
| `!join` | Join your current voice channel |
| `!play <song name or url>` | Play or queue a song |
| `!queue` | Show the current queue |
| `!skip` | Skip the current song |
| `!stop` | Stop playback and clear the queue |
| `!leave` | Disconnect the bot from voice |

Example:

```text
!play zingaat
!play https://www.youtube.com/watch?v=VIDEO_ID
!queue
```

## Requirements

- Python 3.10 or newer
- FFmpeg installed
- A Discord bot token

## Create a Discord Bot

1. Open the Discord Developer Portal: https://discord.com/developers/applications
2. Click **New Application**.
3. Open **Bot** from the left menu.
4. Click **Add Bot**.
5. Copy the bot token.
6. Enable **Message Content Intent** in the bot settings.
7. Invite the bot to your server with these permissions:
   - View Channels
   - Send Messages
   - Embed Links
   - Connect
   - Speak
   - Use Voice Activity

## Setup

Clone or download this project, then open a terminal in the project folder.

Create a virtual environment:

```powershell
python -m venv .venv
```

Activate it:

```powershell
.\.venv\Scripts\activate
```

Install dependencies:

```powershell
pip install -r requirements.txt
```

Create a `.env` file in the project folder:

```env
DISCORD_TOKEN=your_discord_bot_token_here
```

Do not upload your `.env` file to GitHub.

## Install FFmpeg

### Windows

1. Download FFmpeg from https://www.gyan.dev/ffmpeg/builds/
2. Extract it somewhere on your PC.
3. Add the `bin` folder to your system `PATH`.
4. Restart your terminal.
5. Test it:

```powershell
ffmpeg -version
```

If FFmpeg is not in `PATH`, add this to your `.env` file:

```env
FFMPEG_EXECUTABLE=C:\path\to\ffmpeg.exe
```

### Linux VPS

```bash
sudo apt update
sudo apt install ffmpeg python3 python3-venv python3-pip -y
```

## Run Locally

Use:

```powershell
.\.venv\Scripts\python.exe music-bot.py
```

Or double-click:

```text
run-bot.bat
```

When the bot starts, you should see:

```text
Logged in as YourBotName
```

## Host on a VPS

These steps work on Ubuntu/Debian servers.

Install system packages:

```bash
sudo apt update
sudo apt install git ffmpeg python3 python3-venv python3-pip -y
```

Clone your repository:

```bash
git clone https://github.com/YOUR_USERNAME/YOUR_REPO_NAME.git
cd YOUR_REPO_NAME
```

Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Create `.env`:

```bash
nano .env
```

Add:

```env
DISCORD_TOKEN=your_discord_bot_token_here
```

Run the bot:

```bash
python music-bot.py
```

## Keep the Bot Online with systemd

Create a service file:

```bash
sudo nano /etc/systemd/system/discord-music-bot.service
```

Paste this, then replace `YOUR_USER` and the project path:

```ini
[Unit]
Description=Discord Music Bot
After=network.target

[Service]
WorkingDirectory=/home/YOUR_USER/YOUR_REPO_NAME
ExecStart=/home/YOUR_USER/YOUR_REPO_NAME/.venv/bin/python music-bot.py
Restart=always
RestartSec=5
User=YOUR_USER

[Install]
WantedBy=multi-user.target
```

Start the service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable discord-music-bot
sudo systemctl start discord-music-bot
```

Check logs:

```bash
sudo journalctl -u discord-music-bot -f
```

Restart after updating code:

```bash
git pull
sudo systemctl restart discord-music-bot
```

## Files to Upload to GitHub

Upload:

- `music-bot.py`
- `requirements.txt`
- `run-bot.bat`
- `.gitignore`
- `README.md`

Do not upload:

- `.env`
- `.venv/`
- `__pycache__/`

## Troubleshooting

### `DISCORD_TOKEN is missing`

Create a `.env` file and add:

```env
DISCORD_TOKEN=your_discord_bot_token_here
```

### Bot does not respond to commands

Make sure **Message Content Intent** is enabled in the Discord Developer Portal.

### Bot joins but no music plays

Make sure FFmpeg is installed and working:

```bash
ffmpeg -version
```

### Voice connection fails

Check that the bot has permission to connect and speak in the voice channel.

## Security

Never share your Discord bot token. If you accidentally upload it to GitHub, reset the token immediately in the Discord Developer Portal.
