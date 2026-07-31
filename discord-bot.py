import os
import discord
from discord import app_commands
import aiohttp
from dotenv import load_dotenv
import asyncio
import logging
import urllib.parse
import io

# ---------- Setup ----------
logging.basicConfig(level=logging.INFO)
load_dotenv()

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
API_BASE = os.getenv("API_BASE_URL")

if not TOKEN or not API_BASE:
    raise ValueError("Missing DISCORD_BOT_TOKEN or API_BASE_URL in .env file.")

user_problems = {}

# ---------- LaTeX Renderer (CodeCogs PNG) ----------
async def render_latex(text, filename="latex.png"):
    """Render LaTeX text as a PNG image with white background and black text."""
    encoded = urllib.parse.quote(text)
    url = f"https://latex.codecogs.com/png.image?{encoded}&bg=255,255,255&fg=000000"
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    return discord.File(io.BytesIO(data), filename=filename)
                logging.warning(f"CodeCogs returned {resp.status}")
                return None
        except Exception as e:
            logging.warning(f"CodeCogs error: {e}")
            return None

# ---------- API Helpers ----------
async def api_get(endpoint, params=None):
    async with aiohttp.ClientSession() as session:
        url = f"{API_BASE}{endpoint}"
        try:
            async with session.get(url, params=params, timeout=15) as resp:
                if resp.status == 200:
                    return await resp.json()
                return None
        except Exception:
            return None

async def api_post(endpoint, data=None):
    async with aiohttp.ClientSession() as session:
        url = f"{API_BASE}{endpoint}"
        try:
            async with session.post(url, json=data, timeout=15) as resp:
                if resp.status in (200, 201):
                    return await resp.json()
                return None
        except Exception:
            return None

# ---------- Discord Client ----------
class BotClient(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()
        logging.info("Commands synced!")

client = BotClient()

# ---------- Commands ----------
@client.tree.command(name="practice", description="Get a random math problem")
@app_commands.describe(
    competition="AMC10, AMC12, AIME, NSML, or ICTM",
    topic="Algebra, Geometry, etc. (optional)",
    difficulty="easy, medium, or hard (optional)"
)
async def practice(interaction: discord.Interaction, competition: str, topic: str = None, difficulty: str = None):
    await interaction.response.defer()

    try:
        params = {"competition": competition}
        if topic: params["topic"] = topic
        if difficulty: params["difficulty"] = difficulty

        data = await api_get("/problems/random", params=params)
        if not data:
            await interaction.followup.send("❌ No problem found.", ephemeral=True)
            return

        if "problem_id" not in data or "problem_text" not in data:
            await interaction.followup.send("❌ Invalid API response.", ephemeral=True)
            return

        user_problems[interaction.user.id] = data["problem_id"]

        # Build problem text with horizontal choices grid
        lines = []
        lines.append(f"{data.get('competition_name', 'Unknown')} - Problem {data['problem_id']}")
        lines.append("")
        lines.append(data['problem_text'].strip())

        if data.get('choices'):
            # Format choices as a horizontal line: (A) 85   (B) 93   ...
            choices = data['choices']
            # Ensure we sort by letter to maintain order (A, B, C...)
            sorted_choices = sorted(choices.items())
            choices_line = "    ".join([f"({letter}) {value}" for letter, value in sorted_choices])
            lines.append("")
            lines.append("Choices:")
            lines.append(choices_line)

        problem_text = "\n".join(lines)

        # Render as image
        image_file = await render_latex(problem_text, "problem.png")
        if image_file:
            embed = discord.Embed(
                title=f"📐 {data.get('competition_name', 'Unknown')} - Problem {data['problem_id']}",
                color=discord.Color.blue()
            )
            embed.set_image(url="attachment://problem.png")
            embed.set_footer(text="Type /answer YOUR_ANSWER to check.")
            await interaction.followup.send(embed=embed, file=image_file)
        else:
            # Fallback to raw text
            await interaction.followup.send(f"```latex\n{problem_text}\n```")
            await interaction.followup.send("Type `/answer YOUR_ANSWER` to check.")

    except Exception as e:
        logging.error(f"Practice error: {e}")
        await interaction.followup.send("❌ Something went wrong.", ephemeral=True)


@client.tree.command(name="answer", description="Check your answer")
@app_commands.describe(answer="Your answer (e.g., 42, A, or 3/4)")
async def answer(interaction: discord.Interaction, answer: str):
    await interaction.response.defer()

    try:
        problem_id = user_problems.get(interaction.user.id)
        if not problem_id:
            await interaction.followup.send("No active problem. Use `/practice` first.", ephemeral=True)
            return

        data = await api_post(f"/problems/{problem_id}/check", data={"answer": answer})
        if not data:
            await interaction.followup.send("❌ API error.", ephemeral=True)
            return

        if data.get("correct"):
            result_text = "✅ Correct!"
            color = discord.Color.green()
        else:
            correct = data.get("correct_answer", "unknown")
            result_text = f"❌ Incorrect. Correct answer: `{correct}`"
            color = discord.Color.red()

        solution_text = data.get("solution_text")
        if solution_text:
            full_text = f"{result_text}\n\n**Solution:**\n{solution_text.strip()}"
        else:
            full_text = result_text

        image_file = await render_latex(full_text, "solution.png")
        if image_file:
            embed = discord.Embed(
                title="📊 Answer Result",
                color=color
            )
            embed.set_image(url="attachment://solution.png")
            await interaction.followup.send(embed=embed, file=image_file)
        else:
            await interaction.followup.send(full_text)

    except Exception as e:
        logging.error(f"Answer error: {e}")
        await interaction.followup.send("❌ Something went wrong.", ephemeral=True)


@client.tree.command(name="ping", description="Check if bot is alive")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("Pong!")


if __name__ == "__main__":
    logging.info("Starting bot...")
    client.run(TOKEN)