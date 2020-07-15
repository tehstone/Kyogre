import asyncio
import copy
import datetime
import time

import discord
from discord.ext import commands

from kyogre import checks, utils


class RaidAvailable(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="raidavailable", aliases=["rav"], brief="Report that you're actively looking for raids")
    async def _raid_available(self, ctx, exptime=None):
        """**Usage**: `!raidavailable/rav [time]`
        Must be used in a raid reporting channel.
        Assigns a tag-able role (such as @renton-raids) to you so that others looking for raids can ask for help.
        Tag will remain for 60 minutes by default or for the amount of time you provide. Provide '0' minutes to keep it in effect indefinitely."""
        guild_dict = self.bot.guild_dict
        message = ctx.message
        channel = message.channel
        guild = message.guild
        trainer = message.author
        utils_cog = self.bot.cogs.get('Utilities')
        regions = utils_cog.get_channel_regions(channel, 'raid')
        if len(regions) > 0:
            region = regions[0]
        else:
            region_err = "No region associated with this channel, please use this command in a raid reporting channel."
            return await channel.send(embed=discord.Embed(colour=discord.Colour.orange(), description=region_err),
                                      delete_after=10)
        role_to_assign = discord.utils.get(guild.roles, name=region + '-raids')
        for role in trainer.roles:
            if role.name == role_to_assign.name:
                raid_notice_dict = copy.deepcopy(guild_dict[guild.id].get('raid_notice_dict', {}))
                for rnmessage in raid_notice_dict:
                    try:
                        if raid_notice_dict[rnmessage]['reportauthor'] == trainer.id:
                            rnmessage = await channel.fetch_message(rnmessage)
                            await self.expire_raid_notice(rnmessage)
                            await message.delete()
                    except:
                        pass
                role_to_remove = discord.utils.get(guild.roles, name=role_to_assign)
                try:
                    await trainer.remove_roles(*[role_to_remove],
                                               reason="Raid availability expired or was cancelled by user.")
                except:
                    pass
                return
        expiration_minutes = False
        time_err = "Unable to determine the time you provided, you will be notified for raids for the next 60 minutes"
        if exptime:
            if exptime.isdigit():
                if int(exptime) == 0:
                    expiration_minutes = 2628000
                else:
                    expiration_minutes = await utils.time_to_minute_count(guild_dict, channel, exptime, time_err)
        else:
            time_err = "No expiration time provided, you will be notified for raids for the next 60 minutes"
        if expiration_minutes is False:
            await channel.send(embed=discord.Embed(colour=discord.Colour.orange(), description=time_err),
                               delete_after=10)
            expiration_minutes = 60

        now = datetime.datetime.utcnow() + datetime.timedelta(
            hours=guild_dict[guild.id]['configure_dict']['settings']['offset'])
        expire = now + datetime.timedelta(minutes=expiration_minutes)

        raid_notice_embed = discord.Embed(title='{trainer} is available for Raids!'
                                          .format(trainer=trainer.display_name), colour=guild.me.colour)
        if exptime != "0":
            raid_notice_embed.add_field(name='**Expires:**', value='{end}'
                                        .format(end=expire.strftime('%b %d %I:%M %p')), inline=True)
        raid_notice_embed.add_field(name='**To add 30 minutes:**', value='Use the ⏲️ react.', inline=True)
        raid_notice_embed.add_field(name='**To cancel:**', value='Use the 🚫 react.', inline=True)

        if region is not None:
            footer_text = f"Use the **@{region}-raids** tag to notify all trainers who are currently available"
            raid_notice_embed.set_footer(text=footer_text)
        raid_notice_msg = await channel.send(content='{trainer} is available for Raids!'
                                             .format(trainer=trainer.display_name), embed=raid_notice_embed)
        await raid_notice_msg.add_reaction('\u23f2')
        await raid_notice_msg.add_reaction('🚫')
        expiremsg = '**{trainer} is no longer available for Raids!**'.format(trainer=trainer.display_name)
        raid_notice_dict = copy.deepcopy(guild_dict[guild.id].get('raid_notice_dict', {}))
        epoch = datetime.datetime(1970, 1, 1)
        report_time_int = (datetime.datetime.utcnow() - epoch).total_seconds()
        raid_notice_dict[raid_notice_msg.id] = {
            'exp': report_time_int + (expiration_minutes * 60),
            'expedit': {"content": "", "embedcontent": expiremsg},
            'reportmessage': message.id,
            'reportchannel': channel.id,
            'reportauthor': trainer.id,
        }
        guild_dict[guild.id]['raid_notice_dict'] = raid_notice_dict
        self.bot.event_loop.create_task(self.raid_notice_expiry_check(raid_notice_msg))

        await trainer.add_roles(*[role_to_assign], reason="User announced raid availability.")
        await message.delete()

    async def raid_notice_expiry_check(self, message):
        guild_dict = self.bot.guild_dict
        self.bot.logger.info('Expiry_Check - ' + message.channel.name)
        channel = message.channel
        guild = channel.guild
        message = await channel.fetch_message(message.id)
        if message not in self.bot.active_raids:
            self.bot.active_raids.append(message)
            self.bot.logger.info('raid_notice_expiry_check - Message added to watchlist - ' + channel.name)
            epoch = datetime.datetime(1970, 1, 1)
            await asyncio.sleep(0.5)
            while True:
                try:
                    current = (datetime.datetime.utcnow() - epoch).total_seconds()
                    if guild_dict[guild.id]['raid_notice_dict'][message.id]['exp'] <= current:
                        await self.expire_raid_notice(message)
                except KeyError:
                    pass
                await asyncio.sleep(60)
                continue

    async def expire_raid_notice(self, message):
        guild_dict = self.bot.guild_dict
        channel = message.channel
        guild = channel.guild
        raid_notice_dict = guild_dict[guild.id]['raid_notice_dict']
        try:
            trainer = raid_notice_dict[message.id]['reportauthor']
            user = guild.get_member(trainer)
            channel = guild.get_channel(raid_notice_dict[message.id]['reportchannel'])
            utils_cog = self.bot.cogs.get('Utilities')
            regions = utils_cog.get_channel_regions(channel, 'raid')
            region = None
            if len(regions) > 0:
                region = regions[0]
            if region is not None:
                role_to_remove = discord.utils.get(guild.roles, name=region + '-raids')
                await user.remove_roles(*[role_to_remove], reason="Raid availability expired or was cancelled by user.")
            else:
                self.bot.logger.info('expire_raid_notice - Failed to remove role for user ' + user.display_name)
        except:
            self.bot.logger.info('expire_raid_notice - Failed to remove role. User unknown')
        try:
            await message.edit(content=raid_notice_dict[message.id]['expedit']['content'],
                               embed=discord.Embed(description=raid_notice_dict[message.id]['expedit']['embedcontent'],
                                                   colour=message.embeds[0].colour.value))
            await message.clear_reactions()
        except discord.errors.NotFound:
            pass
        try:
            user_message = await channel.fetch_message(raid_notice_dict[message.id]['reportmessage'])
            await user_message.delete()
        except (discord.errors.NotFound, discord.errors.Forbidden, discord.errors.HTTPException):
            pass
        del guild_dict[guild.id]['raid_notice_dict'][message.id]

    @commands.Cog.listener()
    @checks.good_standing()
    async def on_raw_reaction_add(self, payload):
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
        raid_notice_dict = self.bot.guild_dict[guild.id].setdefault('raid_notice_dict', {})
        if message.id in raid_notice_dict and user.id != self.bot.user.id:
            trainer = raid_notice_dict[message.id]['reportauthor']
            if trainer == payload.user_id or utils.can_manage(user, self.bot.config):
                if str(payload.emoji) == '🚫':
                    return await self.expire_raid_notice(message)
                if str(payload.emoji) == '\u23f2':
                    exp = raid_notice_dict[message.id]['exp'] + 1800
                    raid_notice_dict[message.id]['exp'] = exp
                    expire = datetime.datetime.utcfromtimestamp(exp) + datetime.timedelta(
                        hours=self.bot.guild_dict[guild.id]['configure_dict']['settings']['offset'])
                    expire_str = expire.strftime('%b %d %I:%M %p')
                    embed = message.embeds[0]
                    index = 0
                    found = False
                    for field in embed.fields:
                        if "expire" in field.name.lower():
                            found = True
                            break
                        index += 1
                    if found:
                        embed.set_field_at(index, name=embed.fields[index].name, value=expire_str, inline=True)
                    else:
                        embed.add_field(name='**Expires:**', value='{end}'.format(end=expire_str), inline=True)
                    await message.edit(embed=embed)
                    await message.remove_reaction(payload.emoji, user)


def setup(bot):
    bot.add_cog(RaidAvailable(bot))
