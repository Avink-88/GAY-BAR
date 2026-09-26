import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
import yt_dlp
import asyncio
import shlex
from collections import deque
from contextlib import suppress
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

# 讀取隱藏的 .env 檔案（密碼檔）
load_dotenv(Path(__file__).with_name('.env'))

# 1. 設定機器人的意圖 (Intents)
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)


@bot.command(name='help')
async def show_help(ctx):
    description = (
        "🎵 **音樂機器人指令說明**\n\n"
        "不會看的是Gay，騙你的，看了也是\n\n"
        "`!play <網址或關鍵字>`\n"
        "播放 YouTube／Bilibili 連結，或用關鍵字搜尋。已有歌曲時加入隊列，播完自動接下一首。\n"
        "範例：`!play https://b23.tv/BomDNOX`\n\n"
        "`!queue [頁碼]` 或 `!q [頁碼]`\n"
        "查看目前歌曲與待播標題，每頁 10 首。例如 `!queue 2` 查看第二頁。\n\n"
        "`!skip`\n"
        "跳過目前歌曲並播放下一首，歌曲解析中也能使用。\n\n"
        "`!clear`\n"
        "清空待播清單，目前歌曲繼續播放。\n\n"
        "`!leave`\n"
        "停止播放、清空待播清單並離開語音頻道。\n\n"
        "`!hello`：讓機器人打招呼。\n"
        "`!help`：顯示這份說明。\n\n"
        "**使用提醒**\n"
        "• 音樂指令請在伺服器文字頻道使用；點歌與控制音樂前，先加入機器人所在的語音頻道。\n"
        "• 每個伺服器的隊列獨立，最多待播 100 首，點超過100首真他媽不是人；重啟機器人後會清空。\n"
        "• 無法播放的歌曲會自動跳過；受登入或地區限制的影片可能無法播放。\n"
        "• Gay Bar 是給 Gay 專用的"

    )
    embed = discord.Embed(title="🎧 音樂機器人 · 使用指南", colour=0x5865F2)
    for section in description.split('\n\n')[1:]:
        name, _, value = section.partition('\n')
        embed.add_field(name=name.strip('*'), value=value or ' ', inline=False)
    embed.set_footer(text="輸入 !queue 開啟播放清單卡片，可按按鈕翻頁及重新整理。")
    await ctx.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())

# 2. 設定 yt-dlp 下載參數（支援 YouTube 與 Bilibili）
YTDL_OPTIONS = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0',
    'http_headers': {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
    }
}

# 3. 設定 FFmpeg 播放參數（直接讀取同資料夾底下的 ffmpeg.exe）
FFMPEG_OPTIONS = {
    'executable': os.getenv('FFMPEG_PATH') or (
        str(Path(__file__).with_name('ffmpeg.exe'))
        if Path(__file__).with_name('ffmpeg.exe').is_file() else 'ffmpeg'),
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')

    @classmethod
    async def extract_info(cls, url, *, loop=None, stream=True):
        loop = loop or asyncio.get_event_loop()
        url = url.strip().strip('<>')
        parsed = urlsplit(url)
        if parsed.hostname in {'bilibili.com', 'm.bilibili.com'}:
            url = urlunsplit(('https', 'www.bilibili.com', parsed.path, parsed.query, ''))

        def extract():
            # 不共用解析器，避免不同伺服器同時點歌時互相影響。
            with yt_dlp.YoutubeDL(YTDL_OPTIONS) as extractor:
                return extractor.extract_info(url, download=not stream)

        data = await loop.run_in_executor(None, extract)
        while data and 'entries' in data:
            # 搜尋結果或 Bilibili 分 P 會回傳清單，而非影片字典。
            data = next((entry for entry in (data['entries'] or []) if entry), None)
        if not data or not data.get('url'):
            raise ValueError('找不到可播放的音訊，請使用單支影片連結。')
        return data

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=True):
        data = await cls.extract_info(url, loop=loop, stream=stream)
        filename = data['url'] if stream else ytdl.prepare_filename(data)
        options = dict(FFMPEG_OPTIONS)
        if stream:
            # yt-dlp 與 FFmpeg 是不同的 HTTP 用戶端，標頭必須另外傳給 FFmpeg。
            headers = dict(data.get('http_headers') or {})
            if str(data.get('extractor_key', data.get('extractor', ''))).lower().startswith('bili'):
                headers.setdefault('Referer', 'https://www.bilibili.com/')
            header_text = ''.join(
                f'{key}: {value}\r\n' for key, value in headers.items()
                if '\r' not in str(key) + str(value) and '\n' not in str(key) + str(value))
            if header_text:
                options['before_options'] += ' -headers ' + shlex.quote(header_text)
        return cls(discord.FFmpegPCMAudio(filename, **options), data=data)

