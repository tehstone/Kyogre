import asyncio
import copy
import datetime
import re
import textwrap
import time

import discord
from discord.ext import commands

from kyogre import checks, utils
from kyogre.exts.pokemon import Pokemon

from kyogre.exts.db.kyogredb import GuildTable, ResearchTable, TrainerTable, TrainerReportRelation


class ResearchCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(aliases=['res'], brief="Report a Field Research task")
    @checks.allowresearchreport()
    async def research(self, ctx, *, details=None):
        """**Usage**: `!research [pokestop name, quest]`
        Use just the command to start a guided session.
        Or provide Pokestop name and quest info to complete the report."""
        message = ctx.message
        channel = message.channel
        author = message.author
        guild = message.guild
        timestamp = (message.created_at + datetime.timedelta(
            hours=self.bot.guild_dict[message.channel.guild.id]['configure_dict']['settings']['offset']))
        to_midnight = 24*60*60 - (timestamp-timestamp.replace(hour=0, minute=0, second=0, microsecond=0)).seconds
        error = False
        utilities_cog = self.bot.cogs.get('Utilities')
        loc_url = utilities_cog.create_gmaps_query("", message.channel, type="research")
        research_embed = discord.Embed(
            colour=message.guild.me.colour)\
            .set_thumbnail(
            url='https://raw.githubusercontent.com/klords/Kyogre/master/images/misc/field-research.png?cache=0')
        research_embed.set_footer(text='Reported by {author} - {timestamp}'
                                  .format(author=author.display_name,
                                          timestamp=timestamp.strftime('%I:%M %p (%H:%M)')),
                                  icon_url=author.avatar_url_as(format=None, static_format='jpg', size=32))
        utils_cog = self.bot.cogs.get('Utilities')
        regions = utils_cog.get_channel_regions(channel, 'research')
        location_matching_cog = self.bot.cogs.get('LocationMatching')
        stops = location_matching_cog.get_stops(guild.id, regions)
        location, quest, reward = None, None, None
        questrewardmanagement_cog = self.bot.cogs.get('QuestRewardManagement')
        if not questrewardmanagement_cog:
            return await channel.send(embed=discord.Embed(colour=discord.Colour.red(),
                                                          description="Quest data is not loaded for this server."))
        while True:
            if details:
                research_split = details.rsplit(",", 2)
                if len(research_split) == 2:
                    location, quest_name = research_split
                    reward = None
                elif len(research_split) == 3:
                    location, quest_name, reward = research_split
                else:
                    error = "entered an incorrect amount of arguments.\n\n" \
                            "Usage: **!research** or **!research <pokestop>, <quest>**"
                    break
                if stops:
                    stop = await location_matching_cog.match_prompt(channel, author.id, location, stops)
                    if not stop:
                        swap_msg = await channel.send(embed=discord.Embed(
                            colour=discord.Colour.red(),
                            description=f"I couldn't find a pokestop named '**{location}**'. "
                            f"Perhaps you have reversed the order of your report?\n\n"
                            f"Looking up stop with name '**{quest_name.strip()}**'"))
                        quest_name, location = research_split
                        stop = await location_matching_cog.match_prompt(channel, author.id, location.strip(), stops)
                        if not stop:
                            await swap_msg.delete()
                            self.bot.help_logger.info(f"User: {ctx.author.name}, channel: {ctx.channel}, error: No Pokestop found with name: {location.strip()}.")
                            err_msg = await channel.send(
                                embed=discord.Embed(colour=discord.Colour.red(),
                                                    description=f"No pokestop found with name '**{location.strip()}**' "
                                                    f"either. Try reporting again using the exact pokestop name!"))
                            return await utils.sleep_and_cleanup([err_msg], 15)
                        await swap_msg.delete()
                    if self.get_existing_research(guild, stop):
                        return await channel.send(embed=discord.Embed(
                            colour=discord.Colour.red(),
                            description=f"A quest has already been reported for {stop.name}"))
                    location = stop.name
                    loc_url = stop.maps_url
                    regions = [stop.region]
                else:
                    loc_url = utilities_cog.create_gmaps_query(location, channel, type="research")
                location = location.replace(loc_url, "").strip()
                quest = await questrewardmanagement_cog.get_quest(ctx, quest_name.strip())
                if not quest:
                    self.bot.help_logger.info(f"User: {ctx.author.name}, channel: {ctx.channel}, error: No quest found with name: {quest_name}.")
                    return await channel.send(embed=discord.Embed(
                        colour=discord.Colour.red(),
                        description=f"I couldn't find a quest named '{quest_name}'"))
                if reward:
                    reward = await questrewardmanagement_cog.check_reward(ctx, quest, reward)
                else:
                    reward = await questrewardmanagement_cog.prompt_reward(ctx, quest)
                if not reward:
                    return await channel.send(embed=discord.Embed(
                        colour=discord.Colour.red(),
                        description=f"I couldn't find a reward for '{quest_name}'"))
                research_embed.add_field(name="**Pokestop:**",
                                         value='\n'.join(textwrap.wrap(location.title(), width=30)))
                research_embed.add_field(name="**Quest:**",
                                         value='\n'.join(textwrap.wrap(quest.name.title(), width=30)))
                research_embed.add_field(name="**Reward:**",
                                         value='\n'.join(textwrap.wrap(reward.title(), width=30)))
                break
            else:
                research_embed.add_field(name='**New Research Report**',
                                         value="I'll help you report a research quest!\n\n"
                                               "First, I'll need to know what **pokestop** you received the quest from."
                                               " Reply with the name of the **pokestop**. "
                                               "You can reply with **cancel** to stop anytime.", inline=False)
                pokestopwait = await channel.send(embed=research_embed)
                try:
                    pokestopmsg = await self.bot.wait_for('message', timeout=60,
                                                          check=(lambda reply: reply.author == message.author))
                except asyncio.TimeoutError:
                    pokestopmsg = None
                await pokestopwait.delete()
                if not pokestopmsg:
                    error = "took too long to respond"
                    break
                elif pokestopmsg.clean_content.lower() == "cancel":
                    error = "cancelled the report"
                    await pokestopmsg.delete()
                    break
                elif pokestopmsg:
                    location = pokestopmsg.clean_content
                    if stops:
                        stop = await location_matching_cog.match_prompt(channel, author.id, location, stops)
                        if not stop:
                            self.bot.help_logger.info(f"User: {ctx.author.name}, channel: {ctx.channel}, error: No Pokestop found with name: {location.strip()}.")
                            return await channel\
                                .send(embed=discord.Embed(colour=discord.Colour.red(),
                                                          description=f"I couldn't find a pokestop named '{location}'."
                                                          f"Try again using the exact pokestop name!"))
                        if self.get_existing_research(guild, stop):
                            return await channel.send(
                                embed=discord.Embed(colour=discord.Colour.red(),
                                                    description=f"A quest has already been reported for {stop.name}"))
                        location = stop.name
                        loc_url = stop.maps_url
                        regions = [stop.region]
                    else:
                        loc_url = utilities_cog.create_gmaps_query(location, channel, type="research")
                    location = location.replace(loc_url, "").strip()
                await pokestopmsg.delete()
                research_embed.add_field(name="**Pokestop:**",
                                         value='\n'.join(textwrap.wrap(location.title(), width=30)))
                research_embed.set_field_at(0, name=research_embed.fields[0].name,
                                            value="Great! Now, reply with the **quest** that you received from "
                                                  "**{location}**. You can reply with **cancel** to stop anytime."
                                                  "\n\nHere's what I have so far:".format(location=location),
                                            inline=False)
                questwait = await channel.send(embed=research_embed)
                try:
                    questmsg = await self.bot.wait_for('message', timeout=60,
                                                       check=(lambda reply: reply.author == message.author))
                except asyncio.TimeoutError:
                    questmsg = None
                await questwait.delete()
                if not questmsg:
                    error = "took too long to respond"
                    break
                elif questmsg.clean_content.lower() == "cancel":
                    error = "cancelled the report"
                    await questmsg.delete()
                    break
                elif questmsg:
                    quest = await questrewardmanagement_cog.get_quest(ctx, questmsg.clean_content.strip())
                await questmsg.delete()
                if not quest:
                    error = "didn't identify the quest"
                    break
                research_embed.add_field(name="**Quest:**",
                                         value='\n'.join(textwrap.wrap(quest.name.title(), width=30)))
                reward = await questrewardmanagement_cog.prompt_reward(ctx, quest.name.title())
                if not reward:
                    error = "didn't identify the reward"
                    break
                research_embed.add_field(name="**Reward:**",
                                         value='\n'.join(textwrap.wrap(reward.title(), width=30)))
                research_embed.remove_field(0)
                break
        if not error:
            research_msg = f'{quest.name} Field Research task, reward: {reward} reported at {location}'
            research_embed.title = 'Click here for my directions to the research!'
            research_embed.description = "Ask {author} if my directions aren't perfect!".format(author=author.name)
            research_embed.url = loc_url
            confirmation = await channel.send(research_msg, embed=research_embed)
            await utilities_cog.reaction_delay(confirmation, ['\u270f', '🚫'])
            research_dict = copy.deepcopy(self.bot.guild_dict[guild.id].get('questreport_dict', {}))
            research_dict[confirmation.id] = {
                'regions': regions,
                'exp': time.time() + to_midnight,
                'expedit': "delete",
                'reportmessage': message.id,
                'reportchannel': channel.id,
                'reportauthor': author.id,
                'location': location,
                'location_id': stop.id,
                'url': loc_url,
                'quest': quest.name,
                'quest_id': quest.id,
                'reward': reward
            }
            self.bot.guild_dict[guild.id]['questreport_dict'] = research_dict
            listmgmt_cog = self.bot.cogs.get('ListManagement')
            await listmgmt_cog.update_listing_channels(guild, 'research', edit=False, regions=regions)
            subscriptions_cog = self.bot.cogs.get('Subscriptions')
            send_channel = subscriptions_cog.get_region_list_channel(guild, regions[0], 'research')
            if send_channel is None:
                send_channel = channel
            points = 1
            if 'encounter' in reward.lower():
                pkmn = reward.rsplit(maxsplit=1)[0]
                research_details = {'pokemon': [Pokemon.get_pokemon(self.bot, p) for p in re.split(r'\s*,\s*', pkmn)],
                                    'location': location, 'regions': regions}
                points = await subscriptions_cog.send_notifications_async('research', research_details,
                                                                          send_channel, [message.author.id])
            elif reward.split(' ')[0].isdigit() and 'stardust' not in reward.lower():
                item = ' '.join(reward.split(' ')[1:])
                research_details = {'item': item, 'location': location, 'regions': regions}
                points = await subscriptions_cog.send_notifications_async('item', research_details,
                                                                          send_channel, [author.id])
            research_reports = self.bot.guild_dict[ctx.guild.id]\
                                   .setdefault('trainers', {})\
                                   .setdefault(regions[0], {})\
                                   .setdefault(author.id, {})\
                                   .setdefault('research_reports', 0) + points
            self.bot.guild_dict[ctx.guild.id]['trainers'][regions[0]][author.id]['research_reports'] = research_reports
            await self._add_db_research_report(ctx, confirmation)
            clean_list = self.bot.guild_dict[ctx.guild.id]['configure_dict'].setdefault('channel_auto_clean', [])
            if ctx.channel.id in clean_list:
                await ctx.message.delete()
        else:
            research_embed.clear_fields()
            research_embed.add_field(name='**Research Report Cancelled**',
                                     value="Your report has been cancelled because you {error}! "
                                           "Retry when you're ready.".format(error=error), inline=False)
            confirmation = await channel.send(embed=research_embed)
            return await utils.sleep_and_cleanup([message, confirmation], 10)

    @commands.command(aliases=['resl', 'resm'], brief="Report a List of Field Research tasks")
    @checks.allowresearchreport()
    async def research_multiple(self, ctx, *, details=None):
        """**Usage**: `!research_multiple / resl / resm task, reward, stop, [stop2, etc...]`
        Provide task name and reward and at least 1 pokestop."""
        message = ctx.message
        channel = message.channel
        author = message.author
        guild = message.guild
        timestamp = (message.created_at + datetime.timedelta(
            hours=self.bot.guild_dict[message.channel.guild.id]['configure_dict']['settings']['offset']))
        to_midnight = 24 * 60 * 60 - (timestamp - timestamp.replace(hour=0, minute=0, second=0, microsecond=0)).seconds

        utilities_cog = self.bot.cogs.get('Utilities')
        location_matching_cog = self.bot.cogs.get('LocationMatching')
        questrewardmanagement_cog = self.bot.cogs.get('QuestRewardManagement')

        regions = utilities_cog.get_channel_regions(channel, 'research')
        stops = location_matching_cog.get_stops(guild.id, regions)

        research_split = details.split(",")
        if len(research_split) < 3:
            error = "entered an incorrect amount of arguments.\n\n" \
                    "**Usage**: `!research_multiple / resl / resm task, reward, stop, [stop2, etc...]`"
            return await channel.send(embed=discord.Embed(colour=discord.Colour.red(), description=error))
        task, reward, report_stops = research_split[0], research_split[1], research_split[2:]

        quest = await questrewardmanagement_cog.get_quest(ctx, task.strip())
        if not quest:
            self.bot.help_logger.info(
                f"User: {ctx.author.name}, channel: {ctx.channel}, error: No quest found with name: {task}.")
            return await channel.send(embed=discord.Embed(
                colour=discord.Colour.red(),
                description=f"I couldn't find a quest named '{task}'"))

        reward = await questrewardmanagement_cog.check_reward(ctx, quest, reward)
        if not reward:
            return await channel.send(embed=discord.Embed(
                colour=discord.Colour.red(),
                description=f"I couldn't find a reward for '{task}'"))
        failed_stops = {"not_found": [], "already_reported": []}
        success_count = 0
        confirmation = None
        if stops:
            for s in report_stops:
                stop = await location_matching_cog.match_prompt(channel, author.id, s.strip(), stops)
                if not stop:
                    self.bot.help_logger.info(
                        f"User: {ctx.author.name}, channel: {ctx.channel}, error: No Pokestop found with name: {s.strip()}.")
                    failed_stops["not_found"].append(s)
                    continue
                if self.get_existing_research(guild, stop):
                    failed_stops["already_reported"].append(s)
                    continue
                location = stop.name
                loc_url = stop.maps_url
                regions = [stop.region]
                research_embed = discord.Embed(
                    colour=message.guild.me.colour) \
                    .set_thumbnail(
                    url='https://raw.githubusercontent.com/klords/Kyogre/master/images/misc/field-research.png?cache=0')
                research_embed.set_footer(text='Reported by {author} - {timestamp}'
                                          .format(author=author.display_name,
                                                  timestamp=timestamp.strftime('%I:%M %p (%H:%M)')),
                                          icon_url=author.avatar_url_as(format=None, static_format='jpg', size=32))
                research_msg = f'{quest.name} Field Research task, reward: {reward} reported at {location}'
                research_embed.title = 'Click here for my directions to the research!'
                research_embed.description = "Ask {author} if my directions aren't perfect!".format(author=author.name)
                research_embed.url = loc_url
                confirmation = await channel.send(research_msg, embed=research_embed)
                await utilities_cog.reaction_delay(confirmation, ['\u270f', '🚫'])
                research_dict = copy.deepcopy(self.bot.guild_dict[guild.id].get('questreport_dict', {}))
                research_dict[confirmation.id] = {
                    'regions': regions,
                    'exp': time.time() + to_midnight,
                    'expedit': "delete",
                    'reportmessage': message.id,
                    'reportchannel': channel.id,
                    'reportauthor': author.id,
                    'location': location,
                    'location_id': stop.id,
                    'url': loc_url,
                    'quest': quest.name,
                    'quest_id': quest.id,
                    'reward': reward
                }
                self.bot.guild_dict[guild.id]['questreport_dict'] = research_dict
                success_count += 1
        else:
            return await channel.send(embed=discord.Embed(
                colour=discord.Colour.red(), description="Failed to load Pokestops list."))
        no_stop = len(failed_stops["not_found"])
        reported = len(failed_stops["already_reported"])
        if no_stop > 0:
            message = "Could not find the following stops:"
            for stop in failed_stops["not_found"]:
                message += f"\n{stop}"
            await channel.send(embed=discord.Embed(colour=discord.Colour.red(), description=message))
        if reported > 0:
            message = "Task already reported for:"
            for stop in failed_stops["already_reported"]:
                message += f"\n{stop}"
            await channel.send(embed=discord.Embed(colour=discord.Colour.red(), description=message))
        if success_count < 1:
            return
        listmgmt_cog = self.bot.cogs.get('ListManagement')
        await listmgmt_cog.update_listing_channels(guild, 'research', edit=False, regions=regions)
        subscriptions_cog = self.bot.cogs.get('Subscriptions')
        send_channel = subscriptions_cog.get_region_list_channel(guild, regions[0], 'research')
        if send_channel is None:
            send_channel = channel
        points = 1
        if 'encounter' in reward.lower():
            pkmn = reward.rsplit(maxsplit=1)[0]
            research_details = {'pokemon': [Pokemon.get_pokemon(self.bot, p) for p in re.split(r'\s*,\s*', pkmn)],
                                'regions': regions, 'multi': True}
            points = await subscriptions_cog.send_notifications_async('research', research_details,
                                                                      send_channel, [message.author.id])
        elif reward.split(' ')[0].isdigit() and 'stardust' not in reward.lower():
            item = ' '.join(reward.split(' ')[1:])
            research_details = {'item': item, 'regions': regions, 'multi': True}
            points = await subscriptions_cog.send_notifications_async('item', research_details,
                                                                      send_channel, [author.id])
        points *= success_count
        research_reports = self.bot.guild_dict[ctx.guild.id] \
                               .setdefault('trainers', {}) \
                               .setdefault(regions[0], {}) \
                               .setdefault(author.id, {}) \
                               .setdefault('research_reports', 0) + points
        self.bot.guild_dict[ctx.guild.id]['trainers'][regions[0]][author.id]['research_reports'] = research_reports
        await self._add_db_research_report(ctx, confirmation)
        clean_list = self.bot.guild_dict[ctx.guild.id]['configure_dict'].setdefault('channel_auto_clean', [])
        if ctx.channel.id in clean_list:
            await ctx.message.delete()

    async def _add_db_research_report(self, ctx, message):
        channel = ctx.channel
        guild = channel.guild
        author = ctx.author
        quest_dict = self.bot.guild_dict[guild.id]['questreport_dict'][message.id]
        created = round(message.created_at.timestamp())
        __, __ = GuildTable.get_or_create(snowflake=guild.id)
        __, __ = TrainerTable.get_or_create(snowflake=author.id, guild=guild.id)
        report = TrainerReportRelation.create(guild=ctx.guild.id,
                                              created=created, trainer=author.id,
                                              location=quest_dict['location_id'], message=message.id)
        try:
            ResearchTable.create(trainer_report=report, quest=quest_dict['quest'], reward=quest_dict['reward'])
        except Exception as e:
            self.bot.logger.info(f"Failed to create research table entry with error: {e}")

    async def _update_db_research_report(self, guild, message, updated):
        report, report_relation = None, None
        try:
            report_relation = TrainerReportRelation.get(TrainerReportRelation.message == message.id)
            report = ResearchTable.get(ResearchTable.trainer_report_id == report_relation.id)
        except Exception as e:
            self.bot.logger.info(f"Failed to update research table entry with error: {e}")
        if report is None or report_relation is None:
            return self.bot.logger.info(f"No Research report found in db to update. Message id: {message.id}")
        quest_dict = self.bot.guild_dict[guild.id]['questreport_dict'].get(message.id, None)
        if quest_dict is None:
            return self.bot.logger.info(f"No quest_dict found in guild_dict. "
                                        f"Cannot update research report. Message id: {message.id}")
        report.quest = quest_dict['quest']
        report.reward = quest_dict['reward']
        report.save()
        report_relation.location_id = quest_dict['location_id']
        report_relation.updated = updated
        report_relation.save()

    async def _cancel_db_research_report(self, message):
        try:
            report_relation = TrainerReportRelation.get(TrainerReportRelation.message == message.id)
        except Exception as e:
            return self.bot.logger.info(f"Failed to cancel research table entry with error: {e}")
        report_relation.cancelled = 'True'
        report_relation.save()

    async def modify_research_report(self, payload):
        channel = self.bot.get_channel(payload.channel_id)
        try:
            message = await channel.fetch_message(payload.message_id)
        except (discord.errors.NotFound, AttributeError):
            return
        guild = message.guild
        try:
            user = guild.get_member(payload.user_id)
        except AttributeError:
            return
        updated_time = round(time.time())
        questreport_dict = self.bot.guild_dict[guild.id].setdefault('questreport_dict', {})
        research_embed = discord.Embed(colour=message.guild.me.colour).set_thumbnail(
            url='https://raw.githubusercontent.com/klords/Kyogre/master/images/misc/field-research.png?cache=0')
        research_embed.set_footer(text='Reported by {user}'.format(user=user.display_name),
                                  icon_url=user.avatar_url_as(format=None, static_format='jpg', size=32))
        utils_cog = self.bot.cogs.get('Utilities')
        regions = utils_cog.get_channel_regions(channel, 'research')
        location_matching_cog = self.bot.cogs.get('LocationMatching')
        stops = location_matching_cog.get_stops(guild.id, regions)
        stop = questreport_dict[message.id]['location']
        prompt = f'Modifying details for **research task** at **{stop}**\n' \
            f'Which item would you like to modify ***{user.display_name}***?'
        choices_list = ['Pokestop', 'Task', 'Reward']
        match = await utils.ask_list(self.bot, prompt, channel, choices_list, user_list=user.id)
        quest = None
        reward = None
        questrewardmanagement_cog = self.bot.cogs.get('QuestRewardManagement')
        if not questrewardmanagement_cog:
            return await channel.send(embed=discord.Embed(colour=discord.Colour.red(),
                                                          description="Quest data is not loaded for this server."))
        if match in choices_list:
            if match == choices_list[0]:
                query_msg = await channel.send(
                    embed=discord.Embed(colour=discord.Colour.gold(), description="What is the correct Pokestop?"))
                try:
                    pokestopmsg = await self.bot.wait_for('message', timeout=30,
                                                          check=(lambda reply: reply.author == user))
                except asyncio.TimeoutError:
                    pokestopmsg = None
                    await pokestopmsg.delete()
                if pokestopmsg.clean_content.lower() == "cancel":
                    await pokestopmsg.delete()
                elif pokestopmsg:
                    if stops:
                        stop = await location_matching_cog.match_prompt(channel, user.id,
                                                                        pokestopmsg.clean_content, stops)
                        if not stop:
                            self.bot.help_logger.info(f"User: {user.name}, channel: {channel}, error: No Pokestop found with name: {pokestopmsg.clean_content}.")
                            await channel.send(embed=discord.Embed(
                                colour=discord.Colour.red(),
                                description=f"I couldn't find a pokestop named '{pokestopmsg.clean_content}'."
                                f" Try again using the exact pokestop name!"))
                        else:
                            if self.get_existing_research(guild, stop):
                                await channel.send(embed=discord.Embed(
                                    colour=discord.Colour.red(),
                                    description=f"A quest has already been reported for {stop.name}"))
                            else:
                                location = stop.name
                                loc_url = stop.maps_url
                                questreport_dict[message.id]['location'] = location
                                questreport_dict[message.id]['location_id'] = stop.id
                                questreport_dict[message.id]['url'] = loc_url
                                listmgmt_cog = self.bot.cogs.get('ListManagement')
                                await listmgmt_cog.update_listing_channels(guild, "research", regions=regions)
                                await channel.send(embed=discord.Embed(colour=discord.Colour.green(),
                                                                       description="Research listing updated"))
                                await pokestopmsg.delete()
                                await query_msg.delete()
            elif match == choices_list[1]:
                questwait = await channel.send(
                    embed=discord.Embed(colour=discord.Colour.gold(), description="What is the correct research task?"))
                try:
                    questmsg = await self.bot.wait_for('message', timeout=30,
                                                       check=(lambda reply: reply.author == user))
                except asyncio.TimeoutError:
                    questmsg = None
                await questwait.delete()
                if questmsg.clean_content.lower() == "cancel":
                    await questmsg.delete()
                elif questmsg:
                    quest = await questrewardmanagement_cog._get_quest(channel, user.id, questmsg.clean_content)
                    reward = await questrewardmanagement_cog._prompt_reward(channel, user.id, quest)
                questreport_dict[message.id]['quest'] = quest.name
                questreport_dict[message.id]['quest_id'] = quest.id
                questreport_dict[message.id]['reward'] = reward
                listmgmt_cog = self.bot.cogs.get('ListManagement')
                await listmgmt_cog.update_listing_channels(guild, "research", regions=regions)
                await channel.send(
                    embed=discord.Embed(colour=discord.Colour.green(), description="Research listing updated"))
                await questmsg.delete()
            elif match == choices_list[2]:
                rewardwait = await channel.send(embed=discord.Embed(colour=discord.Colour.gold(),
                                                                    description="What is the correct reward?"))
                quest = self.bot.guild_dict[guild.id]['questreport_dict'].get(message.id, None)
                quest_obj = await questrewardmanagement_cog._get_quest(channel, user.id, quest['quest'])
                reward = await questrewardmanagement_cog._prompt_reward(channel, user.id, quest_obj)

                questreport_dict[message.id]['reward'] = reward
                listmgmt_cog = self.bot.cogs.get('ListManagement')
                await listmgmt_cog.update_listing_channels(guild, "research", regions=regions)
                await channel.send(embed=discord.Embed(colour=discord.Colour.green(),
                                                       description="Research listing updated"))
                await rewardwait.delete()
            embed = message.embeds[0]
            embed.clear_fields()
            location = questreport_dict[message.id]['location']
            name = questreport_dict[message.id]['quest']
            reward = questreport_dict[message.id]['reward']
            embed.add_field(name="**Pokestop:**", value='\n'.join(textwrap.wrap(location.title(), width=30)),
                            inline=True)
            embed.add_field(name="**Quest:**", value='\n'.join(textwrap.wrap(name.title(), width=30)), inline=True)
            embed.add_field(name="**Reward:**", value='\n'.join(textwrap.wrap(reward.title(), width=30)), inline=True)
            embed.url = questreport_dict[message.id]['url']
            new_msg = f'{name} Field Research task, reward: {reward} reported at {location}'
            await message.edit(content=new_msg, embed=embed)
            await self._update_db_research_report(guild, message, updated_time)
        else:
            return

    def get_existing_research(self, guild, location):
        """returns a list of confirmation message ids for research reported at the location provided"""
        report_dict = self.bot.guild_dict[guild.id]['questreport_dict']

        def matches_existing(report):
            return report['location'].lower() == location.name.lower()

        return [confirmation_id for confirmation_id, report in report_dict.items() if matches_existing(report)]

    @commands.Cog.listener()
    @checks.good_standing()
    async def on_raw_reaction_add(self, payload):
        if payload.user_id == self.bot.user.id:
            return
        guild_dict = self.bot.guild_dict
        channel = self.bot.get_channel(payload.channel_id)
        try:
            message = await channel.fetch_message(payload.message_id)
        except (discord.errors.NotFound, AttributeError):
            return
        guild = message.guild
        try:
            user = guild.get_member(payload.user_id)
        except AttributeError:
            return
        utils_cog = self.bot.cogs.get('Utilities')
        regions = utils_cog.get_channel_regions(channel, 'raid')
        listmgmt_cog = self.bot.cogs.get('ListManagement')
        questreport_dict = guild_dict[guild.id].setdefault('questreport_dict', {})
        if message.id in questreport_dict:
            quest_dict = questreport_dict.get(message.id, None)
            if quest_dict and (quest_dict['reportauthor'] == payload.user_id or utils.can_manage(user, self.bot.config)):
                if str(payload.emoji) == '\u270f':
                    await self.modify_research_report(payload)
                elif str(payload.emoji) == '🚫':
                    try:
                        await message.edit(embed=discord.Embed(description="Research report cancelled",
                                                               colour=message.embeds[0].colour.value))
                        await message.clear_reactions()
                        await self._cancel_db_research_report(message)
                    except discord.errors.NotFound:
                        pass
                    del questreport_dict[message.id]
                    await listmgmt_cog.update_listing_channels(guild, "research", edit=True, regions=regions)
                await message.remove_reaction(payload.emoji, user)


def setup(bot):
    bot.add_cog(ResearchCommands(bot))
