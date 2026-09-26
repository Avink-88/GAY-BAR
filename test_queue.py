import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import DCBOT as app


class QueueTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        app.music_queues.clear()
        self.state = app.queue_for(1)
        self.channel = SimpleNamespace(send=AsyncMock())
        self.voice = MagicMock()
        self.voice.is_connected.return_value = True
        self.voice.channel = object()
        self.voice.disconnect = AsyncMock()
        self.state.voice = self.voice
        self.ctx = SimpleNamespace(
            guild=SimpleNamespace(id=1), voice_client=self.voice,
            author=SimpleNamespace(voice=SimpleNamespace(channel=self.voice.channel)),
            channel=self.channel, send=AsyncMock())
        self.callbacks = []
        self.voice.play.side_effect = lambda source, after: self.callbacks.append(after)
        self.voice.stop.side_effect = lambda: self.callbacks[-1](None) if self.callbacks else None
        self.extract = AsyncMock(side_effect=lambda url, **kw: SimpleNamespace(title=url, cleanup=MagicMock()))
        self.patcher = patch.object(app.YTDLSource, 'from_url', self.extract)
        self.patcher.start()
        self.metadata = AsyncMock(side_effect=lambda url, **kw: {'title': 'Title ' + url, 'webpage_url': url})
        self.metadata_patcher = patch.object(app.YTDLSource, 'extract_info', self.metadata)
        self.metadata_patcher.start()

    async def asyncTearDown(self):
        await self.state.cancel()
        self.patcher.stop()
        self.metadata_patcher.stop()

    async def settle(self):
        for _ in range(12):
            await asyncio.sleep(0)

    async def enqueue(self):
        await app.play.callback(self.ctx, url='first')
        await self.settle()
        await app.play.callback(self.ctx, url='second')
        await self.settle()

    async def test_fifo_lazy_extraction_and_thread_callback(self):
        await self.enqueue()
        self.assertEqual(self.extract.await_count, 1)
        await asyncio.to_thread(self.callbacks[0], None)
        await self.settle()
        self.assertEqual(self.state.current, 'second')
        self.assertEqual(self.extract.await_count, 2)
        self.callbacks[1](None)
        await self.settle()
        self.assertIsNone(self.state.current)
        self.assertTrue(self.state.task.done())

    async def test_skip_advances_once(self):
        await self.enqueue()
        await app.skip.callback(self.ctx)
        await self.settle()
        self.assertEqual(self.state.current, 'second')
        self.assertEqual(self.voice.play.call_count, 2)

    async def test_clear_keeps_current(self):
        await self.enqueue()
        await app.clear.callback(self.ctx)
        self.assertEqual(self.state.current, 'first')
        self.assertFalse(self.state.pending)
        self.voice.stop.assert_not_called()

    async def test_leave_clears_without_restart(self):
        await self.enqueue()
        await app.leave.callback(self.ctx)
        await self.settle()
        self.assertFalse(self.state.pending)
        self.assertIsNone(self.state.current)
        self.assertEqual(self.voice.play.call_count, 1)
        self.voice.disconnect.assert_awaited_once()

    async def test_failed_track_continues(self):
        self.extract.side_effect = [ValueError('unavailable'), SimpleNamespace(title='second')]
        self.state.pending.extend([('bad', self.channel, 'Bad title'), ('second', self.channel, 'Second title')])
        self.state.start()
        await self.settle()
        self.assertEqual(self.state.current, 'second')
        self.assertEqual(self.voice.play.call_count, 1)

    async def test_skip_during_extraction(self):
        async def extract(url, **kwargs):
            if url == 'first':
                await asyncio.Event().wait()
            return SimpleNamespace(title=url)
        self.extract.side_effect = extract
        await self.enqueue()
        await app.skip.callback(self.ctx)
        await self.settle()
        self.assertEqual(self.state.current, 'second')
        self.assertEqual(self.voice.play.call_count, 1)

    async def test_server_isolation_and_wrong_channel(self):
        await self.enqueue()
        self.assertFalse(app.queue_for(2).pending)
        self.ctx.author.voice.channel = object()
        await app.clear.callback(self.ctx)
        self.assertEqual(len(self.state.pending), 1)

    async def test_queue_displays_title_not_url(self):
        await self.enqueue()
        await app.show_queue.callback(self.ctx)
        text = str(self.ctx.send.call_args.kwargs['embed'].to_dict())
        self.assertIn('1. Title second', text)
        self.assertNotIn('1. second', text)

    async def test_metadata_failure_does_not_enqueue(self):
        self.metadata.side_effect = ValueError('missing video')
        await app.play.callback(self.ctx, url='bad')
        self.assertFalse(self.state.pending)
        self.extract.assert_not_awaited()

    async def test_queue_pagination(self):
        self.state.pending.extend((str(i), self.channel, f'Song {i}') for i in range(1, 22))
        await app.show_queue.callback(self.ctx, '2')
        text = str(self.ctx.send.call_args.kwargs['embed'].to_dict())
        self.assertIn('11. Song 11', text)
        self.assertIn('20. Song 20', text)
        self.assertNotIn('21. Song 21', text)
        self.assertFalse(self.ctx.send.call_args.kwargs['view'].previous.disabled)
        self.assertFalse(self.ctx.send.call_args.kwargs['view'].next_page.disabled)
        await app.show_queue.callback(self.ctx, '3')
        text = str(self.ctx.send.call_args.kwargs['embed'].to_dict())
        self.assertIn('21. Song 21', text)
        self.assertNotIn('!queue 4', text)

    async def test_queue_invalid_pages_and_empty(self):
        for page in ('0', '-1', '2', 'abc'):
            self.ctx.send.reset_mock()
            await app.show_queue.callback(self.ctx, page)
            self.ctx.send.assert_awaited_once()
        await app.show_queue.callback(self.ctx)
        self.assertIn('1/1', str(self.ctx.send.call_args.kwargs['embed'].to_dict()))

    async def test_search_plays_selected_page_not_repeated_search(self):
        self.metadata.return_value = {'title': 'Selected title', 'webpage_url': 'https://youtu.be/selected'}
        self.metadata.side_effect = None
        await app.play.callback(self.ctx, url='search words')
        await self.settle()
        self.extract.assert_awaited_once_with('https://youtu.be/selected', stream=True)

    async def test_card_buttons_refresh_shrinking_queue_and_timeout(self):
        self.state.pending.extend((str(i), self.channel, f'Song {i}') for i in range(21))
        view = app.QueueView(1)
        view.render()
        self.assertTrue(view.previous.disabled)
        interaction = SimpleNamespace(response=SimpleNamespace(defer=AsyncMock()),
                                      edit_original_response=AsyncMock())
        await view.next_page.callback(interaction)
        self.assertEqual(view.page, 2)
        interaction.edit_original_response.assert_awaited_once()
        self.state.pending.clear()
        await view.refresh.callback(interaction)
        self.assertEqual(view.page, 1)
        self.assertTrue(view.next_page.disabled)
        view.message = SimpleNamespace(edit=AsyncMock())
        await view.on_timeout()
        self.assertTrue(all(button.disabled for button in view.children))
        view.message.edit.assert_awaited_once()
        view.stop()

    async def test_help_card_contains_all_commands(self):
        await app.show_help.callback(self.ctx)
        embed = self.ctx.send.call_args.kwargs['embed']
        text = str(embed.to_dict())
        for command in ('!play', '!queue', '!skip', '!clear', '!leave', '!hello', '!help'):
            self.assertIn(command, text)
        self.assertLess(len(embed), 6000)


if __name__ == '__main__':
    unittest.main()