# 4. 機器人上線事件
@bot.event
async def on_ready():
    print(f"🎉 音樂與文字機器人已成功上線！")
    print(f"目前登入帳號：{bot.user.name} (ID: {bot.user.id})")
    print("----------------------------------------")

# 5. 【新增回來】基本的文字回應指令範例（在 DC 輸入 !hello）
@bot.command()
async def hello(ctx):
    await ctx.send(f"嗨！{ctx.author.mention}，找我嗎？🤖")

class MusicQueue:
    """每個伺服器獨立，輪到播放才解析音訊網址。"""
    def __init__(self):
        self.pending = deque()
        self.current = None
        self.task = None
        self.lock = asyncio.Lock()
        self.voice = None

    def start(self):
        if self.pending and (self.task is None or self.task.done()):
            self.task = asyncio.create_task(self.run())

    async def cancel(self):
        if self.task and not self.task.done():
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task
        self.task = None
        self.current = None
        if self.voice:
            self.voice.stop()

    async def run(self):
        try:
            while self.pending and self.voice and self.voice.is_connected():
                url, channel, title = self.pending.popleft()
                self.current = title
                source = None
                handed_off = False
                try:
                    source = await YTDLSource.from_url(url, stream=True)
                    done = asyncio.Event()
                    loop = asyncio.get_running_loop()
                    errors = []

                    def finished(error, event=done, failures=errors):
                        if error:
                            failures.append(error)
                        if not loop.is_closed():
                            loop.call_soon_threadsafe(event.set)

                    self.voice.play(source, after=finished)
                    handed_off = True
                    self.current = source.title or title
                    await music_message(channel, f"🎵 正在播放：{self.current[:300]}")
                    await done.wait()
                    if errors:
                        await music_message(channel, "❌ 播放中斷，將嘗試下一首。")
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    print(f"Queue playback error: {type(error).__name__}: {error}")
                    await music_message(channel, "❌ 這首無法播放，將嘗試下一首。請查看終端機錯誤。")
                finally:
                    if source and not handed_off:
                        source.cleanup()
                    self.current = None
        finally:
            self.current = None


music_queues = {}


async def music_message(channel, text):
    with suppress(discord.HTTPException):
        await channel.send(text, allowed_mentions=discord.AllowedMentions.none(), suppress_embeds=True)


def queue_for(guild_id):
    if guild_id not in music_queues:
        music_queues[guild_id] = MusicQueue()
    return music_queues[guild_id]


async def control_channel(ctx):
    state = ctx.author.voice
    if not state or not state.channel:
        await ctx.send("❌ 請先加入語音頻道。")
        return None
    if ctx.voice_client and ctx.voice_client.channel != state.channel:
        await ctx.send("❌ 請加入機器人所在的語音頻道再操作。")
        return None
    return state.channel


# 6. 播放音樂指令 (!play [網址或關鍵字])
@bot.command()
@commands.guild_only()
async def play(ctx, *, url):
    state = queue_for(ctx.guild.id)
    async with state.lock:
        channel = await control_channel(ctx)
        if channel is None:
            return
        try:
            state.voice = ctx.voice_client or await channel.connect()
            if not state.voice.is_connected():
                await ctx.send("❌ 語音已斷線，請先 !leave 再點歌。")
                return
            if len(state.pending) >= 100:
                await ctx.send("隊列最多 100 首，請稍後再點歌。")
                return
            await music_message(ctx.channel, "🔎 讓我看看又是哪個Gay來點歌了 ")
            try:
                data = await asyncio.wait_for(YTDLSource.extract_info(url), timeout=30)
            except (yt_dlp.utils.DownloadError, ValueError, asyncio.TimeoutError):
                await ctx.send("❌ 無法取得影片資訊，未加入隊列。請確認連結或稍後重試。")
                return
            # 搜尋只在加入時執行一次，播放時使用選定影片的頁面網址。
            video_url = data.get('webpage_url') or data.get('original_url') or url.strip()
            title = ' '.join(str(data.get('title') or '未知標題').split())
            state.pending.append((video_url, ctx.channel, title))
            position = len(state.pending)
            state.start()
            await music_message(ctx.channel, f"✅ 已加入：{title[:200]}（待播第 {position} 首）。")
        except (discord.DiscordException, asyncio.TimeoutError) as error:
            await ctx.send(f"❌ 無法加入語音頻道：{type(error).__name__}")


