import asyncio
import discord
import shlex
import json
import re

from TwitterAPI import TwitterAPI
from wowbot.constants import helpmsg, lockroles, cannotset

def write_json(filename, contents):
    with open(filename, 'w') as outfile:
        outfile.write(json.dumps(contents, indent=2))

def load_json(filename):
    try:
        with open(filename, encoding='utf-8') as f:
            return json.loads(f.read())

    except IOError as e:
        print("Error loading", filename, e)
        return []


def clean_string(string):
    string = re.sub('@', '@\u200b', string)
    string = re.sub('#', '#\u200b', string)
    return string

class WoWBot(discord.Client):
    def __init__(self):
        super().__init__()
        self.prefix = '!'
        self.token = 'TOKEN'
        self.tags = load_json('tags.json')
        self.tagblacklist = load_json('tagbl.json')

        self.since_id = {'BlizzardCS': 706894913959436288, 'Warcraft': 706894913959436288}
        self.twitAPI = TwitterAPI('TOKEN')

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
        print('Username: ' + self.user.name)
        print('ID: ' + self.user.id)
        print('--Server List--')
        for server in self.servers:
            print(server.name)

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
                        await self.send_message(discord.Object(id='114381487943450632'),
                                                '***{}*** tweeted - \"*{}*\"\n***https://twitter.com/{}/status/{}***'.format(
                            item["user"]['name'], item['text'], item["user"]['screen_name'], item['id']
                        ))

                r = self.twitAPI.request('statuses/user_timeline', {'screen_name': 'BlizzardCS',
                                                                    'exclude_replies': True,
                                                                    'count': 1})
                for item in r.get_iterator():
                    strings = ['#D3', 'D3', '#Hearthstone', 'Hearthstone', '#Overwatch', 'Overwatch', 'Heroes',
                               '#Heroes', '#HS', '#SC2', 'SC2']
                    if 'text' in item and item['id'] > self.since_id['BlizzardCS']:
                        if not any(x.lower() in item['text'].lower() for x in strings) or any(x.lower() in item['text'].lower() for x in ['WoW', 'Warcraft', 'BNet']):
                            self.since_id['BlizzardCS'] = item['id']
                            await self.send_message(discord.Object(id='114381487943450632'),
                                                    '***{}*** tweeted - \"*{}*\"\n***https://twitter.com/{}/status/{}***'.format(
                                item["user"]['name'], item['text'], item["user"]['screen_name'], item['id']
                            ))
                await asyncio.sleep(10)
            except:
                print('error handled, fuck twitter API')

    async def timed_message(self, channel, ogmsg, message_content):
        timedmsg = await self.send_message(channel, message_content)
        await asyncio.sleep(120)
        await self.delete_message(timedmsg)
        await self.delete_message(ogmsg)

    async def on_message(self, message):
        if message.author == self.user:
            return
        if message.channel.is_private:
            return
        if [role for role in message.author.roles if role in ['120925729843183617', '210518267515764737']]:
            return
        if message.content.strip().startswith(self.prefix):
            try:
                command, *args = shlex.split(message.content.strip())
            except:
                args = None
                command = message.content.strip()

            if command in [self.prefix + 'help']:
                await self.delete_message(message)
                final_role_names = ''
                for role_to_check in message.server.roles:
                    if role_to_check.id not in lockroles and not role_to_check.is_everyone:
                        final_role_names += '{}, '.format(role_to_check.name)
                final_role_names = final_role_names[:len(final_role_names)-2]
                wowbothelpmessage = None
                async for msg in self.logs_from(message.channel, 1):
                    if msg.author.id == '114749194102636544':
                        wowbothelpmessage = msg
                await self.timed_message(message.channel, message, helpmsg.format(self.prefix, final_role_names))
                if wowbothelpmessage:
                    await self.delete_message(wowbothelpmessage)

            elif command in [self.prefix + 'restart']:
                print('here')
                for roles in message.author.roles:
                    if roles.id  == "175657731426877440":
                        await self.send_message(message.channel, "Restarting....")
                        await self.logout()

            elif command in [self.prefix + 'tag']:
                if len(args) == 0:
                    await self.timed_message(message.channel, message, 'Usage to add tag: {0}tag [+ / add] '
                                                                       '[\"Tag Name\"] [\"Tag Content\"]\n\n'
                                                                       'Usage to view tag: {0}tag [\"Tag Name\"]\n\n'
                                                                       'Usage to view all tags: {0}tag list'
                                                                       ''.format(self.prefix))
                    return
                if int(message.author.id) in self.tagblacklist:
                    return
                if len(args) > 0 and args[0].lower() in ['+', 'add', '-', 'remove', 'list', 'blacklist']:
                    if args[0] in ['+', 'add']:
                        if [role for role in message.author.roles if role.id  in ["175657731426877440"]]:
                            if len(args) == 3:
                                if len(args[1]) > 200 or len(args[2]) > 1750:
                                    await self.timed_message(message.channel, message, 'Tag length too long')
                                    return
                                self.tags[args[1].lower()] = args[2]
                                write_json('tags.json', self.tags)
                                await self.timed_message(message.channel, message, 'Tag \"%s\" created' % clean_string(args[1]))
                            else:
                                await self.timed_message(message.channel, message, 'Bad input')
                    elif args[0] == 'list':
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
                                    await self.send_message(message.author, x)
                            else:
                                await self.send_message(message.author, final)
                        except Exception as e:
                            print(e)
                    elif args[0] == 'blacklist':
                        if [role for role in message.author.roles if role.id  in ["175657731426877440"]]:
                            for user in message.mentions:
                                self.tagblacklist.append(int(user.id))
                                await self.timed_message(message.channel, message, 'User `{}` was blacklisted'.format(clean_string(user.name)))
                    else:
                        if [role for role in message.author.roles if role.id  in ["175657731426877440"]]:
                            try:
                                del self.tags[args[1]]
                                write_json('tags.json', self.tags)
                                await self.timed_message(message.channel, message, 'Tag \"%s\" removed' % clean_string(args[1]))
                            except:
                                await self.timed_message(message.channel, message, 'Tag doesn\'t exist to be removed')
                else:
                    msg = False
                    for tag in self.tags:
                        if args[0].lower() == tag.lower():
                            await self.timed_message(message.channel, message, clean_string(self.tags[tag]))
                            msg = True
                            break
                    if not msg:
                        await self.timed_message(message.channel, message, 'Tag doesn\'t exist')

            elif command in [self.prefix + 'clear']:
                is_mod = False
                author_roles = message.author.roles

                for role_to_check in author_roles:
                    if role_to_check.name in lockroles:
                        is_mod = True

                if is_mod:
                    for roles in message.author.roles:
                        if roles.id not in lockroles and not roles.is_everyone:
                            author_roles.remove(roles)
                    print('removing roles from mod {}'.format(message.author.name.encode('ascii', 'ignore').decode('ascii')))
                    await self.replace_roles(message.author, *author_roles)
                else:
                    print('removing roles from user {}'.format(message.author.name.encode('ascii', 'ignore').decode('ascii')))
                    self.replace_roles(message.author, message.server.default_role)
                await self.delete_message(message)
                await self.timed_message(message.channel, message, '<@{}>, I\'ve removed all classes from you!'
                                                                   ''.format(message.author.id))

            elif command in [self.prefix + 'class']:
                if not args:
                    await self.timed_message(message.channel, message, cannotset)
                    return

                rolename = ' '.join(args).lower()
                role = discord.utils.get(message.server.roles, name=rolename)

                if not role:
                    await self.timed_message(message.channel, message, cannotset)
                    return

                if role.id in lockroles:
                    await self.timed_message(message.channel, message, cannotset)
                    return

                is_mod = False
                author_roles = message.author.roles
                for role_to_check in author_roles:
                    if role_to_check.id in lockroles:
                        is_mod = True

                if is_mod:
                    for roles in message.author.roles:
                        if roles.id not in lockroles and not roles.is_everyone:
                            author_roles.remove(roles)
                    author_roles.append(role)
                    print('giving role {} to mod {}'.format(role.name, message.author.name.encode('ascii', 'ignore').decode('ascii')))
                    await self.replace_roles(message.author, *author_roles)
                else:
                    print('giving role {} to user {}'.format(role.name, message.author.name.encode('ascii', 'ignore').decode('ascii')))
                    await self.replace_roles(message.author, role)
                await self.delete_message(message)
                await self.timed_message(message.channel, message,
                                         '<@{}>, you now are marked with the class `{}`!'.format(message.author.id,
                                                                                                 role.name))

if __name__ == '__main__':
    bot = WoWBot()
    bot.run()
