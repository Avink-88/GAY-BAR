import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
import yt_dlp
import asyncio

# 讀取隱藏的 .env 檔案（密碼檔）
load_dotenv()

# 1. 設定機器人的意圖 (Intents)
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

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
    'executable': './ffmpeg.exe',
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
    async def from_url(cls, url, *, loop=None, stream=True):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))
        if 'entries' in data:
            data = data['entries']
        filename = data['url'] if stream else ytdl.prepare_filename(data)
        return cls(discord.FFmpegPCMAudio(filename, **FFMPEG_OPTIONS), data=data)

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

# 6. 播放音樂指令 (!play [網址或關鍵字])
@bot.command()
async def play(ctx, *, url):
    if not ctx.author.voice:
        await ctx.send("❌ 你必須先進入一個語音頻道！")
        return
    channel = ctx.author.voice.channel
    if ctx.voice_client is None:
        await channel.connect()
    else:
        await ctx.voice_client.move_to(channel)

    async with ctx.typing():
        try:
            player = await YTDLSource.from_url(url, loop=bot.loop, stream=True)
            ctx.voice_client.play(player, after=lambda e: print(f'Player error: {e}') if e else None)
            await ctx.send(f"🎵 正在播放：**{player.title}**")
        except Exception as e:
            await ctx.send(f"❌ 播放時發生錯誤: {e}")

#111
#222
# 7. 離開語音頻道指令 (!leave)
@bot.command()
async def leave(ctx):
    if ctx.voice_client:
        await ctx.voice_client.disconnect()
        await ctx.send("👋 已離開語音頻道。")
    else:
        await ctx.send("❌ 我目前不在任何語音頻道中。")

# 8. 自動從環境變數讀取您的 Token
# 如果您的 .env 檔案裡已經有寫 TOKEN=xxxx，保持原本的即可
# 如果沒有設定 .env，請直接把 "請在這裡貼上您的Token" 改成您在網頁複製的那串密碼
TOKEN = os.getenv('TOKEN') or "請在這裡貼上您的Token"
bot.run(TOKEN)
