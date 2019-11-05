import asyncio

import discord
from discord.ext import commands

from kyogre import image_scan, utils, image_utils
from kyogre.context import Context

level_xp_map = {1: 0,
                2:	1000,
                3:	3000,
                4:	6000,
                5:	10000,
                6:	15000,
                7:	21000,
                8:	28000,
                9:	36000,
                10:	45000,
                11:	55000,
                12:	65000,
                13:	75000,
                14:	85000,
                15:	100000,
                16:	120000,
                17:	140000,
                18:	160000,
                19:	185000,
                20:	210000,
                21:	260000,
                22:	335000,
                23:	435000,
                24:	560000,
                25:	710000,
                26:	900000,
                27:	1100000,
                28:	1350000,
                29:	1650000,
                30:	2000000,
                31:	2500000,
                32:	3000000,
                33:	3750000,
                34: 4750000,
                35: 6000000,
                36: 7500000,
                37: 9500000,
                38: 12000000,
                39: 15000000,
                40: 20000000}


class NewTrainer(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message):
        ctx = await self.bot.get_context(message, cls=Context)
        if len(message.attachments) < 1 \
                or ((message.attachments[0].height is None) and
                    (message.attachments[0].width is None)) \
                or message.author == self.bot.user:
            return
        listen_channels = self.bot.guild_dict[ctx.guild.id]['configure_dict']['settings'] \
            .setdefault('profile_scan_listen_channels', [])
        if message.channel.id in listen_channels:
            await message.add_reaction('🤔')
            file = await image_utils.image_pre_check(message.attachments[0])
            await self._setup_profile(ctx, file)

    @staticmethod
    async def _delete_with_pause(messages):
        for m in messages:
            try:
                await m.delete()
            except:
                pass
            await asyncio.sleep(.3)

    # Prompt to upload screenshot
    # Ask if their trainer name is correct, if not what is correct (accept yes/y/newname)
    # Ask if their level is correct or for correct value (accept yes/y/newlevel)
    # Regardless of answers, set their team
    async def _setup_profile(self, ctx, file):
        team_role_names = [r.lower() for r in self.bot.team_color_map.keys()]
        for team in team_role_names:
            temp_role = discord.utils.get(ctx.guild.roles, name=team)
            if temp_role:
                # and the user has this role,
                if temp_role in ctx.author.roles:
                    await ctx.message.delete()
                    err_msg = f"{ctx.author.mention} your team is already set. Ask for help if you need to change it." \
                              "\nIf you would like to update your profile, use `!set profile`"
                    return await ctx.channel.send(embed=discord.Embed(colour=discord.Colour.red(), description=err_msg))
        scan_team, level, trainer_name, xp = await image_scan.scan_profile(file)
        if not scan_team:
            return await ctx.channel.send(
                embed=discord.Embed(
                    colour=discord.Colour.red(),
                    description="No team color identified. Please try a different image."))
        team_role = discord.utils.get(ctx.guild.roles, name=scan_team)
        if team_role is not None:
            await ctx.author.add_roles(team_role)
        trainer_dict = self.bot.guild_dict[ctx.guild.id].setdefault('trainers', {}) \
            .setdefault('info', {}).setdefault(ctx.author.id, {})
        name_prompt = await ctx.send(f"{ctx.author.mention} Is this your trainer name: **{trainer_name}** ?"
                                     "\nReply with **Y**es if correct, or your actual trainer name if not.")
        try:
            response_msg = await self.bot.wait_for('message', timeout=30,
                                                   check=(lambda reply: reply.author == ctx.message.author))
        except asyncio.TimeoutError:
            response_msg = None
        if response_msg:
            response = response_msg.clean_content.lower()
            if response == 'y' or response == 'yes':
                pass
            else:
                trainer_name = response
            trainer_names = self.bot.guild_dict[ctx.guild.id].setdefault('trainer_names', {})
            trainer_names[trainer_name] = ctx.author.id
            trainer_dict['trainername'] = trainer_name
        await self._delete_with_pause([name_prompt, response_msg])
        level_prompt = await ctx.send(f"{ctx.author.mention}  Are you level **{level}**?"
                                      " Your level plus the XP displayed will determine your total XP."
                                      "\nReply with **Y**es if correct, or your actual level if not.")
        try:
            response_msg = await self.bot.wait_for('message', timeout=30,
                                                   check=(lambda reply: reply.author == ctx.message.author))
        except asyncio.TimeoutError:
            response_msg = None
        if response_msg:
            response = response_msg.clean_content.lower()
            if response == 'y' or response == 'yes':
                pass
            else:
                level = response
        if xp and level:
            try:
                level = int(level)
                xp = int(xp)
                level_xp = level_xp_map[level]
                xp = xp + level_xp
                trainer_dict['xp'] = xp
            except ValueError:
                pass
        elif level == '40':
            trainer_dict['xp'] = level_xp_map[40]
            quickbadge_cog = self.bot.cogs.get('QuickBadge')
            await quickbadge_cog.set_fourty(ctx)
        await self._delete_with_pause([level_prompt, response_msg])
        friend_prompt = await ctx.send(f"{ctx.author.mention} Would you like to add your Friend Code to your profile?\n"
                                       "Reply with your **Friend Code** or with **N**o to skip.")
        try:
            response_msg = await self.bot.wait_for('message', timeout=60,
                                                   check=(lambda reply: reply.author == ctx.message.author))
        except asyncio.TimeoutError:
            response_msg = None
        if response_msg:
            response = response_msg.clean_content.lower()
            if response == 'n' or response == 'no':
                pass
            else:
                trainer_dict['code'] = response
        await self._delete_with_pause([friend_prompt, response_msg])
        team_role = discord.utils.get(ctx.guild.roles, name=scan_team)
        if team_role is not None:
            await ctx.author.add_roles(team_role)
        team_emoji = utils.parse_emoji(ctx.channel.guild, self.bot.config['team_dict'][scan_team])
        await ctx.invoke(self.bot.get_command('profile'), user=ctx.author)
        return await ctx.channel.send(f"{ctx.author.mention} your team has been set to **{scan_team}** {team_emoji}!"
                                      "\nIf you would like to add additional information to your profile or update it "
                                      "use `!set profile`")


def setup(bot):
    bot.add_cog(NewTrainer(bot))