class QueueView(discord.ui.View):
    def __init__(self, guild_id, page=1):
        super().__init__(timeout=180)
        self.guild_id = guild_id
        self.page = page
        self.message = None
        self.edit_lock = asyncio.Lock()

    def render(self):
        state = queue_for(self.guild_id)
        tracks = list(state.pending)
        pages = max(1, (len(tracks) + 9) // 10)
        self.page = max(1, min(self.page, pages))
        self.previous.disabled = self.page == 1
        self.next_page.disabled = self.page == pages
        start = (self.page - 1) * 10
        lines = [f'{i}. {discord.utils.escape_markdown(title[:120])}'
                 for i, (_, _, title) in enumerate(tracks[start:start + 10], start + 1)]
        embed = discord.Embed(title="🎶 播放清單", colour=0x1DB954,
                              description='\n'.join(lines) or '待播隊列是空的，使用 `!play 網址` 加入歌曲。')
        embed.add_field(name="🎵 目前播放／解析中", inline=False,
                        value=discord.utils.escape_markdown(state.current[:200]) if state.current else '目前沒有播放中的歌曲。')
        embed.add_field(name="待播歌曲", value=f'{len(tracks)} 首', inline=True)
        embed.add_field(name="頁碼", value=f'{self.page}/{pages}', inline=True)
        embed.set_footer(text="按重新整理取得最新隊列 · 按鈕閒置 3 分鐘後失效，可重新輸入 !queue")
        return embed

    async def update(self, interaction, offset=0):
        await interaction.response.defer()
        async with self.edit_lock:
            self.page += offset
            await interaction.edit_original_response(embed=self.render(), view=self,
                                                     allowed_mentions=discord.AllowedMentions.none())

    @discord.ui.button(label="上一頁", emoji="◀️", style=discord.ButtonStyle.secondary)
    async def previous(self, interaction, button):
        await self.update(interaction, -1)

    @discord.ui.button(label="重新整理", emoji="🔄", style=discord.ButtonStyle.primary)
    async def refresh(self, interaction, button):
        await self.update(interaction)

    @discord.ui.button(label="下一頁", emoji="▶️", style=discord.ButtonStyle.secondary)
    async def next_page(self, interaction, button):
        await self.update(interaction, 1)

    async def on_timeout(self):
        async with self.edit_lock:
            for button in self.children:
                button.disabled = True
            if self.message:
                with suppress(discord.HTTPException):
                    await self.message.edit(view=self)


@bot.command(name='queue', aliases=['q'])
@commands.guild_only()
async def show_queue(ctx, page='1'):
    state = queue_for(ctx.guild.id)
    tracks = list(state.pending)
    pages = max(1, (len(tracks) + 9) // 10)
    try:
        page = int(page)
    except (ValueError, TypeError):
        await ctx.send("請輸入整數頁碼，例如 `!queue 2`。")
        return
    if not 1 <= page <= pages:
        await ctx.send(f"頁碼超出範圍，目前共有 {pages} 頁。請使用 `!queue 1` 查看。")
        return
    view = QueueView(ctx.guild.id, page)
    try:
        view.message = await ctx.send(embed=view.render(), view=view,
                                      allowed_mentions=discord.AllowedMentions.none())
    except discord.HTTPException:
        view.stop()
        raise


@bot.command()
@commands.guild_only()
async def skip(ctx):
    state = queue_for(ctx.guild.id)
    async with state.lock:
        if await control_channel(ctx) is None:
            return
        if state.current is None:
            await ctx.send("目前沒有可跳過的歌曲。")
            return
        await state.cancel()
        state.start()
        await ctx.send("⏭️ 已跳過目前歌曲。")


@bot.command()
@commands.guild_only()
async def clear(ctx):
    state = queue_for(ctx.guild.id)
    async with state.lock:
        if await control_channel(ctx) is None:
            return
        count = len(state.pending)
        state.pending.clear()
        await ctx.send(f"已清除 {count} 首待播歌曲，目前歌曲繼續播放。")

#111
#222
# 7. 離開語音頻道指令 (!leave)
@bot.command()
@commands.guild_only()
async def leave(ctx):
    state = queue_for(ctx.guild.id)
    async with state.lock:
        if await control_channel(ctx) is None:
            return
        state.pending.clear()
        await state.cancel()
        if ctx.voice_client:
            await ctx.voice_client.disconnect()
        state.voice = None
        await ctx.send("👋 已清空隊列並離開語音頻道。")


@bot.event
async def on_voice_state_update(member, before, after):
    if bot.user and member.id == bot.user.id and after.channel is None:
        state = music_queues.get(member.guild.id)
        if state:
            async with state.lock:
                if state.voice and not state.voice.is_connected():
                    state.pending.clear()
                    await state.cancel()
                    state.voice = None

# 8. 自動從環境變數讀取您的 Token
# 同時相容原本的 DISCORD_TOKEN 與朋友版本的 TOKEN；不要將密碼寫入程式。
if __name__ == '__main__':
    TOKEN = os.getenv('DISCORD_TOKEN') or os.getenv('TOKEN')
    if not TOKEN:
        raise SystemExit('請在 .env 設定 DISCORD_TOKEN。')
    bot.run(TOKEN)
