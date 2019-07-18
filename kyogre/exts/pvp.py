import asyncio
import copy
import datetime
import re
import time

import discord
from discord.ext import commands

from kyogre import utils, checks


class PvP(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.guild_dict = bot.guild_dict

    @commands.group(name="pvp", case_insensitive=True)
    @checks.allowpvp()
    async def _pvp(self, ctx):
        """Handles pvp related commands"""

        if ctx.invoked_subcommand == None:
            raise commands.BadArgument()

    @_pvp.command(name="available", aliases=["av"], brief="Announce that you're available for pvp")
    async def _pvp_available(self, ctx, exptime=None):
        """**Usage**: `!pvp available [time]`
        Kyogre will post a message notifying your friends that you're available for PvP
        for the next 30 minutes by default, or optionally for the amount of time you provide.
        """
        message = ctx.message
        channel = message.channel
        guild = message.guild
        trainer = message.author

        time_msg = None
        expiration_minutes = False
        if exptime:
            if exptime.isdigit():
                expiration_minutes = await utils.time_to_minute_count(self.guild_dict, channel, exptime)
        time_err = "No expiration time provided, your PvP session will remain active for 30 minutes"
        if expiration_minutes is False:
            time_msg = await channel.send(embed=discord.Embed(colour=discord.Colour.orange(), description=time_err))
            expiration_minutes = 30

        now = datetime.datetime.utcnow() + datetime.timedelta(hours=self.guild_dict[guild.id]['configure_dict']['settings']['offset'])
        expire = now + datetime.timedelta(minutes=expiration_minutes)

        league_text = ""
        prompt = 'Do you have a League Preference?'
        choices_list = ['Great League', 'Ultra League', 'Master League', 'Other', 'No Preference']
        match = await utils.ask_list(self.bot, prompt, channel, choices_list, user_list=trainer.id)
        if match in choices_list:
            if match == choices_list[3]:
                specifiy_msg = await channel.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), description="Please specify your battle criteria:"))
                try:
                    pref_msg = await self.bot.wait_for('message', timeout=30, check=(lambda reply: reply.author == trainer))
                except asyncio.TimeoutError:
                    pref_msg = None
                    await specifiy_msg.delete()
                if pref_msg:
                    league_text = pref_msg.clean_content
                    await specifiy_msg.delete()
                    await pref_msg.delete()
            else:
                league_text = match
        else:
            league_text = choices_list[3]

        pvp_embed = discord.Embed(title='{trainer} is available for PvP!'.format(trainer=trainer.display_name), colour=guild.me.colour)

        pvp_embed.add_field(name='**Expires:**', value='{end}'.format(end=expire.strftime('%I:%M %p')), inline=True)
        pvp_embed.add_field(name='**League Preference:**', value='{league}'.format(league=league_text), inline=True)
        pvp_embed.add_field(name='**To challenge:**', value='Use the \u2694 react.', inline=True)
        pvp_embed.add_field(name='**To cancel:**', value='Use the 🚫 react.', inline=True)
        pvp_embed.set_footer(text='{trainer}'.format(trainer=trainer.display_name), icon_url=trainer.avatar_url_as(format=None, static_format='jpg', size=32))
        pvp_embed.set_thumbnail(url="https://github.com/KyogreBot/Kyogre/blob/master/images/misc/pvpn_large.png?raw=true")

        pvp_msg = await channel.send(content=('{trainer} is available for PvP!').format(trainer=trainer.display_name),embed=pvp_embed)
        await pvp_msg.add_reaction('\u2694')
        await pvp_msg.add_reaction('🚫')
        
        expiremsg = '**{trainer} is no longer available for PvP!**'.format(trainer=trainer.display_name)
        pvp_dict = copy.deepcopy(self.guild_dict[guild.id].get('pvp_dict',{}))
        pvp_dict[pvp_msg.id] = {
            'exp':time.time() + (expiration_minutes * 60),
            'expedit': {"content":"","embedcontent":expiremsg},
            'reportmessage':message.id,
            'reportchannel':channel.id,
            'reportauthor':trainer.id,
        }
        self.guild_dict[guild.id]['pvp_dict'] = pvp_dict
        await self._send_pvp_notification_async(ctx)
        self.bot.event_loop.create_task(self.pvp_expiry_check(pvp_msg))
        if time_msg is not None:
            await asyncio.sleep(10)
            await time_msg.delete()
        

    async def _send_pvp_notification_async(self, ctx):
        message = ctx.message
        channel = message.channel
        guild = message.guild
        trainer = guild.get_member(message.author.id)
        trainer_info_dict = self.guild_dict[guild.id]['trainers'].setdefault('info', {})
        friends = trainer_info_dict.setdefault(message.author.id, {}).setdefault('friends', [])
        outbound_dict = {}
        tag_msg = f'**{trainer.display_name}** wants to battle! Who will challenge them?!'
        for friend in friends:
            friend = guild.get_member(friend)
            outbound_dict[friend.id] = {'discord_obj': friend, 'message': tag_msg}
        role_name = utils.sanitize_name(f"pvp {trainer.name}")
        subscriptions_cog = self.bot.cogs.get('Subscriptions')
        if not subscriptions_cog:
            return None
        return await subscriptions_cog.generate_role_notification_async(role_name, channel, outbound_dict)

    @_pvp.command(name="add", brief="Add a user to your friends list")
    async def _pvp_add_friend(self, ctx, *, friends):
        """**Usage**: `!pvp add <friend>`
        **Usage**: `!pvp add AshKetchum#1234, ProfessorOak#5309`
        Provide any number of friends using their discord name including the "#0000" discriminator.
        Whenever one of your friends announces they are available to battle, Kyogre will notify you.
        """
        message = ctx.message
        channel = message.channel
        guild = message.guild
        trainer = message.author
        trainer_dict = copy.deepcopy(self.guild_dict[guild.id]['trainers'])
        trainer_info_dict = trainer_dict.setdefault('info', {})
        friend_list = set([r for r in re.split(r',*\s+', friends.strip()) if r])
        if len(friend_list) < 1:
            err_msg = await channel.send(embed=discord.Embed(colour=discord.Colour.red(), description='Please provide the name of at least one other trainer.\n\
                Name should be the `@mention` of another Discord user.'))
            return await utils.sleep_and_cleanup([message, err_msg], 15)
        friend_list_success = []
        friend_list_errors = []
        friend_list_exist = []
        for user in friend_list:
            try:
                tgt_trainer = await commands.MemberConverter().convert(ctx, user.strip())
            except:
                friend_list_errors.append(user)
                continue
            if tgt_trainer is not None:
                tgt_friends = trainer_info_dict.setdefault(tgt_trainer.id, {}).setdefault('friends', [])
                if trainer.id not in tgt_friends:
                    tgt_friends.append(trainer.id)
                    friend_list_success.append(user)
                else:
                    friend_list_exist.append(user)
            else:
                friend_list_errors.append(user)
        failed_msg = None
        exist_msg = None
        success_msg = None
        if len(friend_list_errors) > 0:
            failed_msg = await channel.send(embed=discord.Embed(colour=discord.Colour.red(), description=f"Unable to find the following users:\n\
                {', '.join(friend_list_errors)}"))
            await message.add_reaction('👍')
        if len(friend_list_exist) > 0:
            exist_msg = await channel.send(embed=discord.Embed(colour=discord.Colour.orange(), description=f"You're already friends with the following users:\n\
                {', '.join(friend_list_exist)}"))
            await message.add_reaction('👍')
        if len(friend_list_success) > 0:
            success_msg = await channel.send(embed=discord.Embed(colour=discord.Colour.green(), description=f"Successfully added the following friends:\n\
                {', '.join(friend_list_success)}"))
            self.guild_dict[guild.id]['trainers'] = trainer_dict
            await message.add_reaction('✅')
        return await utils.sleep_and_cleanup([failed_msg, exist_msg, success_msg], 10)


    @_pvp.command(name="remove", aliases=["rem"], brief="Remove a user from your friends list")
    async def _pvp_remove_friend(self, ctx, *, friends: str = ''):
        """**Usage**: `!pvp [remove|rem] <friend>`
        **Usage**: `!pvp rem AshKetchum#1234, ProfessorOak#5309`
        Provide any number of friends using their discord name including the "#0000" discriminator.
        """
        message = ctx.message
        channel = message.channel
        guild = message.guild
        trainer = message.author
        trainer_dict = copy.deepcopy(self.guild_dict[guild.id]['trainers'])
        trainer_info_dict = trainer_dict.setdefault('info', {})
        friend_list = set([r for r in re.split(r',*\s+', friends.strip()) if r])
        if len(friend_list) < 1:
            err_msg = await channel.send(embed=discord.Embed(colour=discord.Colour.red(), description='Please provide the name of at least one other trainer.\n\
                Name should be the `@mention` of another Discord user.'))
            return await utils.sleep_and_cleanup([message, err_msg], 15)
        friend_list_success = []
        friend_list_errors = []
        friend_list_notexist = []
        for user in friend_list:
            try:
                tgt_trainer = await commands.MemberConverter().convert(ctx, user.strip())
            except:
                friend_list_errors.append(user)
                continue
            if tgt_trainer is not None:
                tgt_friends = trainer_info_dict.setdefault(tgt_trainer.id, {}).setdefault('friends', [])
                if trainer.id in tgt_friends:
                    tgt_friends.remove(trainer.id)
                    friend_list_success.append(user)
                else:
                    friend_list_notexist.append(user)
            else:
                friend_list_errors.append(user)
        
        failed_msg = None
        notexist_msg = None
        success_msg = None
        if len(friend_list_errors) > 0:
            failed_msg = await channel.send(embed=discord.Embed(colour=discord.Colour.red(), description=f"Unable to find the following users:\n\
                {', '.join(friend_list_errors)}"))
            await message.add_reaction('👍')
        if len(friend_list_notexist) > 0:
            notexist_msg = await channel.send(embed=discord.Embed(colour=discord.Colour.orange(), description=f"You're not friends with the following users:\n\
                {', '.join(friend_list_notexist)}"))
            await message.add_reaction('👍')
        if len(friend_list_success) > 0:
            success_msg = await channel.send(embed=discord.Embed(colour=discord.Colour.green(), description=f"Successfully removed the following friends:\n\
                {', '.join(friend_list_success)}"))
            self.guild_dict[guild.id]['trainers'] = trainer_dict
            await message.add_reaction('✅')
        return await utils.sleep_and_cleanup([failed_msg, notexist_msg, success_msg], 10)

    async def pvp_expiry_check(self, message):
        self.bot.logger.info('Expiry_Check - ' + message.channel.name)
        channel = message.channel
        guild = channel.guild
        message = await channel.fetch_message(message.id)
        if message not in self.bot.active_pvp:
            self.bot.active_pvp.append(message)
            self.bot.logger.info('pvp_expiry_check - Message added to watchlist - ' + channel.name)
            await asyncio.sleep(0.5)
            while True:
                try:
                    if self.guild_dict[guild.id]['pvp_dict'][message.id]['exp'] <= time.time():
                        await self.expire_pvp(message)
                except KeyError:
                    pass
                await asyncio.sleep(30)
                continue


    async def expire_pvp(self, message):
        channel = message.channel
        guild = channel.guild
        pvp_dict = self.guild_dict[guild.id]['pvp_dict']
        try:
            await message.edit(content=pvp_dict[message.id]['expedit']['content'],
                               embed=discord.Embed(description=pvp_dict[message.id]['expedit']['embedcontent'],
                                                   colour=message.embeds[0].colour.value))
            await message.clear_reactions()
        except discord.errors.NotFound:
            pass
        try:
            user_message = await channel.fetch_message(pvp_dict[message.id]['reportmessage'])
            await user_message.delete()
        except (discord.errors.NotFound, discord.errors.Forbidden, discord.errors.HTTPException):
            pass
        del self.guild_dict[guild.id]['pvp_dict'][message.id]


def setup(bot):
    bot.add_cog(PvP(bot))
