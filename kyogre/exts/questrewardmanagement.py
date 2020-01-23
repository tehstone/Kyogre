import json
import re

from discord.ext import commands

from kyogre.exts.pokemon import Pokemon
from kyogre import utils, checks
from kyogre.exts.db.kyogredb import QuestTable


class QuestRewardManagement(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.guild_dict = bot.guild_dict

    @commands.group(name="quest")
    async def _quest(self, ctx):
        """Quest data management command"""
        if ctx.invoked_subcommand == None:
            raise commands.BadArgument()


    @_quest.command(name="info", aliases=["lookup", "get", "find"])
    @checks.allowresearchreport()
    async def _quest_info(self, ctx, *, name):
        """Look up a quest by name, returning the quest ID and details
        
        Usage: !quest info <name>"""
        channel = ctx.channel
        quest = await self.get_quest(ctx, name)
        if not quest:
            return await channel.send("Unable to find quest by that name")
        await channel.send(self.format_quest_info(quest))


    @_quest.command(name="add")
    @commands.has_permissions(manage_guild=True)
    async def _quest_add(self, ctx, *, info):
        """Add a new quest and associated reward pool, separated by comma.
        
        Usage: !quest add <name>[, reward_pool]
        
        Reward pool should be provided as a JSON string. If not provided, an empty default will be used."""
        channel = ctx.channel
        name, pool = None, None
        if ',' in info:
            name, pool = info.split(',', 1)
        else:
            name = info
        if '{' in name:
            return await channel.send('Please check the format of your message and try again.\
                                       The name and reward pool should be separated by a comma')
        if pool:
            try:
                pool = json.loads(pool)
            except ValueError:
                return await channel.send("Error: provided reward pool is not a valid JSON string")
        try:
            new_quest = QuestTable.create(name=name, reward_pool=pool if pool else {})
        except:
            return await channel.send("Unable to add record.\
                                       Please ensure the quest does not already exist with the find command.")
        await channel.send(f"Successfully added new quest: {new_quest.name} ({new_quest.id})")


    @_quest.command(name="remove", aliases=["rm", "delete", "del", "rem"])
    @commands.has_permissions(manage_guild=True)
    async def _quest_remove(self, ctx, id):
        """Remove a quest by its ID
        
        Usage: !quest remove <id>"""
        channel = ctx.channel
        try:
            deleted = QuestTable.delete().where(QuestTable.id == id).execute()
        except:
            deleted = False
        if deleted:
            return await channel.send("Successfully deleted record")
        return await channel.send("Unable to delete record")


    def format_quest_info(self, quest):
        pool = quest.reward_pool
        output = f"{quest.name} ({quest.id})\n"
        encounters = pool.get('encounters', [])
        stardust = pool.get('stardust', [])
        xp = pool.get('xp', [])
        items = pool.get('items', {})
        if encounters:
            encounters = [str(e) for e in encounters]
            output += f"\nEncounters: {', '.join(encounters).title()}"
        if stardust:
            stardust = [str(s) for s in stardust]
            output += f"\nStardust: {', '.join(stardust)}"
        if xp:
            xp = [str(x) for x in xp]
            output += f"\nExperience: {', '.join(xp)}"
        if items:
            output += "\nItems:"
            for name, quantities in items.items():
                output += f"\n\t{name.title()}: {quantities[0] if len(quantities) == 1 else str(quantities[0]) + ' - ' + str(quantities[-1])}"
        return output


    @commands.group(name="rewards")
    @commands.has_permissions(manage_guild=True)
    async def _rewards(self, ctx):
        """Quest reward pool data management command"""
        if not ctx.invoked_subcommand:
            raise commands.BadArgument()


    @_rewards.command(name="add")
    async def _rewards_add(self, ctx, *, info):
        """Adds a reward to reward pool for a given quest using provided comma-separated values.
        
        Usage: !rewards add <ID>, <type>, <value>
        
        ID must correspond to a valid db entry.
        If type is not encounters, stardust, or xp, it will be assumed to be an item."""
        channel = ctx.channel
        try:
            reward_id, reward_type, value = re.split(r',', info)
            reward_id = int(reward_id.strip())
            reward_type = reward_type.lower().strip()
            value = value.strip()
        except:
            return await channel.send("Error parsing input. Please check the format and try again")
        try:
            quest = QuestTable[reward_id]
        except:
            return await channel.send(f"Unable to get quest with id {reward_id}")
        pool = quest.reward_pool
        if reward_type.startswith("encounter"):
            pokemon = Pokemon.get_pokemon(self.bot, value)
            if pokemon:
                pool.setdefault("encounters", []).append(pokemon.name.lower())
        else:
            if not value.isnumeric():
                return await channel.send("Value must be a numeric quantity")
            if reward_type == "stardust":
                pool.setdefault("stardust", []).append(int(value))
            elif reward_type == "xp":
                pool.setdefault("xp", []).append(int(value))
            else:
                pool.setdefault("items", {}).setdefault(reward_type, []).append(int(value))
        quest.reward_pool = pool
        quest.save()
        await channel.send("Successfully added reward to pool")


    @_rewards.command(name="remove", aliases=["rm", "delete", "del", "rem"])
    async def _rewards_remove(self, ctx, *, info):
        """Removes a reward to reward pool for a given quest using provided comma-separated values.
        
        Usage: !rewards remove <ID>, <reward_type>, <value>
        
        ID must correspond to a valid db entry.
        If reward_type is not encounters, stardust, or xp, it will be assumed to be an item."""
        channel = ctx.channel
        try:
            reward_id, reward_type, value = re.split(r',', info)
            reward_id = int(reward_id)
            reward_type = reward_type.lower()
        except:
            return await channel.send("Error parsing input. Please check the format and try again")
        try:
            quest = QuestTable[reward_id]
        except:
            return await channel.send(f"Unable to get quest with reward_id {reward_id}")
        pool = quest.reward_pool
        if reward_type.startswith("encounter"):
            encounters = [x.lower() for x in pool["encounters"]]
            pokemon = Pokemon.get_pokemon(self.bot, value)
            name = pokemon.name.lower()
            if pokemon:
                try:
                    encounters.remove(name)
                except:
                    return await channel.send(f"Unable to remove {value}")
            pool["encounters"] = encounters
        else:
            if not value.isnumeric():
                return await channel.send("Value must be a numeric quantity")
            try:
                if reward_type == "stardust":
                    pool["stardust"].remove(int(value))
                elif reward_type == "xp":
                    pool["xp"].remove(int(value))
                else:
                    pool["items"][reward_type].remove(int(value))
                    if len(pool["items"][reward_type]) == 0:
                        del pool["items"][reward_type]
            except:
                return await channel.send(f"Unable to remove {value}")
        quest.reward_pool = pool
        quest.save()
        await channel.send("Successfully removed reward from pool")

    async def get_quest(self, ctx, name):
        channel = ctx.channel
        author = ctx.message.author.id
        return await self.get_quest_v(channel, author, name)

    async def get_quest_v(self, channel, author, name):
        """gets a quest by name or id"""
        if not name:
            return
        quest_id = None
        if str(name).isnumeric():
            quest_id = int(name)
        try:
            query = QuestTable.select()
            if quest_id is not None:
                query = query.where(QuestTable.id == quest_id)
            query = query.execute()
            result = [d for d in query]
        except:
            return await channel.send("No quest data available!")
        if quest_id is not None:
            return None if not result else result[0]
        quest_names = [q.name.lower() for q in result]
        if name.lower() not in quest_names:
            candidates = utils.get_match(quest_names, name, score_cutoff=70, isPartial=True, limit=20)
            if candidates[0] is None:
                return None
            name = await utils.prompt_match_result(self.bot, channel, author, name, candidates)
        return next((q for q in result if q.name is not None and q.name.lower() == name.lower()), None)

    async def prompt_reward(self, ctx, quest, reward_type=None):
        channel = ctx.channel
        author = ctx.message.author.id
        return await self.prompt_reward_v(channel, author, quest, reward_type)

    async def prompt_reward_v(self, channel, author, quest, reward_type=None):
        """prompts user for reward info selection using quest's reward pool
        can optionally specify a start point with reward_type"""
        if not quest or not quest.reward_pool:
            return
        if reward_type:
            if reward_type not in quest.reward_pool:
                raise ValueError("Starting point provided is invalid")
        else:
            candidates = [k for k, v in quest.reward_pool.items() if len(v) > 0]
            if len(candidates) == 0:
                return
            elif len(candidates) == 1:
                reward_type = candidates[0]
            else:
                prompt = "Please select a reward type:"
                reward_type = await utils.ask_list(self.bot, prompt, channel, candidates, user_list=author)
        if not reward_type:
            return
        target_pool = quest.reward_pool[reward_type]
        # handle encounters
        if reward_type == "encounters":
            any_encounter = f"{' or '.join([p.title() for p in target_pool])} Encounter"
            if len(target_pool) > 1:
                candidates = [f"{p.title()} Encounter" for p in target_pool]
                candidates.append(any_encounter)
                prompt = "If you know which encounter this task gives, please select it below. \
                          Otherwise select the last option"
                return await utils.ask_list(self.bot, prompt, channel, candidates, user_list=author)
            else:
                return any_encounter
        # handle items
        if reward_type == "items":
            if len(target_pool) == 1:
                tp_key = list(target_pool.keys())[0]
                return f"{target_pool[tp_key][0]} {tp_key}"
            else:
                candidates = [k for k in target_pool]
                prompt = "Please select an item:"
                reward_type = await utils.ask_list(self.bot, prompt, channel, candidates, user_list=author)
                if not reward_type:
                    return
                target_pool = target_pool[reward_type]
        if len(target_pool) == 1:
            return f"{target_pool[0]} {reward_type.title()}"
        else:
            candidates = [str(q) for q in target_pool]
            prompt = "Please select the correct quantity:"
            quantity = await utils.ask_list(self.bot, prompt, channel, candidates, user_list=author)
            if not quantity:
                return
            return f"{quantity} {reward_type.title()}"

    async def check_reward(self, ctx, quest, reward):
        complete_pool = []
        reward = reward.lower().strip()
        if reward == 'encounter':
            any_encounter = f"{' or '.join([p.title() for p in quest.reward_pool['encounters']])} Encounter"
            complete_pool.append(any_encounter)
        elif 'stardust' in quest.reward_pool and reward in ['stardust', 'dust']:
            if len(quest.reward_pool['stardust']) > 0:
                r = f"{quest.reward_pool['stardust'][0]} stardust"
                complete_pool.append(r)
        else:
            if 'encounters' in quest.reward_pool:
                for e in quest.reward_pool['encounters']:
                    complete_pool.append(e)
            if 'items' in quest.reward_pool:
                for item in quest.reward_pool['items']:
                    r = f"{quest.reward_pool['items'][item][0]} {item}"
                    complete_pool.append(r)
        candidates = utils.get_match(complete_pool, reward.strip(), score_cutoff=70, isPartial=True, limit=5)
        if candidates[0] is None:
            return None
        reward = await utils.prompt_match_result(self.bot, ctx.channel, ctx.message.author.id, reward, candidates)
        return reward


def setup(bot):
    bot.add_cog(QuestRewardManagement(bot))
