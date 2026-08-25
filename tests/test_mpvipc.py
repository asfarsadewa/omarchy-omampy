"""The mpv JSON IPC protocol, exercised against a fake socket."""

import json
import unittest

from omampy import mpvipc


class FakeSocket:
    """A scripted stand-in for a connected unix socket.

    `replies` is a list of byte chunks handed out one `recv` at a time, so a
    test can split a message across reads and check the buffering.
    """

    def __init__(self, replies=(), fail_on_send=None):
        self.replies = list(replies)
        self.sent = []
        self.closed = False
        self.fail_on_send = fail_on_send

    def sendall(self, payload):
        if self.fail_on_send:
            raise self.fail_on_send
        self.sent.append(payload)

    def recv(self, _size):
        return self.replies.pop(0) if self.replies else b""

    def close(self):
        self.closed = True

    def settimeout(self, _value):
        pass


def client(replies=(), **kwargs):
    fake = FakeSocket(replies, **kwargs)
    return mpvipc.MpvClient("/fake.sock", connector=lambda _p, _t: fake), fake


def reply(data, request_id=1, error="success"):
    return (json.dumps({"data": data, "request_id": request_id, "error": error})
            + "\n").encode()


class EncodeTests(unittest.TestCase):
    def test_a_command_is_one_json_line(self):
        payload = mpvipc.encode(["get_property", "pause"], 3)
        self.assertTrue(payload.endswith(b"\n"))
        self.assertEqual(json.loads(payload), {"command": ["get_property", "pause"],
                                               "request_id": 3})

    def test_arguments_keep_their_types(self):
        payload = json.loads(mpvipc.encode(["set_property", "volume", 42.5], 1))
        self.assertEqual(payload["command"][2], 42.5)

    def test_unicode_survives_encoding(self):
        payload = json.loads(mpvipc.encode(["loadfile", "/m/東京.mp3"], 1))
        self.assertEqual(payload["command"][1], "/m/東京.mp3")


class DecodeTests(unittest.TestCase):
    def test_complete_lines_are_returned(self):
        messages, rest = mpvipc.decode(b'{"a":1}\n{"b":2}\n')
        self.assertEqual(messages, [{"a": 1}, {"b": 2}])
        self.assertEqual(rest, b"")

    def test_a_partial_line_is_kept_for_later(self):
        messages, rest = mpvipc.decode(b'{"a":1}\n{"b"')
        self.assertEqual(messages, [{"a": 1}])
        self.assertEqual(rest, b'{"b"')

    def test_unparseable_lines_are_skipped(self):
        messages, _ = mpvipc.decode(b'garbage\n{"a":1}\n')
        self.assertEqual(messages, [{"a": 1}])

    def test_blank_lines_are_skipped(self):
        messages, _ = mpvipc.decode(b'\n\n{"a":1}\n')
        self.assertEqual(messages, [{"a": 1}])

    def test_non_object_json_is_skipped(self):
        messages, _ = mpvipc.decode(b'[1,2]\n{"a":1}\n')
        self.assertEqual(messages, [{"a": 1}])

    def test_an_empty_buffer_yields_nothing(self):
        self.assertEqual(mpvipc.decode(b""), ([], b""))


class ResponseMatchingTests(unittest.TestCase):
    def test_a_matching_reply_is_a_response(self):
        self.assertTrue(mpvipc.is_response({"request_id": 4, "error": "success"}, 4))

    def test_another_request_is_not(self):
        self.assertFalse(mpvipc.is_response({"request_id": 5}, 4))

    def test_an_event_is_never_a_response(self):
        self.assertFalse(mpvipc.is_response({"event": "seek", "request_id": 4}, 4))


