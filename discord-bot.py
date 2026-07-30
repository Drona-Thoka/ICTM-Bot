import os
import discord
from discord import app_commands
import aiohttp
from dotenv import load_dotenv
import asyncio

load_dotenv()

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
API_BASE = os.getenv("API_BASE_URL")

user_problems = {}

class BotClient(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()
        print("Bot commands are ready!")

client = BotClient()

# ---------- API helpers ----------
async def api_get(endpoint, params=None):
    async with aiohttp.ClientSession() as session:
        url = f"{API_BASE}{endpoint}"
        try:
            async with session.get(url, params=params, timeout=8) as resp:
                if resp.status == 200:
                    return await resp.json()
                return None
        except (asyncio.TimeoutError, Exception):
            return None

async def api_post(endpoint, data=None):
    async with aiohttp.ClientSession() as session:
        url = f"{API_BASE}{endpoint}"
        try:
            async with session.post(url, json=data, timeout=8) as resp:
                if resp.status in (200, 201):
                    return await resp.json()
                return None
        except (asyncio.TimeoutError, Exception):
            return None

# ---------- Commands ----------
@client.tree.command(name="practice", description="Get a random math problem")
@app_commands.describe(
    competition="AMC10, AMC12, AIME, NSML, or ICTM",
    topic="Algebra, Geometry, etc. (optional)",
    difficulty="easy, medium, or hard (optional)"
)
async def practice(interaction: discord.Interaction, competition: str, topic: str = None, difficulty: str = None):
    await interaction.response.defer()

    params = {"competition": competition}
    if topic:
        params["topic"] = topic
    if difficulty:
        params["difficulty"] = difficulty

    data = await api_get("/problems/random", params=params)
    if not data:
        await interaction.followup.send(
            "❌ No problem found with those filters, or API timed out.\nTry `/practice competition:AMC10`.",
            ephemeral=True
        )
        return

    user_problems[interaction.user.id] = data["problem_id"]

    # Build a clean text version
    lines = []
    lines.append(f"**{data['competition_name']} - Problem {data['problem_id']}**")
    lines.append("")  # blank line
    lines.append(data['problem_text'])
    if data.get('choices'):
        lines.append("")
        lines.append("**Choices:**")
        for letter, value in data['choices'].items():
            lines.append(f"{letter}: {value}")

    problem_text = "\n".join(lines)

    # Send as a code block (monospace, readable)
    await interaction.followup.send(f"```latex\n{problem_text}\n```")
    await interaction.followup.send("Type `/answer YOUR_ANSWER` to check.")

@client.tree.command(name="answer", description="Check your answer for the current problem")
@app_commands.describe(answer="Your answer (e.g., 42, A, or 3/4)")
async def answer(interaction: discord.Interaction, answer: str):
    await interaction.response.defer()

    problem_id = user_problems.get(interaction.user.id)
    if not problem_id:
        await interaction.followup.send("You don't have an active problem. Use `/practice` first.", ephemeral=True)
        return

    data = await api_post(f"/problems/{problem_id}/check", data={"answer": answer})
    if not data:
        await interaction.followup.send("❌ Error checking answer. API may be slow.", ephemeral=True)
        return

    if data["correct"]:
        msg = "✅ **Correct!**"
    else:
        msg = f"❌ **Incorrect.** Correct answer: `{data['correct_answer']}`"

    if data.get("solution_text"):
        msg += f"\n\n**Solution:**\n{data['solution_text']}"

    await interaction.followup.send(msg)

@client.tree.command(name="ping", description="Check if bot is alive")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("Pong!")

if __name__ == "__main__":
    print("Starting bot...")
    client.run(TOKEN)