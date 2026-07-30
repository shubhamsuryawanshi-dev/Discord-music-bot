import asyncio
import importlib.util
import os
import time
from dataclasses import dataclass, field
from io import BytesIO

import discord
import requests
import yt_dlp
from colorthief import ColorThief
from discord.ext import commands
from dotenv import load_dotenv


load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
LOCAL_FFMPEG = (
    r"C:\ffmpeg-2025-09-04-git-2611874a50-full_build"
    r"\ffmpeg-2025-09-04-git-2611874a50-full_build\bin\ffmpeg.exe"
)
FFMPEG_DEFAULT = LOCAL_FFMPEG if os.path.exists(LOCAL_FFMPEG) else "ffmpeg"
FFMPEG_EXECUTABLE = os.getenv("FFMPEG_EXECUTABLE", FFMPEG_DEFAULT)

if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing. Add it to your .env file.")


def require_voice_dependencies() -> None:
    missing = [
        package_name
        for package_name in ("nacl", "davey")
        if importlib.util.find_spec(package_name) is None
    ]
    if missing:
        raise RuntimeError(
            "Missing Discord voice dependencies: "
            + ", ".join(missing)
            + ". Run: .venv\\Scripts\\python.exe -m pip install -r requirements.txt"
        )


require_voice_dependencies()

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)

ytdl_opts = {
    "format": "bestaudio[acodec=opus][ext=webm]/bestaudio[ext=m4a]/bestaudio/best",
    "format_sort": ["acodec:opus", "abr"],
    "noplaylist": True,
    "quiet": True,
    "default_search": "ytsearch",
    "source_address": "0.0.0.0",
}
ytdl = yt_dlp.YoutubeDL(ytdl_opts)

ffmpeg_before_options = "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
ffmpeg_options = "-vn"


@dataclass
class Song:
    title: str
    url: str
    stream_url: str
    thumbnail: str | None
    duration: int | None
    related: list[str] = field(default_factory=list)
    uploader: str = "Unknown"
    requester: str = "Unknown"
    start_time: float = field(default_factory=time.time)


@dataclass
class GuildPlayer:
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    connect_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    next_song: asyncio.Event = field(default_factory=asyncio.Event)
    now: Song | None = None
    message: discord.Message | None = None
    text_channel: discord.abc.Messageable | None = None
    task: asyncio.Task | None = None
    stopped: bool = False


players: dict[int, GuildPlayer] = {}


def get_player(guild_id: int) -> GuildPlayer:
    if guild_id not in players:
        players[guild_id] = GuildPlayer()
    return players[guild_id]


def queue_snapshot(player: GuildPlayer) -> list[Song]:
    return list(player.queue._queue)


def format_duration(seconds: int | None) -> str:
    if seconds is None:
        return "Live"

    minutes, second = divmod(int(seconds), 60)
    hour, minute = divmod(minutes, 60)
    if hour:
        return f"{hour}:{minute:02d}:{second:02d}"
    return f"{minute}:{second:02d}"


def progress_bar(song: Song, size: int = 18) -> str:
    if not song.duration:
        return "Live stream"

    elapsed = max(0, min(int(time.time() - song.start_time), int(song.duration)))
    return f"{format_duration(elapsed)} / {format_duration(song.duration)}"


def compact_title(title: str, limit: int = 52) -> str:
    if len(title) <= limit:
        return title
    return title[: limit - 3].rstrip() + "..."


def queue_text(player: GuildPlayer, limit: int = 5) -> str:
    queued_songs = queue_snapshot(player)
    if not queued_songs:
        return "No songs queued. Use `!play <song name>`."

    lines = []
    for index, song in enumerate(queued_songs[:limit], start=1):
        lines.append(f"`{index}.` [{compact_title(song.title)}]({song.url}) · `{format_duration(song.duration)}`")

    remaining = len(queued_songs) - limit
    if remaining > 0:
        lines.append(f"...and {remaining} more")

    return "\n".join(lines)


def next_song_text(player: GuildPlayer) -> str:
    queued_songs = queue_snapshot(player)
    if not queued_songs:
        return "`Empty`"

    song = queued_songs[0]
    return f"[{compact_title(song.title, 38)}]({song.url})"


async def send_interaction_message(
    interaction: discord.Interaction,
    content: str | None = None,
    *,
    embed: discord.Embed | None = None,
    ephemeral: bool = True,
) -> None:
    if interaction.response.is_done():
        await interaction.followup.send(content=content, embed=embed, ephemeral=ephemeral)
    else:
        await interaction.response.send_message(content=content, embed=embed, ephemeral=ephemeral)


