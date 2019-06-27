from meowth import utils

subscription_types = ["Raid Boss", "Raid Tier", "Gym", "EX-Eligible", "Research Reward", "Wild Spawn", "Pokemon - All types (includes raid, research, and wild)", "Perfect (100 IV spawns)"]

async def guided_subscription(ctx, Meowth):
    print("here")
    message = ctx.message
    channel = message.channel
    author = message.author
    guild = message.guild
    prompt = "I'll help you manage your subscriptions!\n\nWould you like to add a new subscription, remove a subscription, or see your current subscriptions?"
    choices_list = ['Add', 'Remove', 'View Existing']
    match = await utils.ask_list(Meowth, prompt, channel, choices_list, user_list=author.id)
    if match == choices_list[0]:
        prompt = "What type of subscription would you like to add?"
        choices_list = subscription_types
        match = await utils.ask_list(Meowth, prompt, channel, choices_list, user_list=author.id)
        await _sub_add(ctx, Meowth, match)
    elif match == choices_list[1]:
        pass
    elif match == choices_list[2]:
        pass
    else:
        return

async def _sub_add(ctx, Meowth, type):
    message = ctx.message
    channel = message.channel
    author = message.author
    guild = message.guild
    if type == subscription_types[0] or type == subscription_types[4] or type == subscription_types[5] or type == subscription_types[6]:
        prompt = await channel.send("Please tell me which Pokemon you're interested in with a comma between each name")
        try:
            pokemonmsg = await Meowth.wait_for('message', timeout=60, check=(lambda reply: reply.author == author))
        except asyncio.TimeoutError:
            pokemonmsg = None
        await prompt.delete()
        if not pokemonmsg:
            error = _("took too long to respond")
        elif pokemonmsg.clean_content.lower() == "cancel":
            error = _("cancelled the report")
            await pokemonmsg.delete()
        elif pokemonmsg:
            candidates = pokemonmsg.clean_content
    elif type == type == subscription_types[1]:
        pass
    elif type == type == subscription_types[2]:
        pass
    elif type == type == subscription_types[3]:
        pass
    elif type == type == subscription_types[7]:
        pass