class ClientTests(unittest.TestCase):
    def test_a_command_is_sent_and_its_data_returned(self):
        mpv, fake = client([reply(True)])
        self.assertIs(mpv.command("get_property", "pause"), True)
        self.assertEqual(json.loads(fake.sent[0])["command"], ["get_property", "pause"])

    def test_events_before_the_reply_are_ignored(self):
        mpv, _ = client([b'{"event":"seek"}\n', b'{"event":"file-loaded"}\n', reply(7)])
        self.assertEqual(mpv.command("get_property", "playlist-count"), 7)

    def test_a_reply_split_across_reads_is_reassembled(self):
        whole = reply("ok")
        mpv, _ = client([whole[:9], whole[9:]])
        self.assertEqual(mpv.command("get_property", "path"), "ok")

    def test_a_stale_reply_from_an_earlier_request_is_ignored(self):
        mpv, _ = client([reply("old", request_id=0), reply("new")])
        self.assertEqual(mpv.command("get_property", "path"), "new")

    def test_request_ids_advance(self):
        mpv, fake = client([reply(1), reply(2, request_id=2)])
        mpv.command("get_property", "a")
        mpv.command("get_property", "b")
        ids = [json.loads(payload)["request_id"] for payload in fake.sent]
        self.assertEqual(ids, [1, 2])

    def test_an_error_reply_raises_and_names_the_command(self):
        mpv, _ = client([reply(None, error="property not found")])
        with self.assertRaises(mpvipc.MpvError) as caught:
            mpv.command("get_property", "nonsense")
        self.assertIn("nonsense", str(caught.exception))
        self.assertIn("property not found", str(caught.exception))

    def test_a_closed_connection_raises(self):
        mpv, _ = client([])
        with self.assertRaises(mpvipc.MpvError):
            mpv.command("get_property", "pause")

    def test_a_send_failure_raises_and_drops_the_socket(self):
        mpv, fake = client([], fail_on_send=OSError("broken pipe"))
        with self.assertRaises(mpvipc.MpvError):
            mpv.command("get_property", "pause")
        self.assertTrue(fake.closed)

    def test_get_returns_the_default_when_mpv_refuses(self):
        mpv, _ = client([reply(None, error="property unavailable")])
        self.assertEqual(mpv.get("duration", 0.0), 0.0)

    def test_get_many_skips_what_it_cannot_read(self):
        mpv, _ = client([reply(True), reply(None, request_id=2, error="nope"),
                         reply(9, request_id=3)])
        self.assertEqual(mpv.get_many(["pause", "gone", "playlist-count"]),
                         {"pause": True, "playlist-count": 9})

    def test_set_sends_a_set_property_command(self):
        mpv, fake = client([reply(None)])
        mpv.set("volume", 30)
        self.assertEqual(json.loads(fake.sent[0])["command"], ["set_property", "volume", 30])

    def test_a_missing_socket_raises_not_running(self):
        mpv = mpvipc.MpvClient("/fake.sock",
                               connector=lambda _p, _t: (_ for _ in ()).throw(FileNotFoundError()))
        with self.assertRaises(mpvipc.NotRunning):
            mpv.connect()

    def test_a_refused_connection_raises_not_running(self):
        mpv = mpvipc.MpvClient(
            "/fake.sock",
            connector=lambda _p, _t: (_ for _ in ()).throw(ConnectionRefusedError()))
        with self.assertRaises(mpvipc.NotRunning):
            mpv.connect()

    def test_not_running_is_a_lost_connection(self):
        self.assertTrue(issubclass(mpvipc.NotRunning, mpvipc.ConnectionLost))
        self.assertTrue(issubclass(mpvipc.ConnectionLost, mpvipc.MpvError))

    def test_get_does_not_swallow_a_lost_connection(self):
        # Silently handing back the default for every property would make a
        # dead receiver look like a live one sitting idle.
        mpv, _ = client([])
        with self.assertRaises(mpvipc.ConnectionLost):
            mpv.get("pause", "fallback")

    def test_get_many_stops_at_a_lost_connection(self):
        mpv, _ = client([reply(True)])
        with self.assertRaises(mpvipc.ConnectionLost):
            mpv.get_many(["pause", "duration"])

    def test_a_send_failure_is_a_lost_connection(self):
        mpv, _ = client([], fail_on_send=OSError("broken pipe"))
        with self.assertRaises(mpvipc.ConnectionLost):
            mpv.get("pause")

    def test_a_refused_property_is_still_only_a_refusal(self):
        mpv, _ = client([reply(None, error="property not found"), reply(5, request_id=2)])
        self.assertEqual(mpv.get("nonsense", "fallback"), "fallback")
        self.assertEqual(mpv.get("playlist-count"), 5)

    def test_connecting_twice_reuses_the_socket(self):
        opened = []

        def connector(_path, _timeout):
            fake = FakeSocket([reply(True)])
            opened.append(fake)
            return fake

        mpv = mpvipc.MpvClient("/fake.sock", connector=connector)
        mpv.connect()
        mpv.connect()
        self.assertEqual(len(opened), 1)

    def test_the_context_manager_closes_the_socket(self):
        fake = FakeSocket([reply(True)])
        with mpvipc.MpvClient("/fake.sock", connector=lambda _p, _t: fake) as mpv:
            mpv.command("get_property", "pause")
        self.assertTrue(fake.closed)

    def test_closing_twice_is_harmless(self):
        mpv, fake = client([reply(True)])
        mpv.connect()
        mpv.close()
        mpv.close()
        self.assertTrue(fake.closed)


class SocketReadyTests(unittest.TestCase):
    def test_a_path_that_does_not_exist_is_not_ready(self):
        self.assertFalse(mpvipc.socket_ready("/definitely/not/here.sock"))

    def test_an_empty_path_is_not_ready(self):
        self.assertFalse(mpvipc.socket_ready(""))

    def test_a_plain_file_is_not_a_live_socket(self):
        import tempfile
        with tempfile.NamedTemporaryFile() as handle:
            self.assertFalse(mpvipc.socket_ready(handle.name))


if __name__ == "__main__":
    unittest.main()
