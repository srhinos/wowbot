import inspect
import traceback
import asyncio
import shlex
import discord
import aiohttp
import json
import logging
import sys
import re
import collections
import re
import random
import copy

from TwitterAPI import TwitterAPI


from io import BytesIO, StringIO
from textwrap import dedent
from itertools import islice

from functools import wraps
from discord.ext.commands.bot import _get_variable
from datetime import datetime, timedelta


from wowbot.constants import HELP_MSG, LOCK_ROLES, CANNOT_SET, ROLE_ALIASES, LFG_ROLES, ROLE_REGEX
from .exceptions import CommandError
from .utils import clean_string, write_json, load_json, timestamp_to_seconds, datetime_to_utc_ts, clean_bad_pings
VERSION = '1.0'


class Response(object):
    def __init__(self, content, reply=False, delete_after=0):
        self.content = content
        self.reply = reply
        self.delete_after = delete_after


class WoWBot(discord.Client):
    def __init__(self):
        super().__init__()
        self.prefix = '!'
        self.token = 'ENTER TOKEN HERE'
        self.tags = load_json('tags.json')
        self.mod_mail_db = load_json('modmaildb.json')
        self.muted_dict = load_json('muted.json')
        self.channel_bans = load_json('channel_banned.json')
        self.use_reactions = True
        self.since_id = {'BlizzardCS': 706894913959436288, 'Warcraft': 706894913959436288, 'WoWHead': 706894913959436288}
        self.start_time = datetime.utcnow()
        self.last_modmail_msg = None
        self.reaction_pairings = {'363239568608329738': '282177392225681408',
                             '363239568247488514': '282177411716612096',
                             '363239568608329728': '282177356595200001',
                             '363239568176054274': '282177400408899594',
                             '340167030940631040': '113430817497223168',
                             '340167505131601920': '113430353653284864',
                             '296312735434670080': '146310307189489664',
                             '340167030718332940': '113431023059996672',
                             '340167030533521420': '113430980303306752',
                             '340167030969991168': '113430939165532160',
                             '340167504930537473': '113430474923216896',
                             '340167030802087947': '113430540010430464',
                             '340167030969729024': '113430902763200512',
                             '340167030835642379': '113431058791333888',
                             '340167505114955786': '170201151831146496',
                             '340167030646898699': '113430720893972480',
                             '340167030646898689': '113430589482299392',
                             '363251282846154758': '363245195627724801',
                             '363251284930854924': '363245289240264705'
                            }
        print('past init')
            
    # noinspection PyMethodOverriding
    def run(self):
        loop = asyncio.get_event_loop()
        try:
            loop.create_task(self.mod_mail_reminders())
            loop.run_until_complete(self.start(self.token))
            loop.run_until_complete(self.connect())
        except Exception:
            loop.run_until_complete(self.close())
            pending = asyncio.Task.all_tasks()
            gathered = asyncio.gather(*pending)
            try:
                gathered.cancel()
                loop.run_forever()
                gathered.exception()
            except:
                pass
        finally:
            loop.close()

    async def queue_timed_role(self, sec_time, user, timed_role):
        await asyncio.sleep(sec_time)
        if not user:
            return
        user_roles = user.roles
        if timed_role in user_roles:
            user_roles.remove(timed_role)
            await self.replace_roles(user, *user_roles)
            await self.server_voice_state(user, mute=False)
            del self.muted_dict[user.id]
            write_json('muted.json', self.muted_dict)
                        
    async def mod_mail_reminders(self):
        while True:
            ticker = 0
            while ticker != 1800:
                await asyncio.sleep(1)
                if not [message.id for message in self.messages if message.id in ['363250089176858624', '363250089172664322', '363250090166714369', '363250089793290241']]:
                    while len([message.id for message in self.messages if message.id in ['363250089176858624', '363250089172664322', '363250090166714369', '363250089793290241']]) != 4:
                        self.messages.append(await self.get_message(discord.Object(id='361717008313614337'), '363250089176858624'))
                        self.messages.append(await self.get_message(discord.Object(id='361717008313614337'), '363250089172664322'))
                        self.messages.append(await self.get_message(discord.Object(id='361717008313614337'), '363250090166714369'))
                        self.messages.append(await self.get_message(discord.Object(id='361717008313614337'), '363250089793290241'))
                if not [member_id for member_id in self.mod_mail_db if not self.mod_mail_db[member_id]['answered']]:
                    ticker = 0
                else:
                    ticker+=1
            try:
                async for lmsg in self.logs_from(discord.Object(id='126963941984174080'), limit=1):
                        if self.last_modmail_msg and lmsg.id == self.last_modmail_msg.id:
                            await self.safe_edit_message(lmsg, content='There are **{}** unread items in the mod mail queue that\'re over a half hour old! Either run `!mmqueue` to see them and reply or mark them read using `!markread`!'.format(len([member_id for member_id in self.mod_mail_db if not self.mod_mail_db[member_id]['answered']])))
                        else:
                            if self.last_modmail_msg:
                                await self.safe_delete_message(self.last_modmail_msg)
                            self.last_modmail_msg = await self.safe_send_message(discord.Object(id='126963941984174080'), content='There are **{}** unread items in the mod mail queue that\'re over a half hour old! Either run `!mmqueue` to see them and reply or mark them read using `!markread`!'.format(len([member_id for member_id in self.mod_mail_db if not self.mod_mail_db[member_id]['answered']])))
            except:
                print('something broke in mod mail, just gonna print this I guess')
                           
    async def on_ready(self):
        print('Connected!\n')
        print('Populating New Ban Roles....')
        new_roles = [role for role in discord.utils.get(self.servers, id='113103747126747136').roles if role.name.startswith('Ban') and role.id not in self.channel_bans]
        if new_roles:
            print('Found %s new roles!' % len(new_roles))
            for role in new_roles:
                self.channel_bans[role.id] = [member.id for member in discord.utils.get(self.servers, id='113103747126747136').members if role in member.roles]
                write_json('channel_banned.json', self.channel_bans)
                
        print('Done!\n\nDeserializing Mutes...')
        target_server = discord.utils.get(self.servers, id='113103747126747136')
        mutedrole = discord.utils.get(target_server.roles, id='120925729843183617')
        temp_dict = copy.deepcopy(self.muted_dict)
        for user_id, timestamp in temp_dict.items():
            user = discord.utils.get(target_server.members, id=user_id)
            if user:
                await self.replace_roles(user, *[mutedrole])
                await self.server_voice_state(user, mute=True)
            if timestamp:
                datetime_timestamp = datetime.fromtimestamp(timestamp)
                if datetime.utcnow() < datetime_timestamp:
                    asyncio.ensure_future(self.queue_timed_role((datetime_timestamp-datetime.utcnow()).total_seconds(), user, mutedrole))
                else:
                    asyncio.ensure_future(self.queue_timed_role(0, user, mutedrole))
                
        
        print('Done!\n\nAppending Missed Mutes...')
        muted_coffee_filter = [member for member in discord.utils.get(self.servers, id='113103747126747136').members if mutedrole in member.roles and member.id not in self.muted_dict]
        for member in muted_coffee_filter:
            self.muted_dict[member.id] = None
        write_json('muted.json', self.muted_dict)
        print('Done!')
        
        await self.change_presence(game=discord.Game(name='DM to contact staff!'))
        await self.safe_send_message(discord.Object(id='126963941984174080'), content='I have just been rebooted!')
        
        print('\n~')

    async def _wait_delete_msg(self, message, after):
        await asyncio.sleep(after)
        await self.safe_delete_message(message)

    async def safe_send_message(self, dest, *, content=None, tts=False, expire_in=0, quiet=False, embed=None):
        msg = None
        try:
            msg = await self.send_message(dest, content=content, tts=tts, embed=embed)

            if msg and expire_in:
                asyncio.ensure_future(self._wait_delete_msg(msg, expire_in))

        except discord.Forbidden:
            if not quiet:
                print("Error: Cannot send message to %s, no permission" % dest.name)
        except discord.NotFound:
            if not quiet:
                print("Warning: Cannot send message to %s, invalid channel?" % dest.name)
        finally:
            if msg: return msg

    async def safe_delete_message(self, message, *, quiet=False):
        try:
            return await self.delete_message(message)

        except discord.Forbidden:
            if not quiet:
                print("Error: Cannot delete message \"%s\", no permission" % message.clean_content)
        except discord.NotFound:
            if not quiet:
                print("Warning: Cannot delete message \"%s\", message not found" % message.clean_content)

    async def safe_edit_message(self, message, *, new_content=None, expire_in=0, send_if_fail=False, quiet=False, embed=None):
        msg = None
        try:
            if not embed:
                msg = await self.edit_message(message, new_content=new_content)
            else:
                msg = await self.edit_message(message, new_content=new_content, embed=embed)

            if msg and expire_in:
                asyncio.ensure_future(self._wait_delete_msg(msg, expire_in))

        except discord.NotFound:
            if not quiet:
                print("Warning: Cannot edit message \"%s\", message not found" % message.clean_content)
            if send_if_fail:
                if not quiet:
                    print("Sending instead")
                msg = await self.safe_send_message(message.channel, content=new)
        finally:
            if msg: return msg
            
    def mods_only(func):
        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            orig_msg = _get_variable('message')

            if [role for role in orig_msg.author.roles if role.id  in ["175657731426877440"]]:
                # noinspection PyCallingNonCallable
                return await func(self, *args, **kwargs)
            else:
                return

        wrapper.mod_cmd = True
        return wrapper

    @mods_only
    async def cmd_restart(self, channel, message, author):
        """
        Usage: {command_prefix}logout
        Forces a logout
        """
        await self.safe_send_message(message.channel, content="Restarting....")
        await self.logout()
    @mods_only
    async def cmd_changeavi(self, author, string_avi):
        """
        Usage: {command_prefix}changegame ["new game name"]
        Changes the "Now Playing..." game on Discord!
        """
        async with aiohttp.get(string_avi) as r:
            data = await r.read()
            await self.edit_profile(avatar=data)
        return Response(':thumbsup:', reply=True)

    async def cmd_clear(self, message, author, channel):
        """
        Usage {command_prefix}clear
        Removes all removable roles from a user.
        """
        author_roles = [role for role in author.roles if role.id in LOCK_ROLES]
        await self.replace_roles(author, *author_roles)
        return Response('I\'ve removed all classes from you!', reply=True, delete_after=15)
        
    @mods_only
    async def cmd_eval(self, author, server, message, channel, mentions, code):
        """
        Usage: {command_prefix}eval "evaluation string"
        runs a command thru the eval param for testing
        """
        python = '```py\n{}\n```'
        result = None

        try:
            result = eval(code)
        except Exception as e:
            return Response(python.format(type(e).__name__ + ': ' + str(e)))

        if asyncio.iscoroutine(result):
            result = await result

        return Response('```{}```'.format(result))
        
    async def cmd_id(self, message, author, server):
        """
        Usage: {command_prefix}ping
        Replies with "PONG!"; Use to test bot's responsiveness
        """
        if message.channel.id != '210522691852173312':
            return
        return Response('Your ID is `{}`!'.format(author.id), reply=True)

    async def cmd_ping(self, message, author, server):
        """
        Usage: {command_prefix}ping
        Replies with "PONG!"; Use to test bot's responsiveness
        """
        return Response('PONG!', reply=True) 
    
    async def cmd_tank(self, message, author, server):
        """
        Usage: {command_prefix}ping
        Replies with "PONG!"; Use to test bot's responsiveness
        """
        if author.nick:
            nickname = author.nick + '🛡'
        else:
            nickname = author.name + '🛡'
        await self.change_nickname(author, nickname)
        return Response('🛡!', reply=True, delete_after=5) 
    
    async def cmd_dps(self, message, author, server):
        """
        Usage: {command_prefix}ping
        Replies with "PONG!"; Use to test bot's responsiveness
        """
        if author.nick:
            nickname = author.nick + '⚔'
        else:
            nickname = author.name + '⚔'
        await self.change_nickname(author, nickname)
        return Response('⚔!', reply=True, delete_after=5) 
    
    async def cmd_healer(self, message, author, server):
        """
        Usage: {command_prefix}ping
        Replies with "PONG!"; Use to test bot's responsiveness
        """
        emoji = random.choice(['🚑', '💊'])
        if author.nick:
            nickname = author.nick + emoji
        else:
            nickname = author.name + emoji
        await self.change_nickname(author, nickname)
        return Response('%s!' % emoji, reply=True, delete_after=5)  
    
    async def cmd_help(self, command=None):
        """
        Usage {command_prefix}help
        Fetches the help info for the bot's commands
        """
        if command:
            cmd = getattr(self, 'cmd_' + command, None)
            if cmd and not hasattr(cmd, 'mod_cmd'):
                return Response(
                    "```\n{}```".format(
                        dedent(cmd.__doc__)
                    ).format(command_prefix=self.prefix),
                    delete_after=60
                )
            else:
                return Response("No such command", delete_after=10)

        else:
            helpmsg = "**Available commands**\n```"
            commands = []

            for att in dir(self):
                if att.startswith('cmd_') and att != 'cmd_help' and not hasattr(getattr(self, att), 'mod_cmd'):
                    command_name = att.replace('cmd_', '').lower()
                    commands.append("{}{}".format(self.prefix, command_name))

            helpmsg += ", ".join(commands)
            helpmsg += "```\n"
            helpmsg += "You can also use `{}help x` for more info about each command.".format(self.prefix)

            return Response(helpmsg, reply=True, delete_after=60)
            
    @mods_only
    async def cmd_markread(self, author, server,  auth_id):
        """
        Usage {command_prefix}echo #channel "ENTER MESSAGE HERE"
        Fetches the help info for the bot's commands
        """
        if auth_id in self.mod_mail_db:
            self.mod_mail_db[auth_id]['answered'] = True
            write_json('modmaildb.json', self.mod_mail_db)
            return Response(':thumbsup:')
        else:
            raise CommandError('ERROR: User ID not found in Mod Mail DB')

    @mods_only
    async def cmd_mmlogs(self, author, channel, server, auth_id):
        """
        Usage {command_prefix}echo #channel "ENTER MESSAGE HERE"
        Fetches the help info for the bot's commands
        """
        if auth_id not in self.mod_mail_db:
            raise CommandError('ERROR: User ID not found in Mod Mail DB')
        quick_switch_dict = {}
        quick_switch_dict[auth_id] = {'embed': discord.Embed(), 'member_obj': await self.get_user_info(auth_id)}
        quick_switch_dict[auth_id]['embed'].set_author(name='{}({})'.format(quick_switch_dict[auth_id]['member_obj'].name, quick_switch_dict[auth_id]['member_obj'].id), icon_url=quick_switch_dict[auth_id]['member_obj'].avatar_url)
        
        current_index = 0
        current_msg = None
        message_dict = collections.OrderedDict(sorted(self.mod_mail_db[auth_id]['messages'].items(), reverse=True))
        loop_dict = quick_switch_dict
        while True:
            od = collections.OrderedDict(islice(message_dict.items(),current_index, current_index+20))
            od = collections.OrderedDict(reversed(list(od.items())))
            for timestamp, msg_dict in od.items():
                user = None
                if msg_dict['modreply'] is not None:
                    try:
                        user = discord.utils.get(server.members, id=msg_dict['modreply']).name
                    except:
                        user = await self.get_user_info(msg_dict['modreply'])
                        user = user.name
                else:
                    user = loop_dict[auth_id]['member_obj'].name
                if len(msg_dict['content']) > 1020:
                    msg_dict['content'] = msg_dict['content'][:1020] + '...'
                loop_dict[auth_id]['embed'].add_field(name='{} | *{}*'.format(user, datetime.utcfromtimestamp(float(timestamp)).strftime('%H:%M %d.%m.%y' )), value=msg_dict['content'], inline=False)
            if not current_msg:
                current_msg = await self.safe_send_message(channel, embed=loop_dict[auth_id]['embed'])
            else:
                current_msg = await self.safe_edit_message(current_msg, embed=loop_dict[auth_id]['embed'])
            
            if current_index != 0:
                await self.add_reaction(current_msg, '⬅')
            if (current_index+1) != len(quick_switch_dict):
                await self.add_reaction(current_msg, '➡')
                
            def check(reaction, user):
                e = str(reaction.emoji)
                if user != self.user:
                    return e.startswith(('⬅', '➡'))
                else:
                    return False
                
            reac = await self.wait_for_reaction(check=check, message=current_msg, timeout=300)
            
            if not reac:
                    return
            elif str(reac.reaction.emoji) == '➡' and current_index != len(quick_switch_dict):
                current_index+=1
                await self.remove_reaction(current_msg, reac.reaction.emoji, reac.user)
            elif str(reac.reaction.emoji) == '⬅' and current_index != 0:
                current_index-=1
                await self.remove_reaction(current_msg, reac.reaction.emoji, reac.user)
            else:
                return
            await self.clear_reactions(current_msg)

    @mods_only
    async def cmd_mute(self, server, author, mentions, leftover_args):
        """
        Usage {command_prefix}mute [@mention OR User ID] <time>
        Mutes ppl
        """
        seconds_to_mute = None
        if mentions:
            for user in mentions:
                leftover_args.pop(0)
        else:
            if len(leftover_args) == 2:
                user = discord.utils.get(server.members, id=leftover_args.pop(0))
                if user:
                    mentions = [user]
            if not mentions:
                raise CommandError('Invalid user specified')
        seconds_to_mute = timestamp_to_seconds(''.join(leftover_args))
        
        mutedrole = discord.utils.get(server.roles, id='120925729843183617')
        if not mutedrole:
            raise CommandError('No Muted role created')
        for user in mentions:
            try:
                await self.replace_roles(user, *[mutedrole])
                await self.server_voice_state(user, mute=True)
            except discord.Forbidden:
                raise CommandError('Not enough permissions to mute user : {}'.format(user.name))
            except:
                traceback.print_exc()
                raise CommandError('Unable to mute user defined:\n{}\n'.format(user.name))
        response = ':thumbsup:'
        
        for user in mentions:
            if seconds_to_mute:
                muted_datetime = datetime.utcnow() + timedelta(seconds = seconds_to_mute)
                self.muted_dict[user.id] = muted_datetime.timestamp()
                print('user {} now timed muted'.format(user.name))
                await self.safe_send_message(user, content=MUTED_MESSAGES['timed'].format(' '.join(leftover_args)))
                await self.safe_send_message(discord.Object(id='136130260637974529'), content='Muted user {} ({}) for {}.\nAction taken by {}#{}'.format(user.name, user.id, ' '.join(leftover_args), author.name, author.discriminator))
                asyncio.ensure_future(self.queue_timed_role(seconds_to_mute, user, mutedrole))
                response += ' muted for %s seconds' % seconds_to_mute
            else:
                await self.safe_send_message(user, content=MUTED_MESSAGES['plain'])
                await self.safe_send_message(discord.Object(id='136130260637974529'), content='Muted user {} ({}).\nAction taken by {}#{}'.format(user.name, user.id, author.name, author.discriminator))
                
        return Response(response) 

    @mods_only
    async def cmd_mmqueue(self, author, channel, server):
        """
        Usage {command_prefix}echo #channel "ENTER MESSAGE HERE"
        Fetches the help info for the bot's commands
        """
        unanswered_threads = [member_id for member_id in self.mod_mail_db if not self.mod_mail_db[member_id]['answered']]
        if not unanswered_threads:
            return Response('Everything is answered!')
        quick_switch_dict = {}
        for member_id in unanswered_threads:
            if not discord.utils.get(server.members, id=member_id):
                print 
            quick_switch_dict[member_id] = {'embed': discord.Embed(), 'member_obj': await self.get_user_info(member_id)}
            quick_switch_dict[member_id]['embed'].set_author(name='{}({})'.format(quick_switch_dict[member_id]['member_obj'].name, quick_switch_dict[member_id]['member_obj'].id), icon_url=quick_switch_dict[member_id]['member_obj'].avatar_url)
            od = collections.OrderedDict(sorted(self.mod_mail_db[member_id]['messages'].items(), reverse=True))
            od = collections.OrderedDict(islice(od.items(), 20))
            od = collections.OrderedDict(reversed(list(od.items())))
            for timestamp, msg_dict in od.items():
                user = None
                if msg_dict['modreply'] is not None:
                    user = discord.utils.get(server.members, id=msg_dict['modreply']).name
                else:
                    user = quick_switch_dict[member_id]['member_obj'].name
                if len(msg_dict['content']) > 1020:
                    msg_dict['content'] = msg_dict['content'][:1020] + '...'
                quick_switch_dict[member_id]['embed'].add_field(name='{} | *{}*'.format(user, datetime.utcfromtimestamp(float(timestamp)).strftime('%H:%M %d.%m.%y' )), value=msg_dict['content'], inline=False)
                
        current_index = 0
        current_msg = None
        loop_dict = list(collections.OrderedDict(quick_switch_dict.items()).values())
        while True:
            embed_object = loop_dict[current_index]['embed']
            embed_object.set_footer(text='{} / {}'.format(current_index+1, len(loop_dict)))
            
            if not current_msg: 
                current_msg = await self.safe_send_message(channel, embed=embed_object)
            else:
                current_msg = await self.safe_edit_message(current_msg, embed=embed_object)
            
            if current_index != 0:
                await self.add_reaction(current_msg, '⬅')
            await self.add_reaction(current_msg, '☑')
            if (current_index+1) != len(loop_dict):
                await self.add_reaction(current_msg, '➡')
                
            def check(reaction, user):
                e = str(reaction.emoji)
                if user != self.user:
                    return e.startswith(('⬅', '➡', '☑'))
                else:
                    return False
            
            reac = await self.wait_for_reaction(check=check, message=current_msg, timeout=300)
            
            if not reac:
                return
            elif str(reac.reaction.emoji) == '☑' and not self.mod_mail_db[loop_dict[current_index]['member_obj'].id]['answered']:
                self.mod_mail_db[loop_dict[current_index]['member_obj'].id]['answered'] = True
                if current_index == len(loop_dict):
                    current_index-=1
                    del loop_dict[current_index+1]
                else:
                    del loop_dict[current_index]
                if len(loop_dict) == 0:
                    await self.safe_delete_message(current_msg)
                    await self.safe_send_message(current_msg.channel, content='Everything is answered!')
                    return
                else:
                    await self.remove_reaction(current_msg, reac.reaction.emoji, reac.user)
            elif str(reac.reaction.emoji) == '⬅' and current_index != 0:
                current_index-=1
                await self.remove_reaction(current_msg, reac.reaction.emoji, reac.user)
            elif str(reac.reaction.emoji) == '➡' and current_index != len(loop_dict):
                current_index+=1
                await self.remove_reaction(current_msg, reac.reaction.emoji, reac.user)
            else:
                return
            await self.clear_reactions(current_msg)
    
    @mods_only
    async def cmd_modmail(self, author, server, auth_id, leftover_args):
        """
        Usage {command_prefix}echo #channel "ENTER MESSAGE HERE"
        Fetches the help info for the bot's commands
        """
        if [role for role in author.roles if role.id  in ["175657731426877440"]]:
            member = discord.utils.get(server.members, id=auth_id)
            if member:
                if leftover_args[0].lower() == 'anon':
                    msg_to_send = ' '.join(leftover_args[1:])
                    await self.safe_send_message(member, content='**Mods:** {}'.format(msg_to_send))
                    if member.id in self.mod_mail_db:
                        self.mod_mail_db[member.id]['messages']['{}'.format(datetime_to_utc_ts(datetime.now()))] = {'content': '(ANON){}'.format(msg_to_send), 'modreply': author.id}
                        self.mod_mail_db[member.id]['answered'] = True
                    else:
                        self.mod_mail_db[member.id] = {'answered': True, 'messages': {'{}'.format(datetime_to_utc_ts(datetime.now())): {'modreply': author.id,'content': '(ANON){}'.format(msg_to_send)}}}

                else:
                    msg_to_send = ' '.join(leftover_args)
                    await self.safe_send_message(member, content='**{}:** {}'.format(author.name, msg_to_send))
                    if member.id in self.mod_mail_db:
                        self.mod_mail_db[member.id]['messages']['{}'.format(datetime_to_utc_ts(datetime.now()))] = {'content': '{}'.format(msg_to_send), 'modreply': author.id}
                        self.mod_mail_db[member.id]['answered'] = True
                    else:
                        self.mod_mail_db[member.id] = {'answered': True, 'messages': {'{}'.format(datetime_to_utc_ts(datetime.now())): {'modreply': author.id,'content': '{}'.format(msg_to_send)}}}
                write_json('modmaildb.json', self.mod_mail_db)
                return Response(':thumbsup: Send this to {}:```{}```'.format(member.name, msg_to_send))
            else:
                raise CommandError('ERROR: User not found')

        
    @mods_only
    async def cmd_sendembeds(self):
        """
        Blah
        """
        print('here')
        em = discord.Embed(colour=discord.Colour(0x7FBC45), description="Use the reactions below to indicate each region / faction you're a part of.\nRed = Horde\nBlue = Alliance")
        em.set_author(name="Faction / Region Role Assignment")
        await self.safe_send_message(discord.Object(id='361717008313614337'), embed=em)
        print('here2')
        em = discord.Embed(colour=discord.Colour(0x7FBC45), description="Use the reactions below to indicate each class you play!")
        em.set_author(name="Class Role Assignment")
        await self.safe_send_message(discord.Object(id='361717008313614337'), embed=em)
        print('here3')
        em = discord.Embed(colour=discord.Colour(0x7FBC45), description="React below if you'd like to be pinged when any news regarding WoW is posted!")
        em.set_author(name="WoW News Toggle")
        await self.safe_send_message(discord.Object(id='361717008313614337'), embed=em)
        print('here4')
        em = discord.Embed(colour=discord.Colour(0x7FBC45), description="React below if you'd like to be pinged when any news regarding this discord server is posted!")
        em.set_author(name="Server News Toggle")
        await self.safe_send_message(discord.Object(id='361717008313614337'), embed=em)
        print('here5')

        
    @mods_only
    async def cmd_echo(self, author, message, server, channel, leftover_args):
        """
        Usage {command_prefix}echo #channel "ENTER MESSAGE HERE"
        Fetches the help info for the bot's commands
        """
        chan_mention = message.channel_mentions[0]
        leftover_args = leftover_args[1:]
        await self.safe_send_message(chan_mention, content=' '.join(leftover_args))
        return Response(':thumbsup:')

            
    async def on_reaction_remove(self, reaction, member):
        if not self.use_reactions: return
        if reaction.message.id in ['363250089176858624', '363250089172664322', '363250090166714369', '363250089793290241']:
            if reaction.emoji.id in self.reaction_pairings:
                member_roles = [discord.utils.get(member.server.roles, id=self.reaction_pairings[reaction.emoji.id])]
                if member_roles:
                    await self.remove_roles(member, *member_roles)        
                    
    async def on_reaction_add(self, reaction, member):
        if reaction.message.channel.id == '363245994714071040':
            print('{} : {}'.format(reaction.emoji.name, reaction.emoji.id))
        if not self.use_reactions: return
        if reaction.message.id in ['363250089176858624', '363250089172664322', '363250090166714369', '363250089793290241']:
            if reaction.emoji.id in self.reaction_pairings:
                member_roles = [discord.utils.get(member.server.roles, id=self.reaction_pairings[reaction.emoji.id])]
                if member_roles:
                    await self.add_roles(member, *member_roles)
            
        
    async def on_member_join(self, member):
        for role_id in self.channel_bans:
            if member.id in self.channel_bans[role_id]:
                member_roles = [discord.utils.get(member.server.roles, id=role_id)] + member.roles
                if member_roles:
                    await self.replace_roles(member, *member_roles)
        if member.id in self.muted_dict:
            member_roles = [discord.utils.get(member.server.roles, id='120925729843183617')]
            if member_roles:
                await self.replace_roles(member, *member_roles)

    async def on_member_update(self, before, after):        
        new_roles = [role for role in discord.utils.get(self.servers, id='113103747126747136').roles if role.name.startswith('Ban') and role.id not in self.channel_bans]
        if new_roles:
            print('Found %s new roles!' % len(new_roles))
            for role in new_roles:
                self.channel_bans[role.id] = [member.id for member in discord.utils.get(self.servers, id='113103747126747136').members if role in member.roles]
                write_json('channel_banned.json', self.channel_bans)
                
        if before.roles != after.roles:
            try:                
                if not [role for role in before.roles if role.id  in ["120925729843183617"]] and [role for role in after.roles if role.id  in ["120925729843183617"]]:
                    await asyncio.sleep(5)
                    if before.id not in self.muted_dict:
                        self.muted_dict[before.id] = None
                        print('user {} now no time muted'.format(before.name))
                    write_json('muted.json', self.muted_dict)
                if [role for role in before.roles if role.id  in ["120925729843183617"]] and not [role for role in after.roles if role.id  in ["120925729843183617"]]:
                    await asyncio.sleep(5)
                    if before.id in self.muted_dict:
                        del self.muted_dict[before.id]
                        print('user {} unmuted'.format(before.name))
                    write_json('muted.json', self.muted_dict)
                    
                for role_id in self.channel_bans:
                    if not [role for role in before.roles if role.id == role_id] and [role for role in after.roles if role.id == role_id]:
                        self.channel_bans[role_id].append(before.id)
                        print('user {} now channel banned'.format(before.name))
                        write_json('channel_banned.json', self.channel_bans)
                    if [role for role in before.roles if role.id == role_id] and not [role for role in after.roles if role.id == role_id]:
                        self.channel_bans[role_id].remove(before.id)
                        print('user {} no longer channel banned'.format(before.name))
                        write_json('channel_banned.json', self.channel_bans)
            except:
                pass

    async def on_message_edit(self, before, after):
        await self.on_message(after, edit=True)
        
    async def on_message(self, message, edit=False):
        if message.author == self.user:
            return
        
        if message.channel.is_private:
            print('pm')
            if [role for role in discord.utils.get(discord.utils.get(self.servers, id='113103747126747136').members, id=message.author.id).roles if role.id == '210518267515764737']:
                return
            if not edit: await self.safe_send_message(message.author, content='Thank you for your message! Our mod team will reply to you as soon as possible.')
            if message.attachments:
                if not message.content: 
                    msg_content = '-No content-'
                else:
                    msg_content = message.clean_content
                    
                if message.author.id in self.mod_mail_db:
                    self.mod_mail_db[message.author.id]['messages']['{}'.format(datetime_to_utc_ts(datetime.now()))] = {'content': '{}\n~ATTACHMENT:{}'.format(msg_content, ', '.join([attachment['url'] for attachment in message.attachments])), 'modreply': None}
                    self.mod_mail_db[message.author.id]['answered'] = False
                else:
                    self.mod_mail_db[message.author.id] = {'answered': False,'messages': {'{}'.format(datetime_to_utc_ts(datetime.now())): {'modreply': None,'content': '{}\n~ATTACHMENT:{}'.format(msg_content, ', '.join([attachment['url'] for attachment in message.attachments]))}}}
                if edit: 
                    await self.safe_send_message(discord.Object(id='304740929544388608'), content='**EDITED MSG From:** *{}*:\n```{}```\n~Attachments: {}\nReply ID: `{}`'.format(message.author.mention, msg_content, ', '.join([attachment['url'] for attachment in message.attachments]), message.author.id))
                else:
                    await self.safe_send_message(discord.Object(id='304740929544388608'), content='**From:** *{}*:\n```{}```\n~Attachments: {}\nReply ID: `{}`'.format(message.author.mention, msg_content, ', '.join([attachment['url'] for attachment in message.attachments]), message.author.id))
                
            else:
                if message.author.id in self.mod_mail_db:
                    self.mod_mail_db[message.author.id]['messages']['{}'.format(datetime_to_utc_ts(datetime.now()))] = {'content': '{}'.format(message.content), 'modreply': None}
                    self.mod_mail_db[message.author.id]['answered'] = False
                else:
                    self.mod_mail_db[message.author.id] = {'answered': False,'messages': {'{}'.format(datetime_to_utc_ts(datetime.now())): {'modreply': None,'content': '{}'.format(message.content)}}}
                if edit:
                    await self.safe_send_message(discord.Object(id='304740929544388608'), content='**EDITED MSG From:** *{}*:\n```{}```\nReply ID: `{}`'.format(message.author.mention, message.clean_content, message.author.id))
                else:
                    await self.safe_send_message(discord.Object(id='304740929544388608'), content='**From:** *{}*:\n```{}```\nReply ID: `{}`'.format(message.author.mention, message.clean_content, message.author.id))
            write_json('modmaildb.json', self.mod_mail_db)
            return
        
        if message.author.discriminator != '0000' and [role for role in message.author.roles if role.id == '210518267515764737']:
            return
        
        if message.channel.id == '151939221828009984' and ('$server' in message.content or '$game' in message.content):
            server_role = discord.utils.get(message.server.roles, id='363245195627724801')
            game_role = discord.utils.get(message.server.roles, id='363245289240264705')
            msg = message.content
            if '$server' in message.content:
                await self.edit_role(message.server, server_role, mentionable=True)
                msg = msg.replace('$server', server_role.mention)
            if '$game' in message.content:
                await self.edit_role(message.server, game_role, mentionable=True)
                msg = msg.replace('$game', game_role.mention)
            await self.safe_send_message(discord.Object(id='151939221828009984'), content=msg)
            await self.safe_delete_message(message)
            await asyncio.sleep(1)
            await self.edit_role(message.server, server_role, mentionable=False)
            await self.edit_role(message.server, game_role, mentionable=False)
            
        message_content = message.content.strip()
                        
        if not message_content.startswith(self.prefix):
            return
        try:
            command, *args = shlex.split(message.content.strip())
        except:
            command, *args = message.content.strip().split()
        command = command[len(self.prefix):].lower().strip()
        
        
        handler = getattr(self, 'cmd_%s' % command, None)
        if not handler:
            return

        print("[Command] {0.id}/{0.name} ({1})".format(message.author, message_content))

        argspec = inspect.signature(handler)
        params = argspec.parameters.copy()

        # noinspection PyBroadException
        try:
            handler_kwargs = {}
            if params.pop('message', None):
                handler_kwargs['message'] = message

            if params.pop('channel', None):
                handler_kwargs['channel'] = message.channel

            if params.pop('author', None):
                handler_kwargs['author'] = message.author

            if params.pop('server', None):
                handler_kwargs['server'] = message.server

            if params.pop('mentions', None):
                handler_kwargs['mentions'] = message.mentions

            if params.pop('leftover_args', None):
                            handler_kwargs['leftover_args'] = args
                            
            args_expected = []
            for key, param in list(params.items()):
                doc_key = '[%s=%s]' % (key, param.default) if param.default is not inspect.Parameter.empty else key
                args_expected.append(doc_key)

                if not args and param.default is not inspect.Parameter.empty:
                    params.pop(key)
                    continue

                if args:
                    arg_value = args.pop(0)
                    if arg_value.startswith('<@') or arg_value.startswith('<#'):
                        pass
                    else:
                        handler_kwargs[key] = arg_value
                        params.pop(key)

            if params:
                docs = getattr(handler, '__doc__', None)
                if not docs:
                    docs = 'Usage: {}{} {}'.format(
                        self.prefix,
                        command,
                        ' '.join(args_expected)
                    )

                docs = '\n'.join(l.strip() for l in docs.split('\n'))
                await self.safe_send_message(
                    message.channel,
                    content= '```\n%s\n```' % docs.format(command_prefix=self.prefix),
                             expire_in=15
                )
                return

            response = await handler(**handler_kwargs)
            if response and isinstance(response, Response):
                content = response.content
                if response.reply:
                    content = '%s, %s' % (message.author.mention, content)
                    
                if response.delete_after > 0:
                    await self.safe_delete_message(message)
                    sentmsg = await self.safe_send_message(message.channel, content=content, expire_in=response.delete_after)
                else:
                    sentmsg = await self.safe_send_message(message.channel, content=content)
                    
        except CommandError as e:
            await self.safe_send_message(message.channel, content='```\n%s\n```' % e.message, expire_in=15)

        except:
            await self.safe_send_message(message.channel, content='```\n%s\n```' % traceback.format_exc(), expire_in=60)
            traceback.print_exc()

if __name__ == '__main__':
    bot = WoWBot()
    bot.run()