async def connect_voice_channel(ctx: commands.Context) -> discord.VoiceClient | None:
    if not ctx.guild:
        await ctx.send("⚠️ This command only works in a server.")
        return None

    if not ctx.author.voice or not ctx.author.voice.channel:
        await ctx.send("🎧 Join a voice channel first.")
        return None

    player = get_player(ctx.guild.id)
    channel = ctx.author.voice.channel

    async with player.connect_lock:
        voice_client = ctx.guild.voice_client

        if voice_client and voice_client.is_connected():
            if voice_client.channel != channel:
                await voice_client.move_to(channel)
            return voice_client

        if voice_client:
            await voice_client.disconnect(force=True)

        try:
            return await channel.connect(timeout=20, reconnect=False, self_deaf=True)
        except asyncio.TimeoutError:
            await ctx.send("⏳ I timed out while connecting to voice. Check my permissions and try again.")
        except discord.ConnectionClosed as exc:
            if exc.code == 4017:
                await ctx.send(
                    "🔐 Discord rejected the voice connection because this voice channel requires "
                    "DAVE/E2EE support. Install the updated voice dependencies with "
                    "`.venv\\Scripts\\python.exe -m pip install -r requirements.txt`, "
                    "then run the bot from `.venv\\Scripts\\python.exe`."
                )
            else:
                await ctx.send(f"⚠️ Voice websocket closed while connecting. Discord close code: {exc.code}.")
        except discord.ClientException as exc:
            await ctx.send(f"⚠️ Voice connection failed: {exc}")
        except discord.DiscordException:
            await ctx.send("⚠️ I could not connect to voice. Check my permissions and try again.")

    return None


def get_dominant_color(url: str | None) -> discord.Color:
    if not url:
        return discord.Color.blurple()

    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        color_thief = ColorThief(BytesIO(response.content))
        r, g, b = color_thief.get_color(quality=1)
        return discord.Color.from_rgb(r, g, b)
    except Exception:
        return discord.Color.blurple()


async def extract_info(query: str) -> Song:
    data = await asyncio.to_thread(ytdl.extract_info, query, download=False)

    if "entries" in data:
        entries = [entry for entry in data["entries"] if entry]
        if not entries:
            raise commands.CommandError("No results found.")
        data = entries[0]

    related = []
    for video in data.get("related_videos") or []:
        video_id = video.get("id")
        if video_id:
            related.append(f"https://www.youtube.com/watch?v={video_id}")

    return Song(
        title=data.get("title") or "Unknown title",
        url=data.get("webpage_url") or query,
        stream_url=data.get("url"),
        thumbnail=data.get("thumbnail"),
        duration=data.get("duration"),
        related=related,
        uploader=data.get("uploader") or "Unknown",
    )


def create_music_embed(song: Song, player: GuildPlayer) -> discord.Embed:
    embed = discord.Embed(
        title=compact_title(song.title, 58),
        url=song.url,
        description=(
            f"**Artist:** {compact_title(song.uploader, 42)}\n"
            f"**Time:** `{progress_bar(song)}`\n"
            f"**Next:** {next_song_text(player)}"
        ),
        color=get_dominant_color(song.thumbnail),
    )
    embed.set_author(name="Now Playing")
    if song.thumbnail:
        embed.set_thumbnail(url=song.thumbnail)

    return embed


def create_queue_embed(player: GuildPlayer) -> discord.Embed:
    embed = discord.Embed(title="🎶 Music Queue", color=discord.Color.green())
    if player.now:
        embed.add_field(
            name="▶️ Now Playing",
            value=f"[{player.now.title}]({player.now.url}) `[{format_duration(player.now.duration)}]`",
            inline=False,
        )

    embed.add_field(name="📜 Up Next", value=queue_text(player, limit=10), inline=False)
    return embed


