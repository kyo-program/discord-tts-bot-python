import asyncio
from collections import deque
from dotenv import load_dotenv
import discord
from discord import app_commands
from discord.ext import commands
import edge_tts
import io
import os
import re
load_dotenv()

TOKEN = os.getenv("TOKEN")
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", 0))
executable_path = os.getcwd() + "/ffmpeg.exe"

intents = discord.Intents.all()
bot = commands.Bot(command_prefix='>', intents=intents)
tree = bot.tree

all_voices = []
guilds_config = {}
queues = {}

@bot.event
async def on_ready():
    print(f"ログインしました: {bot.user}")
    voice_manager = await edge_tts.VoicesManager.create()
    japanese_voices = voice_manager.find(Locale="ja-JP")
    all_voices.clear()
    for v in japanese_voices:
        print(v)
        display_name = v["Name"].split(", ")[1].split(")")[0]
        all_voices.append({"name": display_name, "value": v["ShortName"]})
    for guild in bot.guilds:
        guilds_config[guild.id] = {"speaker": all_voices[0]["value"] if all_voices else "ja-JP-NanamiNeural"}
        queues[guild.id] = deque()
    await tree.sync()
    if LOG_CHANNEL_ID:
        channel = bot.get_channel(LOG_CHANNEL_ID)
        if channel:
            await channel.send(f"TTS Bot 起動完了！ {len(all_voices)} 個の声をロードしました。")

def check_queue(ctx, guild_id):
    vc = ctx.guild.voice_client
    if vc and queues.get(guild_id):
        next_text = queues[guild_id].popleft()
        coro = play_tts(ctx, next_text)
        asyncio.run_coroutine_threadsafe(coro, bot.loop)

async def play_tts(ctx, text):
    clean_text = text.replace('"', '""').replace('\\', '').strip()
    if not re.search(r'[\w\u3040-\u30ff\u4e00-\u9faf]', clean_text):
        return check_queue(ctx, ctx.guild.id)
    vc = ctx.guild.voice_client
    if not vc: return
    speaker = guilds_config.get(ctx.guild.id, {}).get("speaker", "ja-JP-NanamiNeural")
    audio_data = io.BytesIO()
    try:
        communicate = edge_tts.Communicate(clean_text, speaker)
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_data.write(chunk["data"])
        if audio_data.tell() == 0:
            return check_queue(ctx, ctx.guild.id)

        audio_data.seek(0)
    except Exception as e:
        print(f"TTS生成エラー: {e}")
        return check_queue(ctx, ctx.guild.id)
    source = discord.FFmpegPCMAudio(audio_data, pipe=True, options='-loglevel panic', executable=executable_path)
    try:
        vc.play(source, after=lambda e: check_queue(ctx, ctx.guild.id))
    except discord.errors.ClientException:
        queues[ctx.guild.id].appendleft(text)
    except Exception as e:
        print(f"再生エラー: {e}")
        check_queue(ctx, ctx.guild.id)
        
@bot.event
async def on_message(message):
    if message.author.bot or message.content.startswith(">") or not message.guild:
        return
    vc = message.guild.voice_client
    if vc and vc.is_connected():
        guild_id = message.guild.id
        if guild_id not in queues:
            queues[guild_id] = deque()
        if vc.is_playing() or len(queues[guild_id]) > 0:
            queues[guild_id].append(message.content)
        else:
            try:
                await play_tts(message, message.content)
            except discord.errors.ClientException:
                queues[guild_id].append(message.content)

@tree.command(name="join", description="コマンド実行者がいるVCに参加します")
async def join(interaction: discord.Interaction):
    if interaction.user.voice:
        channel = interaction.user.voice.channel
        await channel.connect()
        await interaction.response.send_message(f"✅ {channel.name} に接続しました。")
    else:
        await interaction.response.send_message("❌ 先にボイスチャンネルに入ってください。", ephemeral=True)

@tree.command(name="leave", description="VCから退出します")
async def leave(interaction: discord.Interaction):
    if interaction.guild.voice_client:
        await interaction.guild.voice_client.disconnect()
        queues[interaction.guild.id].clear()
        await interaction.response.send_message("👋 退室しました。")
    else:
        await interaction.response.send_message("接続していません。", ephemeral=True)

async def speaker_autocomplete(interaction: discord.Interaction, current: str):
    """スピーカー選択の補完機能"""
    return [
        app_commands.Choice(name=v["name"], value=v["value"])
        for v in all_voices if current.lower() in v["name"].lower()
    ][:25]

@tree.command(name="speaker", description="読み上げの声を設定します")
@app_commands.autocomplete(name=speaker_autocomplete)
async def speaker(interaction: discord.Interaction, name: str):
    valid_ids = [v["value"] for v in all_voices]
    if name not in valid_ids:
        await interaction.response.send_message("有効なスピーカーを候補から選んでください。", ephemeral=True)
        return

    guilds_config[interaction.guild_id] = {"speaker": name}
    display_name = next((v["name"] for v in all_voices if v["value"] == name), name)
    await interaction.response.send_message(f"🗣 話者を **{display_name}** に設定しました。")
        

bot.run(TOKEN)