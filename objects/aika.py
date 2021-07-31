# -*- coding: utf-8 -*-

import asyncio
import time
import traceback
from collections import defaultdict
from typing import Optional
from typing import Union

import aiohttp
import discord
import orjson
from cmyui.logging import Ansi
from cmyui.logging import log
from cmyui.mysql import AsyncSQLPool
from cmyui.version import Version
from discord.ext import commands
from discord.ext import tasks

from utils import asciify
from utils import truncate

__all__ = (
    'Leaderboard',
    'ContextWrap',
    'Aika'
)

AKATSUKI_API__ONLINE_USERS = 'http://144.217.254.156:5001/api/v1/onlineUsers'

class Leaderboard:
    """A simple class to create simple readable key: value pair
    leaderboards which can be pretty-printed for output in Discord.
    """
    __slots__ = ('data', 'max_keylen')

    def __init__(self, **kwargs) -> None:
        self.data = kwargs.pop('data', {})
        self.max_keylen = kwargs.pop('max_keylen', 0)

    def update(self, d) -> None:
        self.data.update(d)

    def __repr__(self) -> str:
        # Maximum lenth of an ID as a string.
        # Only needs to work for 1-2, so optimized.
        idx_maxlen = 2 if len(self.data) > 9 else 1

        # Maximum length of a key.
        if self.max_keylen:
            # Make sure the length does not exceed `self.max_keylen` chars
            keylen = min(self.max_keylen, max(len(k) for k in self.data))
        else:
            # Keys can be of any length.
            keylen = max(len(k) for k in self.data)

        # Generate the lines of our leaderboard.
        lines = []

        for idx, (k, v) in enumerate(self.data.items()):
            # Truncate key if max length is specified.
            if keylen:
                k = truncate(k, keylen)

            lines.append(
                '{i:0>{ilen}}. {k:^{klen}} - {v}'.format(
                i = idx + 1, k = asciify(k), v = v,
                ilen = idx_maxlen, klen = keylen
            ))

        # Put the leaderboard all together,
        # and display it with markdown syntax.
        return '```md\n{}```'.format('\n'.join(lines))

# Light wrapper around commands.Context to allow for one of Aika's
# special features: the ability to edit previous messages to edit
# Aika's response (and specifically for Aika to be able to edit
# their previous) response rather than just creating a new one.
# With: ctx.send(...) // Without: self.bot.send(ctx, ...)
class ContextWrap(commands.Context):
    async def send(self, *args, **kwargs) -> Optional[discord.Message]:
        # Allows for the syntax `ctx.send('content')`
        if len(args) == 1 and isinstance(args[0], str):
            kwargs['content'] = args[0]

        # Clear previous msg params.
        kwargs['embed'] = kwargs.pop('embed', None)
        kwargs['content'] = kwargs.pop('content', None)

        cached = self.bot.cache['responses'][self.message.id]

        if cached and (time.time() - cached['timeout']) <= 0:
            # We have cache and it's not expired.
            msg = cached['resp']
            await msg.edit(**kwargs)
        else: # We either have no cached val, or it's expired.
            msg = await super().send(**kwargs)

            self.bot.cache['responses'][self.message.id] = {
                'resp': msg,
                'timeout': int(time.time()) + 300 # 5 min
            }

        return msg

