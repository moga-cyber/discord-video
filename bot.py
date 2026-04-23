import os
import re
import asyncio
import logging
import subprocess
from typing import Optional, Tuple

import discord
from discord.ext import commands
from discord import app_commands
import yt_dlp

# ==================== الإعدادات ====================
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise ValueError("❌ DISCORD_TOKEN غير موجود")

DOWNLOAD_PATH = "/tmp/downloads"
MAX_FILE_SIZE = 25 * 1024 * 1024
BAD_WORDS = ["سب", "شتم", "كس", "عرص", "منيوك", "خول", "شرموط", "زنديق", "ملحد"]

os.makedirs(DOWNLOAD_PATH, exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

stats = {"total": 0, "platforms": {}, "formats": {}}

def detect_url(text):
    urls = re.findall(r'(https?://[^\s<>"]+|www\.[^\s<>"]+)', text)
    return urls[0] if urls else None

def get_platform(url):
    platforms = {
        "youtube.com": "YouTube", "youtu.be": "YouTube",
        "instagram.com": "Instagram", "tiktok.com": "TikTok",
        "facebook.com": "Facebook", "fb.watch": "Facebook",
        "twitter.com": "Twitter/X", "x.com": "Twitter/X"
    }
    for domain, name in platforms.items():
        if domain in url.lower():
            return name
    return "Unknown"

def is_bad_word(text):
    return any(word in text.lower() for word in BAD_WORDS)

async def download_media(url: str, format_type: str = "video") -> Tuple[bool, Optional[str], str, str, str]:
    ydl_opts = {
        'quiet': True, 'no_warnings': True,
        'outtmpl': f'{DOWNLOAD_PATH}/%(title).100s.%(ext)s',
        'restrictfilenames': True, 'noplaylist': True,
        'user_agent': 'Mozilla/5.0',
    }
    
    if format_type == 'audio':
        ydl_opts.update({
            'format': 'bestaudio/best',
            'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}],
        })
    else:
        ydl_opts.update({'format': 'bestvideo[ext=mp4][height<=720]+bestaudio[ext=m4a]/best[ext=mp4]/best'})
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = await asyncio.to_thread(ydl.extract_info, url, download=True)
            file_path = ydl.prepare_filename(info)
            if format_type == 'audio':
                file_path = file_path.rsplit('.', 1)[0] + '.mp3'
                ext = 'mp3'
            else:
                ext = os.path.splitext(file_path)[1][1:]
            return True, file_path, info.get('title', 'بدون عنوان'), get_platform(url), ext
    except Exception as e:
        return False, None, str(e), "Unknown", ""

intents = discord.Intents.all()
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

class FormatSelect(discord.ui.Select):
    def __init__(self, url: str, platform: str):
        self.url = url
        self.platform = platform
        options = [
            discord.SelectOption(label="🎬 فيديو MP4", value="video", emoji="🎬"),
            discord.SelectOption(label="🎵 صوت MP3", value="audio", emoji="🎵"),
        ]
        super().__init__(placeholder="اختر نوع التحميل...", options=options)
    
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        format_type = self.values[0]
        format_names = {"video": "فيديو", "audio": "صوت"}
        
        embed = discord.Embed(title="⏳ جاري التحميل...", description=f"**المنصة:** {self.platform}\n**النوع:** {format_names[format_type]}", color=0xFEE75C)
        msg = await interaction.followup.send(embed=embed)
        
        success, file_path, title, platform, ext = await download_media(self.url, format_type)
        
        if not success:
            await msg.edit(embed=discord.Embed(title="❌ فشل التحميل", description=title[:1000], color=0xED4245))
            return
        
        file_size = os.path.getsize(file_path)
        if file_size > MAX_FILE_SIZE:
            await msg.edit(embed=discord.Embed(title="❌ الملف كبير جداً", description=f"{file_size//(1024*1024)}MB > {MAX_FILE_SIZE//(1024*1024)}MB", color=0xED4245))
            os.remove(file_path)
            return
        
        stats["total"] += 1
        stats["platforms"][platform] = stats["platforms"].get(platform, 0) + 1
        stats["formats"][format_type] = stats["formats"].get(format_type, 0) + 1
        
        embed = discord.Embed(title="✅ تم التحميل!", description=f"**{title}**", color=0x57F287)
        embed.add_field(name="📊 المنصة", value=platform, inline=True)
        embed.add_field(name="📦 الحجم", value=f"{file_size//(1024*1024)}MB", inline=True)
        
        try:
            await msg.delete()
            await interaction.channel.send(embed=embed, file=discord.File(file_path))
            os.remove(file_path)
        except:
            await interaction.channel.send("❌ خطأ في الإرسال")
            if os.path.exists(file_path):
                os.remove(file_path)

class DownloadView(discord.ui.View):
    def __init__(self, url: str, platform: str):
        super().__init__(timeout=120)
        self.add_item(FormatSelect(url, platform))

@bot.event
async def on_ready():
    logger.info(f"✅ {bot.user} جاهز!")
    await bot.tree.sync()

@bot.event
async def on_message(message):
    if message.author.bot: return
    if is_bad_word(message.content):
        await message.add_reaction("🕌")
        await message.reply("✨ لا إله إلا الله ✨", delete_after=5)
        return
    url = detect_url(message.content)
    if url:
        platform = get_platform(url)
        embed = discord.Embed(title="🔗 تم اكتشاف رابط!", description=f"**المنصة:** {platform}\nاختر نوع التحميل:", color=0x5865F2)
        await message.reply(embed=embed, view=DownloadView(url, platform))

@bot.tree.command(name="help", description="📚 قائمة الأوامر")
async def slash_help(interaction: discord.Interaction):
    embed = discord.Embed(title="🤖 أوامر البوت", color=0x5865F2)
    embed.add_field(name="📥 التحميل", value="أرسل أي رابط مباشرة", inline=False)
    await interaction.response.send_message(embed=embed)

if __name__ == "__main__":
    bot.run(TOKEN)
