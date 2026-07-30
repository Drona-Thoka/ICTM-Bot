import os
import discord
from discord import app_commands
import aiohttp
from dotenv import load_dotenv
from io import BytesIO
import asyncio
import re

# ---------- Matplotlib with LaTeX ----------
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend
import matplotlib.pyplot as plt

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

# ---------- Helpers ----------
def clean_latex(text: str) -> str:
    """Clean up common OCR mistakes and escape #."""
    text = text.replace(r'\texbf', r'\textbf')
    text = text.replace(r'\texit', r'\textit')
    text = text.replace('#', r'\#')      # escape # for LaTeX
    text = text.replace(': :', ':')
    return text

async def render_latex_local(latex_str: str) -> BytesIO:
    """Render LaTeX to PNG using matplotlib (local)."""
    latex_str = clean_latex(latex_str)
    fig, ax = plt.subplots(figsize=(12, 8))
    ax.axis('off')
    plt.rc('text', usetex=True)
    plt.rc('font', family='serif')
    # Wrap in displaymath for proper rendering
    tex = f"\\begin{{displaymath}}\n{latex_str}\n\\end{{displaymath}}"
    ax.text(0.5, 0.5, tex, size=16, ha='center', va='center', transform=ax.transAxes)
    buf = BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight', pad_inches=0.5, dpi=150)
    plt.close(fig)
    buf.seek(0)
    return buf

async def render_latex(latex_str: str) -> BytesIO:
    """Try local render; if fails, fall back to raw text (no image)."""
    try:
        return await render_latex_local(latex_str)
    except Exception as e:
        print(f"Local LaTeX render failed: {e}")
        # Raise so the command can fall back to raw text
        raise

async def api_get(endpoint, params=None):
    async with aiohttp.ClientSession() as session:
        url = f"{API_BASE}{endpoint}"
        try:
            async with session.get(url, params=params, timeout=8) as resp:
                if resp.status == 200:
                    return await resp.json()
                return None
        except asyncio.TimeoutError:
            return None
        except Exception:
            return None

async def api_post(endpoint, data=None):
    async with aiohttp.ClientSession() as session:
        url = f"{API_BASE}{endpoint}"
        try:
            async with session.post(url, json=data, timeout=8) as resp:
                if resp.status in (200, 201):
                    return await resp.json()
                return None
        except asyncio.TimeoutError:
            return None
        except Exception:
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

    # Build LaTeX string
    lines = []
    lines.append(f"\\textbf{{{data['competition_name']} - Problem {data['problem_id']}}}")
    lines.append("")  # blank line
    lines.append(data['problem_text'])
    if data.get('choices'):
        lines.append("")  # blank line
        lines.append("\\textbf{Choices:}")
        for letter, value in data['choices'].items():
            lines.append(f"{letter}: {value}")
    latex_str = "\n".join(lines)

    try:
        img_buf = await render_latex(latex_str)
        file = discord.File(img_buf, filename="problem.png")
        await interaction.followup.send(file=file)
        await interaction.followup.send("Type `/answer YOUR_ANSWER` to check.")
    except Exception as e:
        # Fallback: send raw LaTeX in a code block
        await interaction.followup.send(
            f"⚠️ **Could not render image.** Here's the raw problem:\n```latex\n{latex_str}\n```"
        )

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