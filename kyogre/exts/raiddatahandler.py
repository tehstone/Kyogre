import json
import re
import requests
from bs4 import BeautifulSoup
from discord.ext import commands

from kyogre import checks
from kyogre.exts.pokemon import Pokemon


class RaidDataHandler(commands.Cog):
    """Raid Data Loading and Saving Test Cog."""

    def __init__(self, bot):
        self.bot = bot
        self.raid_info = bot.raid_info

    def __local_check(self, ctx):
        return checks.is_owner_check(ctx) or checks.is_dev_check(ctx)

    @commands.group(invoke_without_command=True, aliases=['rd'])
    @commands.has_permissions(manage_roles=True)
    async def raiddata(self, ctx, level=None):
        """Show all raid Pokemon, showing only the raid level if provided."""
        data = []
        title = None
        if level:
            title = f"Pokemon Data for Raid {level}"
            try:
                for pkmn in self.raid_info['raid_eggs'][level]["pokemon"]:
                    pkmn = Pokemon.get_pokemon(self.bot, pkmn)
                    data.append(f"#{pkmn.id} - {pkmn.name}")
            except KeyError:
                return await ctx.send('Invalid raid level specified.')
            except:
                return await ctx.send('Error processing command')
        else:
            title = f"Pokemon Data for All Raids"
            data = []
            for pkmnlvl, vals in self.raid_info['raid_eggs'].items():
                if not vals["pokemon"]:
                    continue
                leveldata = []
                try:
                    for pkmn in vals["pokemon"]:
                        pkmn = Pokemon.get_pokemon(self.bot, pkmn)
                        leveldata.append(f"#{pkmn.id} - {pkmn.name}")
                except:
                    return await ctx.send('Error processing command')
                leveldata = '\n'.join(leveldata)
                data.append(f"**Raid {pkmnlvl} Pokemon**\n{leveldata}\n")
        data_str = '\n'.join(data)
        await ctx.send(f"**{title}**\n{data_str}")

    def in_list(self, pkmn):
        for pkmnlvl, vals in self.raid_info['raid_eggs'].items():
            if pkmn.name in vals["pokemon"]:
                return pkmnlvl
        return None

    @raiddata.command(name='remove', aliases=['rm', 'del', 'delete'])
    async def remove_rd(self, ctx, *, raid_pokemon=None):
        """Removes all pokemon provided as comma-separated arguments from the raid data.

        Example: !raiddata remove Mr Mime, Jynx, Alolan Raichu
        """
        results = []
        # remove level if erroneously provided
        raid_pokemon = re.sub(r'^\d+\s+', '', raid_pokemon)
        raid_pokemon = re.split(r'\s*,\s*', raid_pokemon)
        for pokemon in raid_pokemon:
            pkmn = Pokemon.get_pokemon(self.bot, pokemon)
            if not pkmn:
                self.bot.help_logger.info(f"User: {ctx.author.name}, channel: {ctx.channel}, error: Invalid pokemon name: {pokemon}.")
                return await ctx.send('Invalid Pokemon Name')
            hit_key = []
            name = pkmn.name.lower()
            for k, v in self.raid_info['raid_eggs'].items():
                if name in v['pokemon']:
                    hit_key.append(k)
                    self.raid_info['raid_eggs'][k]['pokemon'].remove(name)
            if hit_key:
                hits = '\n'.join(hit_key)
                result_text = f"#{pkmn.id} {pkmn.name} from {hits}"
            else:
                result_text = f"#{pkmn.id} {pkmn.name} not found in raid data"
            results.append(result_text)
        results_st = '\n'.join(results)
        await ctx.send(f"**Pokemon removed from raid data**\n{results_st}")

    def add_raid_pkmn(self, level, raid_pokemon):
        """Add raid pokemon to relevant level."""
        added = []
        failed = []
        raid_pokemon = re.split(r'\s*,\s*', raid_pokemon)
        raid_list = self.raid_info['raid_eggs'][level]['pokemon']
        for pokemon in raid_pokemon:
            pkmn = Pokemon.get_pokemon(self.bot, pokemon)
            if not pkmn:
                failed.append(pokemon)
                continue
            in_level = self.in_list(pkmn)
            name = pkmn.name.lower()
            if in_level:
                if in_level == level:
                    continue
                self.raid_info['raid_eggs'][in_level]['pokemon'].remove(name)
            raid_list.append(name)
            added.append(f"#{pkmn.id} {pkmn.name}")
        return (added, failed)

    @raiddata.command(name='add')
    async def add_rd(self, ctx, level, *, raid_pokemon=None):
        """Adds all pokemon provided as arguments to the specified raid
        level in the raid data.

        Example: !raiddata add 3 Mr Mime, Jynx, Alolan Raichu
        """

        if level not in self.raid_info['raid_eggs'].keys():
            self.bot.help_logger.info(f"User: {ctx.author.name}, channel: {ctx.channel}, error: Invalid raid level.")
            return await ctx.send("Invalid raid level specified.")

        added, failed = self.add_raid_pkmn(level, raid_pokemon)

        result = []

        if added:
            result.append(
                f"**{len(added)} Pokemon added to Level {level} Raids:**\n"
                f"{', '.join(added)}")

        if failed:
            result.append(
                f"**{len(failed)} entries failed to be added:**\n"
                f"{', '.join(failed)}")

        await ctx.send('\n'.join(result))

    @raiddata.command(name='replace', aliases=['rp'])
    async def replace_rd(self, ctx, level, *, raid_pokemon=None):
        """All pokemon provided will replace the specified raid level
        in the raid data.

        Example: !raiddata replace 3 Mr Mime, Jynx, Alolan Raichu
        """
        return await self._replace_rd(ctx, level, raid_pokemon)

    async def _replace_rd(self, ctx, level, raid_pokemon, message=True):
        if level not in self.raid_info['raid_eggs'].keys():
            self.bot.help_logger.info(f"User: {ctx.author.name}, channel: {ctx.channel}, error: Invalid raid level.")
            return await ctx.send("Invalid raid level specified.")
        if not raid_pokemon:
            self.bot.help_logger.info(f"User: {ctx.author.name}, channel: {ctx.channel}, error: No Pokemon provided.")
            return await ctx.send("No pokemon provided.")
        old_data = tuple(self.raid_info['raid_eggs'][level]['pokemon'])
        self.raid_info['raid_eggs'][level]['pokemon'] = []
        added, failed = self.add_raid_pkmn(level, raid_pokemon)
        if not added:
            self.raid_info['raid_eggs'][level]['pokemon'].extend(old_data)

        result = []

        if added:
            result.append(
                f"**{len(added)} Pokemon added to Level {level} Raids:**\n"
                f"{', '.join(added)}")

        if failed:
            result.append(
                f"**{len(failed)} entries failed to be added:**\n"
                f"{', '.join(failed)}")
        if message:
            await ctx.send('\n'.join(result))
        else:
            return '\n'.join(result)

    @raiddata.command(name='save', aliases=['commit'])
    async def save_rd(self, ctx):
        """Saves the current raid data state to the json file.
        Must be run after any changes made to raid data with the add/remove/replace commands."""
        return await self._save_rd(ctx)

    async def _save_rd(self, ctx):
        for pkmn_lvl in self.raid_info['raid_eggs']:
            data = self.raid_info['raid_eggs'][pkmn_lvl]["pokemon"]
            pkmn_names = [Pokemon.get_pokemon(self.bot, p).name.lower() for p in data]
            self.raid_info['raid_eggs'][pkmn_lvl]["pokemon"] = pkmn_names

        with open(ctx.bot.raid_json_path, 'w') as fd:
            json.dump(self.raid_info, fd, indent=4)
        return await ctx.message.add_reaction('\u2705')

    @raiddata.command(name='populate', aliases=['pop'])
    async def populate_rd_from_tsr(self, ctx):
        """Pulls the current raid boss list from the Silph Road website and updates Kyogre.

        Example: `!raiddata pop`
        """
        def walk_siblings(sib):
            try:
                # We've encountered another level header. Exit this loop.
                if sib.attrs["class"] == ['raid-boss-tier-wrap']:
                    return False
            except:
                pass
            boss = None
            try:
                boss = sib.find('div', attrs={'class': 'pokemonOption'})
            except:
                pass
            if boss:
                poke = boss.attrs['data-pokemon-slug']
                if '-' in poke:
                    poke = poke.replace('alola', 'alolan')
                    poke_split = poke.split('-')[::-1]
                    poke = ' '.join(poke_split)
                return poke

        task_page = "https://thesilphroad.com/raid-bosses"
        await ctx.send(f"Connecting to <{task_page}> to update raid boss list.")
        page = requests.get(task_page)
        soup = BeautifulSoup(page.content, 'html.parser')
        # This will pull all tier headers to walk through.
        # The headers are at the same hierarchy level as the actual raids
        # so walking through siblings will encounter both.
        tiers = soup.findAll('div', attrs={'class': 'raid-boss-tier-wrap'})
        messages = []
        for tier in tiers:
            tier_str = tier.find('h4')
            if 'EX' in tier_str.string:
                level = 'EX'
            else:
                level = tier_str.string.split(' ')[1]
            raid_pokemon = []
            for sibling in tier.next_siblings:
                result = walk_siblings(sibling)
                if result:
                    result = result.replace('galar', 'galarian')
                    raid_pokemon.append(result)
                # If result is false, it means we encountered a header.
                # Break the inner loop and save the current Pokemon list
                # to the current level.
                if result == False:
                    break
            messages.append(await self._replace_rd(ctx, level, ', '.join(raid_pokemon), False))
        await self._save_rd(ctx)
        await ctx.send('\n'.join(messages))
        await ctx.send("Finished updating raid boss list.")
        await ctx.invoke(self.bot.get_command('update_rbl'))


def setup(bot):
    bot.add_cog(RaidDataHandler(bot))
