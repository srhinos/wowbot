import inspect
import traceback
import asyncio
import shlex
import discord

from TwitterAPI import TwitterAPI

from wowbot.constants import HELP_MSG, LOCK_ROLES, CANNOT_SET
from .exceptions import CommandError
from .utils import clean_string, write_json, load_json
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
        self.tagblacklist = load_json('tagbl.json')
        self.since_id = {'BlizzardCS': 706894913959436288, 'Warcraft': 706894913959436288}
        self.twitAPI = TwitterAPI('',
                                  '',
                                  '',
                                  '')
        print('past init')

    # noinspection PyMethodOverriding
    def run(self):
        loop = asyncio.get_event_loop()
        try:
            loop.create_task(self.get_tweets())
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

    async def on_ready(self):
        print('Connected!\n')
        print('Username: %s' % self.user.name)
        print('Bot ID: %s' % self.user.id)

        if self.servers:
            print('--Server List--')
            [print(s) for s in self.servers]
        else:
            print("No servers have been joined yet.")

        print()
        
    async def get_tweets(self):
        await self.wait_until_ready()
        r = self.twitAPI.request('statuses/user_timeline', {'screen_name': 'BlizzardCS',
                                                                    'exclude_replies': True,
                                                                    'include_rts': False,
                                                                    'count': 10})
        for item in r.get_iterator():
            print('in ID 1')
            if item['id'] > self.since_id['BlizzardCS']:
                self.since_id['BlizzardCS'] = item['id']

        r = self.twitAPI.request('statuses/user_timeline', {'screen_name': 'Warcraft',
                                                                    'exclude_replies': True,
                                                                    'include_rts': False,
                                                                    'count': 10})
        for item in r.get_iterator():
            print('in ID 2')
            if item['id'] > self.since_id['Warcraft']:
                self.since_id['Warcraft'] = item['id']
        while not self.is_closed:
            try:
                r = self.twitAPI.request('statuses/user_timeline', {'screen_name': 'Warcraft',
                                                                    'exclude_replies': True,
                                                                    'count': 1})
                for item in r.get_iterator():
                    if 'text' in item and item['id'] > self.since_id['Warcraft']:
                        self.since_id['Warcraft'] = item['id']
                        await self.safe_send_message(discord.Object(id='114381487943450632'),
                                                clean_string('***{}*** tweeted - \"*{}*\"\n***https://twitter.com/{}/status/{}***'.format(
                            item["user"]['name'], item['text'], item["user"]['screen_name'], item['id']
                        )))

                r = self.twitAPI.request('statuses/user_timeline', {'screen_name': 'BlizzardCS',
                                                                    'exclude_replies': True,
                                                                    'count': 1})
                for item in r.get_iterator():
                    strings = ['#D3', 'D3', '#Hearthstone', 'Hearthstone', '#Overwatch', 'Overwatch', 'Heroes',
                               '#Heroes', '#HS', '#SC2', 'SC2']
                    if 'text' in item and item['id'] > self.since_id['BlizzardCS']:
                        if not any(x.lower() in item['text'].lower() for x in strings) or any(x.lower() in item['text'].lower() for x in ['WoW', 'Warcraft', 'BNet']):
                            self.since_id['BlizzardCS'] = item['id']
                            await self.safe_send_message(discord.Object(id='114381487943450632'),
                                                    clean_string('***{}*** tweeted - \"*{}*\"\n***https://twitter.com/{}/status/{}***'.format(
                                item["user"]['name'], item['text'], item["user"]['screen_name'], item['id']
                            )))
                await asyncio.sleep(30)
            except:
                print('error handled, fuck twitter API')

    async def _wait_delete_msg(self, message, after):
        await asyncio.sleep(after)
        await self.safe_delete_message(message)

    async def safe_send_message(self, dest, content, *, tts=False, expire_in=0, quiet=False):
        msg = None
        try:
            msg = await self.send_message(dest, content, tts=tts)

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

    async def safe_edit_message(self, message, new, *, expire_in=0, send_if_fail=False, quiet=False):
        msg = None
        try:
            msg = await self.edit_message(message, new)

            if msg and expire_in:
                asyncio.ensure_future(self._wait_delete_msg(msg, expire_in))

        except discord.NotFound:
            if not quiet:
                print("Warning: Cannot edit message \"%s\", message not found" % message.clean_content)
            if send_if_fail:
                if not quiet:
                    print("Sending instead")
                msg = await self.safe_send_message(message.channel, new)
        finally:
            if msg: return msg


    async def cmd_restart(self, channel, author):
        """
        Usage: {command_prefix}logout
        Forces a logout
        """
        for roles in message.author.roles:
            if roles.id  == "175657731426877440":
                await self.safe_send_message(message.channel, "Restarting....")
                await self.logout()


    async def cmd_clear(self, message, author, channel):
        """
        Usage {command_prefix}clear
        Removes all removable roles from a user.
        """
        author_roles = author.roles
        mod_check = [role for role in author_roles if role.id in LOCK_ROLES]
        
        if mod_check:
            for roles in author.roles:
                if roles.id not in LOCK_ROLES and not roles.is_everyone:
                    author_roles.remove(roles)
        else:
            author_roles = []
        await self.replace_roles(author, *author_roles)
        return Response('I\'ve removed all classes from you!', reply=True, delete_after=15)
    
    async def cmd_class(self, message, author, channel, leftover_args):
        """
        Usage {command_prefix}class class_name
        Gives you the role for the class based on the class_name you entered
        """
        class_name = ' '.join(leftover_args)
        if class_name.startswith('['):
            class_name = class_name.replace('[', '').replace(']', '')
        role = discord.utils.get(message.server.roles, name=class_name.lower())
        if not role or role.id in LOCK_ROLES:
            raise CommandError(CANNOT_SET)
            return
        author_roles = author.roles
        mod_check = [role for role in author_roles if role.id in LOCK_ROLES]
        
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
                                                                                                 
    async def cmd_tag(self, message, author, channel, mentions, switch, leftover_args):
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
        switch = switch.lower()
        if switch in ['+', 'add', '-', 'remove', 'list', 'blacklist']:
            if switch in ['+', 'add']:
                if [role for role in author.roles if role.id  in ["175657731426877440"]]:
                    if len(leftover_args) == 2:
                        if len(leftover_args[0]) > 200 or len(leftover_args[1]) > 1750:
                            raise CommandError('Tag length too long')
                        self.tags[leftover_args[0].lower()] = leftover_args[1]
                        write_json('tags.json', self.tags)
                        return Response('Tag \"%s\" created' % clean_string(leftover_args[0]), delete_after=15)
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
                    final = clean_string('%s' % '\n'.join(new_this))
                    if len(final) > 1800:
                        final_this = [new_this[0]]
                        for elem in new_this[1:]:
                            if len(final_this[-1]) + len(elem) < 1800:
                                final_this[-1] = final_this[-1] + '\n' + elem
                            else:
                                final_this.append(elem)
                        for x in final_this:
                            await self.safe_send_message(author, x)
                    else:
                        await self.safe_send_message(author, final)
                except Exception as e:
                    print(e)
            elif switch == 'blacklist':
                if [role for role in author.roles if role.id  in ["175657731426877440"]]:
                    for user in mentions:
                        self.tagblacklist.append(int(user.id))
                        return Response('User `{}` was blacklisted'.format(clean_string(user.name)), delete_after=20)
            else:
                if [role for role in author.roles if role.id  in ["175657731426877440"]]:
                    try:
                        del self.tags[' '.join(leftover_args)]
                        write_json('tags.json', self.tags)
                        return Response('Tag \"%s\" removed' % clean_string(' '.join(leftover_args)), delete_after=10)
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
                    return Response(clean_string(self.tags[tag]))
            raise CommandError('Tag doesn\'t exist')
    
    async def cmd_help(self, message, server, channel):
        """
        Usage {command_prefix}help
        Fetches the help info for the bot's commands
        """
        final_role_names = ', '.join([rc.name for rc in server.roles if rc.id not in LOCK_ROLES and not rc.is_everyone])
        return Response(HELP_MSG.format(self.prefix, final_role_names), delete_after=120)

    async def cmd_echo(self, author, message, server, channel, msg):
        """
        Usage {command_prefix}help
        Fetches the help info for the bot's commands
        """
        if [role for role in author.roles if role.id  in ["175657731426877440"]]:
            chan_mentions = message.channel_mentions
            for chan in chan_mentions:
                await self.safe_send_message(chan, msg)
            return Response(':thumbsup:')

    async def on_message(self, message):
        if message.author == self.user:
            return

        message_content = message.content.strip()
        if not message_content.startswith(self.prefix):
            return

        command, *args = shlex.split(message.content.strip())
        command = command[len(self.prefix):].lower().strip()

        for arg in list(args):
            if arg.startswith('<@'):
                args.remove(arg)
            if arg.startswith('<#'):
                args.remove(arg)
        
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
                    '```\n%s\n```' % docs.format(command_prefix=self.prefix),
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
                    sentmsg = await self.safe_send_message(message.channel, content, expire_in=response.delete_after)
                else:
                    sentmsg = await self.safe_send_message(message.channel, content)
                    
        except CommandError as e:
            await self.safe_send_message(message.channel, '```\n%s\n```' % e.message, expire_in=15)

        except:
            await self.safe_send_message(message.channel, '```\n%s\n```' % traceback.format_exc(), expire_in=60)
            traceback.print_exc()


if __name__ == '__main__':
    bot = WoWBot()
    bot.run()