class Aika(commands.Bot):
    __slots__ = ('db', 'http', 'cache', 'version', 'uptime')

    def __init__(self, **kwargs) -> None:
        super().__init__(
            owner_id = self.config.discord_owner,
            command_prefix = self.when_mentioned_or_prefix(),
            help_command = None, **kwargs
        )

        self.db: Optional[AsyncSQLPool] = None
        self.http_sess: Optional[aiohttp.ClientSession] = None

        # Various types of cache
        # for different applications.
        self.cache = {
            # whenever aika replies to a command, cache
            # {msgid: {'timeout': sent+5min, 'msg': resp}}
            'responses': defaultdict(lambda: None),
            # keep all data from aika_guilds cached from startup
            'guilds': {}, # {guildid: {guild_info ...}, ...}
            # keep all chatxp wait times in cache.
            'chatxp': {} # {(discordid, guildid): timeout, ...}
        }

        self.version = Version(1, 1, 5)
        self.uptime: Optional[int] = None

    def when_mentioned_or_prefix(self):
        def inner(bot, msg):
            prefix = self.cache['guilds'][msg.guild.id]['cmd_prefix']
            return commands.when_mentioned_or(prefix)(bot, msg)

        return inner

    ##########
    # Events #
    ##########

    async def on_guild_join(self, guild: discord.Guild) -> None:
        await self.wait_until_ready()

        # insert new guild into sql.
        await self.db.execute(
            'INSERT INTO aika_guilds '
            '(guildid) VALUES (%s)',
            [guild.id]
        )

        # add it to the cache.
        # XXX: i'm fetching from sql simply because
        # i don't care to update this every time i
        # add something to the table for 1ms gain..
        res = await self.db.fetch(
            'SELECT * FROM aika_guilds '
            'WHERE guildid = %s',
            [guild.id]
        )

        self.cache['guilds'][guild.id] = {
            k: res[k] for k in set(res) - {'guildid'}
        }

    async def on_guild_remove(self, guild: discord.Guild) -> None:
        await self.wait_until_ready()

        # Delete from database.
        # TODO: maybe don't..? needs more consideration
        await self.db.execute(
            'DELETE FROM aika_guilds '
            'WHERE guildid = %s',
            [guild.id]
        )

        # Remove from cache.
        del self.cache['guilds'][guild.id]

    async def on_message(self, msg: discord.Message) -> None:
        await self.wait_until_ready()

        if not msg.content or msg.author.bot:
            return

        # filter messages in akatsuki
        if msg.guild.id == self.config.akatsuki['id']:
            if await self.filter_content(msg.content.lower()):
                return await msg.delete()

        if self.config.server_build or await self.is_owner(msg.author):
            await self.process_commands(msg)

    async def on_message_edit(self, before: discord.Message,
                              after: discord.Message) -> None:
        await self.wait_until_ready()

        if not after.content or after.author.bot:
            return

        if after.content == before.content:
            return

        # filter messages in akatsuki
        if after.guild.id == self.config.akatsuki['id']:
            if await self.filter_content(after.content.lower()):
                return await after.delete()

        if self.config.server_build or await self.is_owner(after.author):
            await self.process_commands(after)

    async def on_message_delete(self, msg: discord.Message) -> None:
        # Whenever a message is deleted, check if it was in
        # our cache, and delete it (so they don't accumulate).
        cached = self.cache['responses'][msg.id]

        if cached:
            try:
                await cached['resp'].delete()
            except discord.NotFound: # No 403 since it's our own message.
                pass # Response has already been deleted.

            del self.cache['responses'][msg.id]

    async def on_member_ban(self, guild: discord.Guild,
                            user: Union[discord.Member, discord.User]) -> None:
        log(f'{user} was banned from {guild}.', Ansi.GREEN)

    async def enqueue_mutes(self) -> None:
        res = await self.db.fetchall(
            'SELECT discordid, guildid, muted_until '
            'FROM aika_users WHERE muted_until != 0'
        )

        async def reset_mute(discordid: int, guildid: int) -> None:
            await self.db.execute(
                'UPDATE aika_users SET muted_until = 0 '
                'WHERE discordid = %s and guildid = %s',
                [discordid, guildid]
            )

        for row in res:
            # get the guild
            if not (g := self.get_guild(row['guildid'])):
                await reset_mute(row['discordid'], row['guildid'])
                continue

            # get the member
            if not (m := g.get_member(row['discordid'])):
                await reset_mute(row['discordid'], row['guildid'])
                continue

            # get the muted role
            if not (r := discord.utils.get(g.roles, name='muted')):
                await reset_mute(row['discordid'], row['guildid'])
                continue

            duration = max(0, time.time() - row['muted_until'])

            # Enqueue the task to remove their mute when complete.
            self.loop.create_task(self.remove_role_in(m, duration, r))

    async def add_new_guilds(self) -> None:
        for guild in self.guilds:
            if guild.id in self.cache['guilds']:
                continue # we already have this guild

            # Guild not in our cache (or sql).

            # insert the new guild into sql
            await self.db.execute(
                'INSERT INTO aika_guilds '
                '(guildid) VALUES (%s)',
                [guild.id]
            )

            # add it to the cache
            # XXX: i'm fetching from sql simply because
            # i don't care to update this every time i
            # add something to the table for 1ms gain..
            res = await self.db.fetch(
                'SELECT * FROM aika_guilds '
                'WHERE guildid = %s',
                [guild.id]
            )

            self.cache['guilds'][guild.id] = {
                k: res[k] for k in set(res) - {'guildid'}
            }

    async def on_ready(self) -> None:
        # TODO: maybe use datetime module rather than this w/ formatting?
        if not self.uptime:
            self.uptime = time.time()

        # add any guild newly joined while
        # the bot was offline to sql.
        await self.add_new_guilds()

        # load all pending mutes
        # from sql into tasks
        await self.enqueue_mutes()

        print('{col}Ready{reset}: {user} ({userid})'.format(
              col = repr(Ansi.GREEN), reset = repr(Ansi.RESET),
              user = self.user, userid = self.user.id))

    #async def on_error(self, event, *args, **kwargs) -> None:
    #    if event != 'on_message':
    #        print(f'{Ansi.LRED!r}ERR{Ansi.RESET!r}: '
    #              f'{event} ({args} {kwargs})')

    async def on_command_error(self, ctx: ContextWrap,
                               error: commands.CommandError) -> None:
        if hasattr(ctx.command, 'on_error'):
            return

        ignored = (commands.CommandNotFound,
                   commands.UserInputError,
                   commands.NotOwner)

        error = getattr(error, 'original', error)

        if isinstance(error, ignored):
            return

        elif isinstance(error, commands.DisabledCommand):
            return await ctx.send(f'{ctx.command} is currently disabled.')

        elif isinstance(error, commands.NoPrivateMessage):
            try:
                return await ctx.author.send(f'{ctx.command} can only be used in guilds.')
            except discord.errors.Forbidden:
                # user is not accepting our dms
                pass

        elif isinstance(error, commands.CommandOnCooldown):
            return await ctx.send(
                f'{ctx.author.mention} that commands is still '
                f'on cooldown ({error:.1f}s)'
            )

        elif isinstance(error, commands.BotMissingPermissions):
            return await ctx.send('I have insufficient guild permissions to perform that command.')

        elif isinstance(error, commands.MissingPermissions):
            return await ctx.send('You have insufficient guild permissions to perform that command.')

        elif isinstance(error, commands.CheckFailure):
            return # Someone tried using an akatsuki-limited command outside.

        print(f'Ignoring exception in command {ctx.command}')
        traceback.print_exception(type(error), error, error.__traceback__)

    ########
    # Misc #
    ########

    async def process_commands(self, message):
        if not message.author.bot:
            ctx = await self.get_context(message, cls=ContextWrap)
            await self.invoke(ctx)

    #########
    # Utils #
    #########

    @staticmethod
    async def add_role_in(member: discord.Member,
                          duration: int, *roles) -> None:
        await asyncio.sleep(duration)
        await member.add_roles(*roles)

    @staticmethod
    async def remove_role_in(member: discord.Member,
                             duration: int, *roles) -> None:
        await asyncio.sleep(duration)
        await member.remove_roles(*roles)

    async def filter_content(self, msg: str) -> bool:
        if not (self.config.filters or self.config.substring_filters):
            return False # filters disabled

        return (any(f in msg for f in self.config.substring_filters) or
                any(s in self.config.filters for s in msg.split(' ')))

    @tasks.loop(seconds=15)
    async def bg_loop(self) -> None:
        await self.wait_until_ready()

        akat_url = 'http://144.217.254.156:5001/api/v1/onlineUsers'
        async with self.http_sess.get(AKATSUKI_API__ONLINE_USERS) as r:
            if r.status == 200:
                online = (await r.json(content_type=None))['result']
            else:
                online = 0

        await self.change_presence(
            activity = discord.Game(f'Akat: {online}, Servers: {len(self.guilds)}'),
            status = discord.Status.online
        )

    def run(self, *args, **kwargs) -> None:
        async def runner() -> None:
            # get our db connection & http client
            self.db = AsyncSQLPool()
            await self.db.connect(self.config.mysql)
            log('Connected to mysql.', Ansi.GREEN)

            self.http_sess = aiohttp.ClientSession(json_serialize=orjson.dumps)

            # load guild settings into cache
            self.cache['guilds'] = {
                row['guildid']: {k: row[k] for k in set(row) - {'guildid'}}
                for row in await self.db.fetchall('SELECT * FROM aika_guilds')
            }

            try: # load all of Aika's enabled cogs.
                for ext in self.config.initial_extensions:
                    self.load_extension(f'cogs.{ext}')
            except:
                print(f'Failed to load extension {ext}.')
                raise RuntimeError(f'Failed to load extension {ext}.')

            try:
                # start the bot in discordpy
                await self.start(self.config.discord_token,
                                 *args, **kwargs)
            finally:
                # clean up any active sessions
                await self.http_sess.close()

                self.db.pool.close()
                await self.db.pool.wait_closed()

                await self.close()

        loop = asyncio.get_event_loop()
        loop.create_task(runner())

        try:
            self.bg_loop.start()
            loop.run_forever()
        finally:
            self.bg_loop.cancel()

    config = __import__('config')
