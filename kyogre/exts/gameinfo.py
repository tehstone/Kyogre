import copy

import discord
from discord.ext import commands

from kyogre import utils, pokemon_emoji
from kyogre.exts.db.kyogredb import QuestTable
from kyogre.exts.pokemon import Pokemon


class GameInfo(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.failed_react = '❌'
        self.success_react = '✅'
        self.info_types = ['raid', 'research']
        self.default_type_dict = {"channel_id": None, "message_ids": []}

    @commands.command(hidden=True, name='setinfochannel', aliases=['sic'])
    @commands.has_permissions(manage_guild=True)
    async def _set_info_channel(self, ctx, info_type: str):
        if info_type not in self.info_types:
            error_response = await ctx.send(embed=discord.Embed(
                colour=discord.Colour.red(),
                description=f"Invalid info type {info_type}. "
                            f"Please try again with one of: {', '.join(self.info_types)}"))
            return await utils.sleep_and_cleanup([ctx.message, error_response], 10)
        ic_dict = self.bot.guild_dict[ctx.guild.id]['configure_dict']['settings'].setdefault('info_channels', {})
        if info_type in ic_dict and ic_dict[info_type]["channel_id"] == ctx.channel.id:
            ic_dict[info_type] = copy.deepcopy(self.default_type_dict)
            await ctx.channel.send(f'{ctx.channel.mention} no longer {info_type} list channel.', delete_after=10)
        else:
            ic_dict[info_type] = copy.deepcopy(self.default_type_dict)
            ic_dict[info_type]["channel_id"] = ctx.channel.id
            await ctx.channel.send(f'{ctx.channel.mention} set as {info_type} list channel.', delete_after=10)
        return await ctx.message.add_reaction(self.bot.success_react)

    async def update_info_channel(self, ctx, info_type):
        ic_dict = self.bot.guild_dict[ctx.guild.id]['configure_dict']['settings'].setdefault('info_channels', {})
        if info_type not in ic_dict:
            return
        info_channel = self.bot.get_channel(ic_dict[info_type]["channel_id"])
        if not info_channel:
            return
        for mid in ic_dict[info_type]["message_ids"]:
            try:
                message = await info_channel.fetch_message(mid)
                await message.delete()
            except:
                pass
        if info_type == "research":
            mid = await self._update_research_info(info_channel)
            ic_dict[info_type]["message_ids"].append(mid)
            return
        elif info_type == "raid":
            pass
        else:
            return

    @commands.command(hidden=True, name='testinfo', aliases=['ti'])
    async def test_info(self, ctx):
        return await self._update_research_info(ctx.channel)

    async def _update_research_info(self, channel):
        query = QuestTable.select().execute()
        research_tasks = [d for d in query]
        current_field_str = ""
        m_embed = discord.Embed(colour=discord.Colour.dark_blue())
        for task in research_tasks:
            this_task = ""
            if len(current_field_str) > 1900:
                break
            reward_pool = task.reward_pool
            if len(reward_pool["encounters"]) == 0:
                continue
            this_task += f"\n**{task.name}**"
            for pkmn in reward_pool["encounters"]:
                pokemon = Pokemon.get_pokemon(self.bot, pkmn)
                if not pokemon:
                    continue
                p_emoji = pokemon_emoji.get_pokemon_emoji(pokemon.emoji_name)
                lower_cp = pokemon.get_cp_by_level(15, 10, 10, 10)
                upper_cp = pokemon.get_cp_by_level(15, 15, 15, 15)
                this_task += f"\n\u2001{p_emoji} {pokemon.name} ({lower_cp}-{upper_cp})"
            if len(current_field_str) + len(this_task) > 1024:
                m_embed.add_field(name=self.bot.empty_str, value=current_field_str, inline=False)
                current_field_str = this_task
            else:
                current_field_str += this_task
        m_embed.add_field(name=self.bot.empty_str, value=current_field_str, inline=False)
        new_message = await channel.send(embed=m_embed)
        return new_message.id


def setup(bot):
    bot.add_cog(GameInfo(bot))
