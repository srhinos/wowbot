import inspect
import traceback
import asyncio
import shlex
import discord
import aiohttp
import json
import logging
import sys
import collections
import re
import random

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
        self.token = ''
        self.tags = load_json('tags.json')
        self.mod_mail_db = load_json('modmaildb.json')
        self.muted_tracking = load_json('muted_tracking.json')
        self.restricted_tracking = load_json('restricted_tracking.json')
        self.restricted_db = load_json('restricted_db.json')
        self.tagblacklist = load_json('tagbl.json')
        self.since_id = {'BlizzardCS': 706894913959436288, 'Warcraft': 706894913959436288, 'WoWHead': 706894913959436288}
        self.start_time = datetime.utcnow()
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
        user_roles = user.roles
        if timed_role in user_roles:
            user_roles.remove(timed_role)
            await self.replace_roles(user, *user_roles)
            await self.server_voice_state(user, mute=False)

    async def mod_mail_reminders(self):
        while True:
            ticker = 0
            while ticker != 1800:
                await asyncio.sleep(1)
                if not [member_id for member_id in self.mod_mail_db if not self.mod_mail_db[member_id]['answered']]:
                    ticker = 0
                else:
                    ticker+=1
            await self.safe_send_message(discord.Object(id='141225778472943616'), content='There are **{}** unread items in the mod mail queue that\'re over a half hour old! Either run `!mmqueue` to see them and reply or mark them read using `!markread`!'.format(len([member_id for member_id in self.mod_mail_db if not self.mod_mail_db[member_id]['answered']])))

            
            
    async def on_ready(self):
        print('Connected!\n')
        print('Username: %s' % self.user.name)
        print('Bot ID: %s' % self.user.id)
        
        await self.change_presence(game=discord.Game(name='DM to contact staff!'))

        if self.servers:
            print('--Server List--')
            [print(s) for s in self.servers]
        else:
            print("No servers have been joined yet.")

        print()
        
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
    

    async def cmd_class(self, message, author, channel, leftover_args):
        """
        Usage {command_prefix}class class_name
        Gives you the role for the class based on the class_name you entered
        """
        class_name = ' '.join(leftover_args)
        if class_name.startswith('['):
            class_name = class_name.replace('[', '').replace(']', '')
        if class_name.lower() in ROLE_ALIASES:
            role = discord.utils.get(message.server.roles, id=ROLE_ALIASES[class_name.lower()])
        else:
            role = discord.utils.get(message.server.roles, name=class_name.lower())
        if not role or role.id in LOCK_ROLES:
            raise CommandError(CANNOT_SET)
            return
        author_roles = author.roles
        mod_check = [role for role in author_roles if role.id in LOCK_ROLES or role.id in LFG_ROLES.values()]
        
        if mod_check:
            for roles in author.roles:
                if roles.id not in LOCK_ROLES and not roles.is_everyone:
                    author_roles.remove(roles)
            author_roles.append(role)
            print('giving role {} to mod {}'.format(role.name, message.author.name.encode('ascii', 'ignore').decode('ascii')))
            await self.replace_roles(message.author, *author_roles)
        else:
            print('giving role {} to user {}'.format(role.name, message.author.name.encode('ascii', 'ignore').decode('ascii')))
            await self.replace_roles(message.author, role)   
        return Response('you now are marked with the class `%s`!' % role.name, reply=True, delete_after=15)    
                                                                                                 
    async def cmd_tag(self, message, author, channel, mentions, leftover_args):
        """
        Usage {command_prefix}tag tag name
        Gets a tag from the database of tags and returns it in chat for all to see.
        
        Usage {command_prefix}tag list
        Sends you a PM listing all tags in the tag database
        
        Usage {command_prefix}tag [+, add, -, remove,  blacklist]
        Mod only commands, ask rhino if you dont know the full syntax
        """
        if int(author.id) in self.tagblacklist:
            return
        switch = leftover_args.pop(0).lower()
        if switch in ['+', 'add', '-', 'remove', 'list', 'blacklist']:
            if switch in ['+', 'add']:
                if [role for role in author.roles if role.id  in ["175657731426877440"]]:
                    if len(leftover_args) == 2:
                        if len(leftover_args[0]) > 200 or len(leftover_args[1]) > 1750:
                            raise CommandError('Tag length too long')
                        self.tags[leftover_args[0].lower()] = [False, leftover_args[1]]
                        write_json('tags.json', self.tags)
                        return Response('Tag \"%s\" created' % clean_bad_pings(leftover_args[0]), delete_after=15)
                    elif len(leftover_args) == 3 and 'restrict' in leftover_args[0]:
                        if len(leftover_args[1]) > 200 or len(leftover_args[2]) > 1750:
                            raise CommandError('Tag length too long')
                        self.tags[leftover_args[1].lower()] = [True, leftover_args[2]]
                        write_json('tags.json', self.tags)
                        return Response('Tag \"%s\" created' % clean_bad_pings(leftover_args[1]), delete_after=15)
                        
                    else:
                        print(leftover_args)
                        raise CommandError('Bad input')
            elif switch == 'list':
                try:
                    this = sorted(list(self.tags.keys()), key=str.lower)
                    new_this = [this[0]]
                    for elem in this[1:]:
                        if len(new_this[-1]) + len(elem) < 70:
                            new_this[-1] = new_this[-1] + ', ' + elem
                        else:
                            new_this.append(elem)
                    final = clean_bad_pings('%s' % '\n'.join(new_this))
                    if len(final) > 1800:
                        final_this = [new_this[0]]
                        for elem in new_this[1:]:
                            if len(final_this[-1]) + len(elem) < 1800:
                                final_this[-1] = final_this[-1] + '\n' + elem
                            else:
                                final_this.append(elem)
                        for x in final_this:
                            await self.safe_send_message(author, content=x)
                    else:
                        await self.safe_send_message(author, content=final)
                except Exception as e:
                    print(e)
            elif switch == 'blacklist':
                if [role for role in author.roles if role.id  in ["175657731426877440"]]:
                    for user in mentions:
                        self.tagblacklist.append(int(user.id))
                        return Response('User `{}` was blacklisted'.format(clean_bad_pings(user.name)), delete_after=20)
            else:
                if [role for role in author.roles if role.id  in ["175657731426877440"]]:
                    try:
                        del self.tags[' '.join(leftover_args)]
                        write_json('tags.json', self.tags)
                        return Response('Tag \"%s\" removed' % clean_bad_pings(' '.join(leftover_args)), delete_after=10)
                    except:
                        raise CommandError('Tag doesn\'t exist to be removed')
        else:
            msg = False
            if leftover_args:
                tag_name = '{} {}'.format(switch, ' '.join(leftover_args))
            else:
                tag_name = switch
            for tag in self.tags:
                if tag_name.lower() == tag.lower():
                    if self.tags[tag][0]:
                        if channel.id != '210522691852173312' and not [role for role in author.roles if role.id  in ["175657731426877440"]]:
                            return Response('Tag cannot be used in this channel please use <#210522691852173312>')
                    return Response(clean_bad_pings(self.tags[tag][1]))
            raise CommandError('Tag doesn\'t exist')
    
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
                    user = discord.utils.get(server.members, id=msg_dict['modreply']).name
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
    async def cmd_mute(self, message, server, author, mentions, leftover_args):
        """
        Usage: {command_prefix}mute @UserName <time>
        Mutes the user(s) listed. If a time is defined then add
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
        print(seconds_to_mute)
        
        mutedrole = discord.utils.get(server.roles, id='120925729843183617')
        if not mutedrole:
            raise CommandError('No Muted role created')
        for user in mentions:
            try:
                await self.add_roles(user, mutedrole)
                await self.server_voice_state(user, mute=True)
            except discord.Forbidden:
                raise CommandError('Not enough permissions to mute user : {}'.format(user.name))
            except:
                raise CommandError('Unable to mute user defined:\n{}\n'.format(user.name))
        response = ':thumbsup:'
        if seconds_to_mute:
            for user in mentions:
                asyncio.ensure_future(self.queue_timed_role(seconds_to_mute, user, mutedrole))
                response += ' muted for %s seconds' % seconds_to_mute
        return Response(response) 
            
    @mods_only
    async def cmd_punish(self, message, server, author, mentions, leftover_args):
        """
        Usage: {command_prefix}mute @UserName <time>
        Mutes the user(s) listed. If a time is defined then add
        """
        seconds_to_punish = None
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
        if len(leftover_args) == 1:
            seconds_to_mute = timestamp_to_seconds(''.join(leftover_args))
        
        punishedrole = discord.utils.get(server.roles, id='210518267515764737')
        if not punishedrole:
            raise CommandError('No Muted role created')
        for user in mentions:
            try:
                await self.add_roles(user, punishedrole)
                await self.server_voice_state(user, mute=True)
            except discord.Forbidden:
                raise CommandError('Not enough permissions to mute user : {}'.format(user.name))
            except:
                raise CommandError('Unable to mute user defined:\n{}\n'.format(user.name))
        response = ':thumbsup:'
        if seconds_to_punish:
            await asyncio.sleep(float(seconds_to_punish))
            for user in mentions:
                asyncio.ensure_future(self.queue_timed_role(seconds_to_punish, user, punishedrole))
                response += ' muted for %s seconds' % seconds_to_punish
        return Response(':thumbsup:') 
                        
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
                if leftover_args[0] == 'anon':
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
    async def cmd_echo(self, author, message, server, channel, leftover_args):
        """
        Usage {command_prefix}echo #channel "ENTER MESSAGE HERE"
        Fetches the help info for the bot's commands
        """
        chan_mentions = message.channel_mentions
        for chan in chan_mentions:
            await self.safe_send_message(chan, content=' '.join(leftover_args))
        return Response(':thumbsup:')

            
    async def on_member_join(self, member):
        if member.id in self.restricted_tracking:
            member_roles = [discord.utils.get(member.server.roles, id='210518267515764737')]
            if member_roles:
                await self.replace_roles(member, *member_roles)
        elif member.id in self.restricted_tracking:
            member_roles = [discord.utils.get(member.server.roles, id='210518267515764737')]
            if member_roles:
                await self.replace_roles(member, *member_roles)

    async def on_member_update(self, before, after):
        if before.roles != after.roles:
            try:
                if not [role for role in before.roles if role.id  in ["210518267515764737"]] and [role for role in after.roles if role.id  in ["210518267515764737"]]:
                    self.restricted_tracking.append(before.id)
                    self.restricted_db.append(before.id)
                    print('user {} now restricted'.format(before.name))
                    write_json('restricted_tracking.json', self.restricted_tracking)
                    write_json('restricted_db.json', self.restricted_db)
                if [role for role in before.roles if role.id  in ["210518267515764737"]] and not [role for role in after.roles if role.id  in ["210518267515764737"]]:
                    self.restricted_tracking.remove(before.id)
                    print('user {} now not restricted'.format(before.name))
                    write_json('restricted_tracking.json', self.restricted_tracking)
                if not [role for role in before.roles if role.id  in ["120925729843183617"]] and [role for role in after.roles if role.id  in ["120925729843183617"]]:
                    self.muted_tracking.remove(before.id)
                    print('user {} now muted'.format(before.name))
                    write_json('sd_bl.json', self.muted_tracking)
                if [role for role in before.roles if role.id  in ["120925729843183617"]] and not [role for role in after.roles if role.id  in ["120925729843183617"]]:
                    self.muted_tracking.append(before.id)
                    print('user {} no longer muted'.format(before.name))
                    write_json('sd_bl.json', self.muted_tracking)
            except:
                pass
    async def on_message(self, message):
        if message.author == self.user:
            return
        
        if message.channel.is_private:
            print('pm')
            if [role for role in discord.utils.get(discord.utils.get(self.servers, id='113103747126747136').members, id=message.author.id).roles if role.id == '210518267515764737']:
                return
            await self.safe_send_message(message.author, content='Thank you for your message! Our mod team will reply to you as soon as possible.')
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
                
                if message.author.id in self.restricted_db:
                    await self.safe_send_message(discord.Object(id='304740929544388608'), content='**From:** *{}*:\n```{}```\n~Attachments: {}\n**__WARNING: USER PREVIOUSLY RESTRICTED__**\nReply ID: `{}`'.format(message.author.mention, msg_content, ', '.join([attachment['url'] for attachment in message.attachments]), message.author.id))
                else:
                    await self.safe_send_message(discord.Object(id='304740929544388608'), content='**From:** *{}*:\n```{}```\n~Attachments: {}\nReply ID: `{}`'.format(message.author.mention, msg_content, ', '.join([attachment['url'] for attachment in message.attachments]), message.author.id))
                
            else:
                if message.author.id in self.mod_mail_db:
                    self.mod_mail_db[message.author.id]['messages']['{}'.format(datetime_to_utc_ts(datetime.now()))] = {'content': '{}'.format(message.content), 'modreply': None}
                    self.mod_mail_db[message.author.id]['answered'] = False
                else:
                    self.mod_mail_db[message.author.id] = {'answered': False,'messages': {'{}'.format(datetime_to_utc_ts(datetime.now())): {'modreply': None,'content': '{}'.format(message.content)}}}

                if message.author.id in self.restricted_db:
                    await self.safe_send_message(discord.Object(id='304740929544388608'), content='**From:** *{}*:\n```{}```\n**__WARNING: USER PREVIOUSLY RESTRICTED__**\nReply ID: `{}`'.format(message.author.mention, message.clean_content, message.author.id))
                else:
                    await self.safe_send_message(discord.Object(id='304740929544388608'), content='**From:** *{}*:\n```{}```\nReply ID: `{}`'.format(message.author.mention, message.clean_content, message.author.id))
            write_json('modmaildb.json', self.mod_mail_db)
            return
            
        if [role for role in message.author.roles if role.id == '210518267515764737']:
            return

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
            class_name = message.content.strip()[1:]
            if class_name.startswith('['):
                class_name = class_name.replace('[', '').replace(']', '')
            if class_name.lower() in ROLE_ALIASES:
                role = discord.utils.get(message.server.roles, id=ROLE_ALIASES[class_name.lower()])
            else:
                role = discord.utils.get(message.server.roles, name=class_name.lower())
                if not role:
                    for pattern in ROLE_REGEX:
                        patt = re.compile(pattern)
                        if patt.match(class_name.lower()):
                            role = discord.utils.get(message.server.roles, id=ROLE_REGEX[pattern])
            if not role or role.id in LOCK_ROLES:
                return
            author_roles = message.author.roles
            mod_check = [role for role in author_roles if role.id in LOCK_ROLES or role.id in LFG_ROLES.values()]
            if role.id in LFG_ROLES.values():
                author_roles.append(role)
                await self.replace_roles(message.author, *author_roles)
                await self.safe_delete_message(message)
                await self.safe_send_message(message.channel, content='%s, you now are marked with the role `%s`!' % (message.author.mention, role.name), expire_in=15)
                print("[Command] {0.id}/{0.name} ({1})".format(message.author, message_content))
                return
            elif mod_check:
                author_roles = [role for role in author_roles if role.id in LOCK_ROLES or role.id in LFG_ROLES.values()]
                author_roles.append(role)
                await self.replace_roles(message.author, *author_roles)
            else:
                await self.replace_roles(message.author, role)
            await self.safe_delete_message(message)
            await self.safe_send_message(message.channel, content='%s, you now are marked with the class `%s`!' % (message.author.mention, role.name), expire_in=15)
            print("[Command] {0.id}/{0.name} ({1})".format(message.author, message_content))
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
