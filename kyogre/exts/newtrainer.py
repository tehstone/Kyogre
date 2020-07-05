import asyncio
import json

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
            await self._setup_profile(ctx, file, message.attachments[0].url)

    @staticmethod
    async def _delete_with_pause(messages):
        for m in messages:
            try:
                await m.delete()
            except:
                pass
            await asyncio.sleep(.3)

    async def _setup_profile(self, ctx, file, u):
        team_role_names = [r.lower() for r in self.bot.team_color_map.keys()]
        for team in team_role_names:
            temp_role = discord.utils.get(ctx.guild.roles, name=team)
            if temp_role:
                # and the user has this role,
                if temp_role in ctx.author.roles:
                    await ctx.message.delete()
                    err_msg = f"{ctx.author.mention} your team is already set. Ask for help if you need to change it." \
                              "\nIf you would like to update your profile, use `!set profile`"
                    await ctx.channel.send(embed=discord.Embed(colour=discord.Colour.red(), description=err_msg))
                    return await image_utils.cleanup_file(file, f"screenshots/profile")
        trainer_name, xp, level = "", "", ""
        try:
            data = json.loads('{"image_url": "' + u + '"}')
            image_info = await self.bot.make_request(data, 'profile')
            scan_team = image_info['team']
            level = image_info['level']
            trainer_name = image_info['trainer_name']
            xp = image_info['xp']
        except Exception as e:
            self.bot.logger.info(f"Request to image processing server failed with error: {e}")
            try:
                scan_team, level, trainer_name, xp = await image_scan.scan_profile(file)
            except AttributeError:
                scan_team = None
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

        trainer_names = self.bot.guild_dict[ctx.guild.id].setdefault('trainer_names', {})
        trainer_names[trainer_name] = ctx.author.id
        trainer_dict['trainername'] = trainer_name

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
            fourty_prompt = await ctx.send(
                f"{ctx.author.mention} You have been verified as a level 40 Trainer. \n"
                "Reply with your **Total XP** or with **N**o to skip.")
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
                    trainer_dict['xp'] = response
            await self._delete_with_pause([fourty_prompt, response_msg])
        friend_prompt = await ctx.send(f"{ctx.author.mention} Would you like to add your Friend Code to your profile?\n"
                                       "Reply with your **Friend Code** as text or with **N**o to skip.")
        try:
            response_msg = await self.bot.wait_for('message', timeout=120,
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
        try:
            xp = int(xp)
            xp_msg = f'your XP has been set to **{xp:,d}**'
        except (ValueError, TypeError):
            xp_msg = "your XP could not be determined"
        if not level:
            level_msg = "your level could not be determined"
        else:
            level_msg = f"your level has been set to **{level}**"
        if not trainer_name:
            trainer_msg = "\nYour trainer name could not be determined"
        else:
            trainer_msg = f"\nThe trainer name on your profile has been set to **{trainer_name}**"


        await ctx.channel.send(f"{ctx.author.mention} your team has been set to **{scan_team.capitalize()}** {team_emoji}!"
                               f"{trainer_msg}, {level_msg} and {xp_msg}."
                               "\nIf you would like to make changes or update your profile use `!set profile`"
                               "\nOr set an profile entry individually with `!set <entry name>`"
                               "\nFor example: `!set friendcode 123456789101`")
        await image_utils.cleanup_file(file, f"screenshots/profile")


def setup(bot):
    bot.add_cog(NewTrainer(bot))
