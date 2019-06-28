from discord.ext import commands
from kyogre.context import Context

class KyogreBot(commands.AutoShardedBot):
    """Custom Discord Bot class for Kyogre"""

    async def process_commands(self, message):
        """Processes commands that are registed with the bot and it's groups.

        Without this being run in the main `on_message` event, commands will
        not be processed.
        """
        if message.author.bot:
            return
        if message.content.startswith('!'):
            if message.content[1] == " ":
                message.content = message.content[0] + message.content[2:]
            content_array = message.content.split(' ')
            content_array[0] = content_array[0].lower()
            # Well that's *one* way to do it
            if content_array[0][1:] in ['r1','r2','r3','r4','r5','raid1','raid2','raid3','raid4','raid5']:
                content_array[0] = content_array[0][:-1] + " " + content_array[0][-1]
            message.content = ' '.join(content_array)

        ctx = await self.get_context(message, cls=Context)
        if not ctx.command:
            return
        await self.invoke(ctx)
