import discord
from discord.ext import commands
import os                       # 1. 新增這行
from dotenv import load_dotenv  # 2. 新增這行

load_dotenv()                   # 3. 新增這行，這會讀取 .env 檔案
# 1. 設定機器人的意圖 (Intents)
# 請確保您在網頁的 Bot 頁面下方有將 Presence、Server Members、Message Content 這三個 Intent 開啟 (ON)
intents = discord.Intents.default()
intents.message_content = True  # 允許讀取訊息內容

# 2. 設定指令的前綴（這裡設定為驚嘆號 !）
bot = commands.Bot(command_prefix="!", intents=intents)


# 3. 當機器人成功連線到 Discord 時觸發
@bot.event
async def on_ready():
    print(f"🎉 機器人已成功上線！")
    print(f"目前登入帳號：{bot.user.name} (ID: {bot.user.id})")
    print("----------------------------------------")


# 4. 基本的文字回應指令範例（在 DC 輸入 !hello）
@bot.command()
async def hello(ctx):
    await ctx.send(f"嗨！{ctx.author.mention}，找你爹我嗎？小蘿莉🤖")


# ⚠️ 請把引號內的文字，替換成您剛剛在網頁上點「重設權杖」複製下來的那串 Token！!!
bot.run(os.getenv("DISCORD_TOKEN"))

#111
#222
