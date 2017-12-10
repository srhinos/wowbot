import inspect
import traceback
import asyncio
import shlex
import discord
import aiohttp
import concurrent.futures

from TwitterAPI import TwitterAPI
from datetime import datetime, timedelta

from wowbot.constants import HELP_MSG, LOCK_ROLES, CANNOT_SET, ROLE_ALIASES
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
        self.since_id = {'BlizzardCS': 826248627739885568, 'Warcraft': 826248627739885568, 'WoWHead': 826248627739885568}
        self.start_time = datetime.utcnow()
        self.debug = True
        self.twitAPI = TwitterAPI('',
                                  '',
                                  '',
                                  '')
        print('past init')
        
    async def uptime_check(self):
        if datetime.utcnow() - timedelta(hours=24) > self.start_time:
            print('daily reboot time')
            os._exit(0)
            
    # noinspection PyMethodOverriding
    def run(self):
        loop = asyncio.get_event_loop()
        try:
            loop.create_task(self.uptime_check())
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
        
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=3)
        loop = asyncio.get_event_loop()
        
        def get_twitter_data(twitter_handle):
            return self.twitAPI.request('statuses/user_timeline', {'screen_name': twitter_handle,
                                                                    'exclude_replies': True,
                                                                    'include_rts': False,
                                                                    'tweet_mode': "extended",
                                                                    'count': 1})
        for handle in self.since_id.keys():
            future = loop.run_in_executor(executor, get_twitter_data, handle)
        
            r = await future
            for item in r.get_iterator():
                print('got recent tweet for ' + handle)
                if item['id'] > self.since_id[handle]:
                    self.since_id[handle] = item['id']
                
        while not self.is_closed:
            try:
                for handle in self.since_id.keys():
                    if self.debug: print('checking ' + handle)
                    future = loop.run_in_executor(executor, get_twitter_data, handle)
                    
                    r = await future
                    for item in r.get_iterator():
                        if 'text' in item and item['id'] > self.since_id[handle]:
                            if handle in ['BlizzardCS']:
                                strings = ['#D3', 'D3', '#Hearthstone', 'Hearthstone', '#Overwatch', 'Overwatch', 'Heroes', '#Heroes', '#HS', '#SC2', 'SC2', 'RT @']
                            else:
                                strings = ['RT @']
                            if not any(x.lower() in item['text'].lower() for x in strings) or any(x.lower() in item['text'].lower() for x in ['WoW', 'Blizzcon', 'Warcraft', 'BNet', 'WarcraftDevs']):
                                if self.debug: print('posting tweet by ' + handle)
                                self.since_id[handle] = item['id']
                                embed = await self.generate_tweet_embed(item)
                                await self.safe_send_message(discord.Object(id='114381487943450632'), embed=embed)
                    await asyncio.sleep(5)
            except:
                traceback.print_exc()

                
                
    async def generate_tweet_embed(self, resp):
        final_text = None
        image_url = None
        
        if 'media' in resp["entities"]:
            if len(resp["entities"]["media"]) == 1:
                for media in resp["entities"]["media"]:
                    if not final_text:
                        final_text = clean_string(resp["text"]).replace(media["url"], '')
                    else:
                        final_text = final_text.replace(media["url"], '')
                    image_url = media["media_url_https"]
        if 'urls' in resp["entities"]:
            for url in resp["entities"]["urls"]:
                if not final_text:
                    final_text = clean_string(resp["text"]).replace(url["url"], '[{0}]({1})'.format(url["display_url"], url["expanded_url"]))
                else:
                    final_text = final_text.replace(url["url"], '[{0}]({1})'.format(url["display_url"], url["expanded_url"]))
        if not final_text:
            final_text = clean_string(resp["text"])
        
        date_time = datetime.strptime(resp["created_at"], "%a %b %d %H:%M:%S +0000 %Y")
        em = discord.Embed(colour=discord.Colour(0x00aced), description=final_text, timestamp=date_time)
        if image_url:
            em.set_image(url=image_url)
        em.set_author(name=resp["user"]['screen_name'], url='https://twitter.com/{}/status/{}'.format(resp["user"]["screen_name"], resp["id"]), icon_url=resp["user"]["profile_image_url_https"])
        return em

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
            
    async def on_message(self, message):
        if message.content == '!tping':
            await self.safe_send_message(message.channel, content='pong! \:D')
        if message.content == '!embedtest':
            em = discord.Embed(colour=discord.Colour(0x56d696), description='test', timestamp=datetime.utcnow())
            await self.safe_send_message(message.channel, embed=em)

if __name__ == '__main__':
    bot = WoWBot()
    bot.run()