class MusicControls(discord.ui.View):
    def __init__(self, guild_id: int, *, paused: bool = False):
        super().__init__(timeout=None)
        self.guild_id = guild_id
        if paused:
            for item in self.children:
                if getattr(item, "custom_id", None) == "music:pause_resume":
                    item.emoji = "▶️"

    async def on_error(
        self,
        interaction: discord.Interaction,
        error: Exception,
        item: discord.ui.Item,
    ) -> None:
        print(f"Button error in {item}: {error}")
        await send_interaction_message(interaction, "⚠️ Button action failed. Check the bot console.")

    async def get_voice_client(
        self,
        interaction: discord.Interaction,
    ) -> tuple[GuildPlayer | None, discord.VoiceClient | None]:
        if not interaction.guild:
            await send_interaction_message(interaction, "⚠️ This button only works in a server.")
            return None, None

        player = get_player(self.guild_id)
        voice_client = interaction.guild.voice_client

        if not voice_client or not voice_client.is_connected():
            await send_interaction_message(interaction, "⚠️ I am not connected to voice.")
            return player, None

        return player, voice_client

    async def refresh_message(self, interaction: discord.Interaction, player: GuildPlayer) -> None:
        if not player.message or not player.now:
            return

        try:
            voice_client = interaction.guild.voice_client if interaction.guild else None
            paused = bool(voice_client and voice_client.is_paused())
            await player.message.edit(embed=create_music_embed(player.now, player), view=MusicControls(self.guild_id, paused=paused))
        except discord.DiscordException:
            await send_interaction_message(interaction, "⚠️ Could not refresh the player message.")

    @discord.ui.button(emoji="⏯️", style=discord.ButtonStyle.blurple, custom_id="music:pause_resume")
    async def pause_resume(self, interaction: discord.Interaction, button: discord.ui.Button):
        player, voice_client = await self.get_voice_client(interaction)
        if not voice_client:
            return

        if voice_client.is_playing():
            voice_client.pause()
            button.emoji = "▶️"
            await send_interaction_message(interaction, "⏸️ Paused.")
        elif voice_client.is_paused():
            voice_client.resume()
            button.emoji = "⏯️"
            await send_interaction_message(interaction, "▶️ Resumed.")
        else:
            await send_interaction_message(interaction, "ℹ️ Nothing is playing.")
            return

        await self.refresh_message(interaction, player)

    @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.green, custom_id="music:skip")
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        player, voice_client = await self.get_voice_client(interaction)
        if not voice_client or not player:
            return

        if not voice_client.is_playing() and not voice_client.is_paused():
            await send_interaction_message(interaction, "ℹ️ Nothing is playing.")
            return

        skipped_song = player.now.title if player.now else "current song"
        voice_client.stop()

        if player.queue.empty():
            await send_interaction_message(interaction, f"⏭️ Skipped **{skipped_song}**. Queue is empty.")
        else:
            await send_interaction_message(interaction, f"⏭️ Skipped **{skipped_song}**. Playing next song.")

    @discord.ui.button(emoji="⏹️", style=discord.ButtonStyle.red, custom_id="music:stop")
    async def stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        player, voice_client = await self.get_voice_client(interaction)
        if not player:
            return

        player.stopped = True
        player.queue = asyncio.Queue()
        player.now = None
        player.next_song.set()

        if voice_client and (voice_client.is_playing() or voice_client.is_paused()):
            voice_client.stop()

        if player.message:
            try:
                await player.message.edit(content="⏹️ Player stopped.", embed=None, view=None)
            except discord.DiscordException:
                pass

        await send_interaction_message(interaction, "⏹️ Stopped and cleared the queue.")

async def play_song(ctx: commands.Context, player: GuildPlayer, song: Song) -> bool:
    if not song.stream_url:
        await ctx.send(f"⚠️ Could not get an audio stream for **{song.title}**.")
        return False

    voice_client = ctx.guild.voice_client if ctx.guild else None
    if not voice_client or not voice_client.is_connected():
        voice_client = await connect_voice_channel(ctx)
    if not voice_client:
        return False

    player.now = song
    player.stopped = False
    player.next_song.clear()
    song.start_time = time.time()

    try:
        source = await discord.FFmpegOpusAudio.from_probe(
            song.stream_url,
            method="fallback",
            executable=FFMPEG_EXECUTABLE,
            before_options=ffmpeg_before_options,
            options=ffmpeg_options,
        )
    except Exception as exc:
        await ctx.send(f"⚠️ Could not start high-quality audio for **{song.title}**: {exc}")
        return False

    def after_playback(error: Exception | None):
        if error:
            print(f"Playback error: {error}")
        bot.loop.call_soon_threadsafe(player.next_song.set)

    voice_client.play(source, after=after_playback)

    if player.message:
        try:
            await player.message.delete()
        except discord.DiscordException:
            pass

    embed = create_music_embed(song, player)
    player.message = await ctx.send(embed=embed, view=MusicControls(ctx.guild.id))
    return True


