import copy

async def get_embed_field_indices(embed):
    index = 0
    embed_indices = {"gym": None,
                    "possible": None,
                    "interest": None,
                    "next": None,
                    "hatch": None,
                    "expires": None,
                    "status": None,
                    "team": None,
                    "details": None,
                    "weak": None,
                    "maybe": None,
                    "coming": None,
                    "here": None,
                    "tips": None,
                    "directions": None
                    }
    for field in embed.fields:
        if "gym" in field.name.lower():
            embed_indices["gym"] = index
        if "possible" in field.name.lower():
            embed_indices["possible"] = index
        if "interest" in field.name.lower():
            embed_indices["interest"] = index
        if "next" in field.name.lower():
            embed_indices["next"] = index
        if "hatch" in field.name.lower():
            embed_indices["hatch"] = index
        if "expires" in field.name.lower():
            embed_indices["expires"] = index
        if "status" in field.name.lower():
            embed_indices["status"] = index
        if "team" in field.name.lower():
            embed_indices["team"] = index
        if "details" in field.name.lower():
            embed_indices["details"] = index
        if "weak" in field.name.lower():
            embed_indices["weak"] = index
        if "tips" in field.name.lower():
            embed_indices["tips"] = index
        if "maybe" in field.name.lower():
            embed_indices["maybe"] = index
        if "coming" in field.name.lower():
            embed_indices["coming"] = index
        if "here" in field.name.lower():
            embed_indices["here"] = index
        if "directions" in field.name.lower():
            embed_indices["directions"] = index
        # if "" in field.name.lower():
        #     embed_indices[""] = index
        index += 1
    return embed_indices

async def filter_fields_for_report_embed(embed, embed_indices, enabled):
    new_embed = copy.deepcopy(embed)
    new_embed.clear_fields()
    if embed_indices['gym'] is not None:
        new_embed.add_field(name=embed.fields[embed_indices['gym']].name, value=embed.fields[embed_indices['gym']].value, inline=True) 
    if embed_indices['hatch'] is not None:
        new_embed.add_field(name=embed.fields[embed_indices['hatch']].name, value=embed.fields[embed_indices['hatch']].value, inline=True) 
    if embed_indices['expires'] is not None:
        new_embed.add_field(name=embed.fields[embed_indices['expires']].name, value=embed.fields[embed_indices['expires']].value, inline=True)
    if embed_indices['team'] is not None:
        new_embed.add_field(name=embed.fields[embed_indices['team']].name, value=embed.fields[embed_indices['team']].value, inline=True)
    if embed_indices['status'] is not None:
        new_embed.add_field(name=embed.fields[embed_indices['status']].name, value=embed.fields[embed_indices['status']].value, inline=True)
    if not enabled:
        if embed_indices['directions'] is not None:
            new_embed.add_field(name=embed.fields[embed_indices['directions']].name, value=embed.fields[embed_indices['directions']].value, inline=True)
    return new_embed
