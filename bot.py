from __future__ import annotations

import logging
from typing import Any

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

from config import load_config
from db import Database
from futbin_client import FutbinClient
from tracker_service import TrackerService


def coins(value: int | None) -> str:
    return "n/a" if not value else f"{value:,}"


def alert_emoji(change: float) -> str:
    if change > 0:
        return "📈"
    if change < 0:
        return "📉"
    return "➖"


config = load_config()
logging.basicConfig(
    level=getattr(logging, config.log_level, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("fc26-tradepilot")

if not config.discord_token:
    raise RuntimeError("Brak DISCORD_TOKEN w .env")

intents = discord.Intents.default()
intents.message_content = True

db = Database(config.database_path)
futbin = FutbinClient(config.futbin_request_timeout_seconds, config.futbin_max_retries, logger)
service = TrackerService(db, futbin, config, logger)


class TradePilotBot(commands.Bot):
    async def setup_hook(self) -> None:
        await db.init()

        if config.discord_guild_id:
            guild_obj = discord.Object(id=int(config.discord_guild_id))
            self.tree.clear_commands(guild=guild_obj)
            self.tree.copy_global_to(guild=guild_obj)
            synced = await self.tree.sync(guild=guild_obj)
            logger.info("Synced %s guild commands: %s", len(synced), [c.name for c in synced])
        else:
            synced = await self.tree.sync()
            logger.info("Synced %s global commands: %s", len(synced), [c.name for c in synced])

        if not tracking_loop.is_running():
            tracking_loop.start()


bot = TradePilotBot(command_prefix="!", intents=intents)


async def send_embed_to_alert_target(embed: discord.Embed) -> None:
    if config.discord_webhook_url:
        async with aiohttp.ClientSession() as session:
            await session.post(config.discord_webhook_url, json={"embeds": [embed.to_dict()]})
        return

    if not config.discord_alert_channel_id:
        return

    channel = bot.get_channel(int(config.discord_alert_channel_id))
    if channel is None:
        channel = await bot.fetch_channel(int(config.discord_alert_channel_id))
    if isinstance(channel, (discord.TextChannel, discord.Thread)):
        await channel.send(embed=embed)


async def notify_price_alert(data: dict[str, Any]) -> None:
    sig = data["signal_type"].upper()
    embed = discord.Embed(
        title=f"{alert_emoji(data['change_percent'])} {data['player_name']} {sig}",
        description=f"Platform: **{data['platform'].upper()}** | source: **{data['source']}**",
        color=0x1DB954 if data["change_percent"] >= 0 else 0xFF4D4D,
    )
    embed.add_field(name="Previous", value=coins(data["previous_price"]), inline=True)
    embed.add_field(name="Current", value=coins(data["current_price"]), inline=True)
    embed.add_field(name="Change", value=f"{data['change_percent']:.2f}%", inline=True)
    embed.set_footer(text="FC26 TradePilot")
    await send_embed_to_alert_target(embed)


async def send_market_summary(title: str, rows: list[str]) -> None:
    embed = discord.Embed(title=title, description="\n".join(rows) if rows else "No data", color=0xF5B400)
    await send_embed_to_alert_target(embed)


@bot.event
async def on_ready() -> None:
    logger.info("Bot online as %s", bot.user)


@tasks.loop(minutes=config.track_interval_minutes)
async def tracking_loop() -> None:
    await service.run_cycle(notify_price_alert, send_market_summary)


@tracking_loop.before_loop
async def before_tracking_loop() -> None:
    await bot.wait_until_ready()


@bot.tree.command(name="price", description="Pokazuje aktualna cene zawodnika")
@app_commands.describe(player="Nazwa zawodnika")
async def price_command(interaction: discord.Interaction, player: str) -> None:
    await interaction.response.defer()
    try:
        data = await service.get_price(player)
        trend = await service.build_trend(data["player"]["id"])
        embed = discord.Embed(
            title=f"💰 {data['player']['name']} ({data['player']['rating'] or '?'})",
            description=f"Rarity: {data['player']['rarity']} | source: {data['prices']['source']}",
            color=0x2B87FF,
        )
        embed.add_field(name="PS", value=coins(data["prices"]["ps"]), inline=True)
        embed.add_field(name="XBOX", value=coins(data["prices"]["xbox"]), inline=True)
        embed.add_field(name="PC", value=coins(data["prices"]["pc"]), inline=True)
        embed.add_field(name="24h", value=f"{trend['change24h']:.2f}%", inline=True)
        embed.add_field(name="7d", value=f"{trend['change7d']:.2f}%", inline=True)
        embed.add_field(name="Trend", value=trend["trend"], inline=True)
        await interaction.followup.send(embed=embed)
    except Exception as exc:
        await interaction.followup.send(f"Blad price: {exc}")


@bot.tree.command(name="track", description="Dodaje karte do watchlisty")
@app_commands.describe(player="Nazwa zawodnika", threshold="Procent alertu, np 5")
async def track_command(interaction: discord.Interaction, player: str, threshold: float | None = None) -> None:
    await interaction.response.defer(ephemeral=True)
    try:
        found = await service.track_player(player, threshold)
        await interaction.followup.send(
            f"✅ Dodano: {found['name']} (ID {found['id']}) | threshold: {threshold or config.alert_threshold_percent}%",
            ephemeral=True,
        )
    except Exception as exc:
        await interaction.followup.send(f"Blad track: {exc}", ephemeral=True)


@bot.tree.command(name="untrack", description="Usuwa karte z watchlisty")
@app_commands.describe(player="Nazwa zawodnika albo FUTBIN ID")
async def untrack_command(interaction: discord.Interaction, player: str) -> None:
    removed = await service.untrack_player(player)
    if not removed:
        await interaction.response.send_message("Nie znaleziono na watchliscie", ephemeral=True)
        return
    await interaction.response.send_message(f"🗑️ Usunieto: {removed['player_name']}", ephemeral=True)


@bot.tree.command(name="alerts", description="Pokazuje ostatnie alerty")
async def alerts_command(interaction: discord.Interaction) -> None:
    rows = await service.get_alerts()
    lines = [f"• {r['player_name']} | {r['alert_type'].upper()} | {r['message']}" for r in rows]
    await interaction.response.send_message("\n".join(lines) if lines else "Brak alertow", ephemeral=True)


@bot.tree.command(name="portfolio", description="Pokazuje portfolio")
async def portfolio_command(interaction: discord.Interaction) -> None:
    rows = await service.get_portfolio()
    lines = [f"• {r['player_name']} x{r['quantity']} @ {coins(r['buy_price'])} ({r['platform']})" for r in rows]
    await interaction.response.send_message("\n".join(lines) if lines else "Portfolio puste", ephemeral=True)


@bot.tree.command(name="toprisers", description="Top wzrosty")
async def toprisers_command(interaction: discord.Interaction) -> None:
    rows = await service.top_movers("risers", 10)
    lines = [f"{i+1}. {r['player_name']}: +{r['pct']:.2f}%" for i, r in enumerate(rows)]
    await interaction.response.send_message("\n".join(lines) if lines else "Za malo danych", ephemeral=True)


@bot.tree.command(name="topfallers", description="Top spadki")
async def topfallers_command(interaction: discord.Interaction) -> None:
    rows = await service.top_movers("fallers", 10)
    lines = [f"{i+1}. {r['player_name']}: {r['pct']:.2f}%" for i, r in enumerate(rows)]
    await interaction.response.send_message("\n".join(lines) if lines else "Za malo danych", ephemeral=True)


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
    logger.exception("App command error: %s", error)
    msg = "Wystapil blad komendy. Sprawdz logi bota."
    if interaction.response.is_done():
        await interaction.followup.send(msg, ephemeral=True)
    else:
        await interaction.response.send_message(msg, ephemeral=True)


if __name__ == "__main__":
    bot.run(config.discord_token)