async def player_loop(ctx: commands.Context):
    player = get_player(ctx.guild.id)

    while not bot.is_closed():
        try:
            song = await asyncio.wait_for(player.queue.get(), timeout=300)
        except asyncio.TimeoutError:
            voice_client = ctx.guild.voice_client
            if voice_client and voice_client.is_connected() and not voice_client.is_playing():
                await voice_client.disconnect()
            players.pop(ctx.guild.id, None)
            return

        started = await play_song(ctx, player, song)
        if not started:
            continue

        await player.next_song.wait()

        if player.stopped:
            player.now = None
            player.stopped = False
        elif player.queue.empty():
            player.now = None
            if player.message:
                try:
                    await player.message.edit(
                        content="✅ Queue ended. Add more songs with `!play <song name>`.",
                        embed=None,
                        view=None,
                    )
                except discord.DiscordException:
                    pass


def ensure_player_loop(ctx: commands.Context) -> GuildPlayer:
    player = get_player(ctx.guild.id)
    player.text_channel = ctx.channel

    if player.task is None or player.task.done():
        player.task = bot.loop.create_task(player_loop(ctx))

    return player


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")


@bot.command()
@commands.guild_only()
async def join(ctx: commands.Context):
    voice_client = await connect_voice_channel(ctx)
    if voice_client:
        await ctx.send(f"✅ Joined **{voice_client.channel.name}**.")


@bot.command()
@commands.guild_only()
async def play(ctx: commands.Context, *, query: str):
    voice_client = await connect_voice_channel(ctx)
    if not voice_client:
        return

    player = ensure_player_loop(ctx)
    searching_msg = await ctx.send(f"🔎 Searching for: **{query}** ...")

    try:
        song = await extract_info(query)
    except Exception as exc:
        await searching_msg.edit(content=f"⚠️ Could not find or load that track: {exc}")
        return

    song.requester = ctx.author.mention
    await searching_msg.delete()
    await player.queue.put(song)

    if voice_client.is_playing() or voice_client.is_paused() or player.now:
        if player.message and player.now:
            try:
                await player.message.edit(embed=create_music_embed(player.now, player), view=MusicControls(ctx.guild.id))
            except discord.DiscordException:
                pass
        await ctx.send(f"➕ Queued: **{song.title}**")


@bot.command(name="queue")
@commands.guild_only()
async def queue_command(ctx: commands.Context):
    player = get_player(ctx.guild.id)
    await ctx.send(embed=create_queue_embed(player))


@bot.command()
@commands.guild_only()
async def skip(ctx: commands.Context):
    voice_client = ctx.guild.voice_client
    if not voice_client or not voice_client.is_connected():
        await ctx.send("⚠️ I am not connected to voice.")
        return

    if not voice_client.is_playing() and not voice_client.is_paused():
        await ctx.send("ℹ️ Nothing is playing.")
        return

    player = get_player(ctx.guild.id)
    skipped_song = player.now.title if player.now else "current song"
    voice_client.stop()

    if player.queue.empty():
        await ctx.send(f"⏭️ Skipped **{skipped_song}**. Queue is empty.")
    else:
        await ctx.send(f"⏭️ Skipped **{skipped_song}**. Playing next song.")


@bot.command()
@commands.guild_only()
async def leave(ctx: commands.Context):
    player = players.pop(ctx.guild.id, None)
    if player:
        player.stopped = True
        if player.task and not player.task.done():
            player.task.cancel()
        if player.message:
            try:
                await player.message.edit(content="👋 Left voice channel.", embed=None, view=None)
            except discord.DiscordException:
                pass

    voice_client = ctx.guild.voice_client
    if voice_client and voice_client.is_connected():
        await voice_client.disconnect(force=True)
        await ctx.send("👋 Left voice channel.")
    else:
        await ctx.send("ℹ️ I am not connected to voice.")


@bot.command()
@commands.guild_only()
async def stop(ctx: commands.Context):
    player = get_player(ctx.guild.id)
    player.stopped = True
    player.queue = asyncio.Queue()
    player.now = None
    player.next_song.set()

    voice_client = ctx.guild.voice_client
    if voice_client and (voice_client.is_playing() or voice_client.is_paused()):
        voice_client.stop()

    if player.message:
        try:
            await player.message.edit(content="⏹️ Player stopped.", embed=None, view=None)
        except discord.DiscordException:
            pass

    await ctx.send("⏹️ Stopped and cleared the queue.")


if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
