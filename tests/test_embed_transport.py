"""Deterministic regressions for the private, trusted embed socket transport.

Run with: python -m unittest discover -s tests -p test_embed_transport.py
No external server or subprocess is used.
"""
import io
import pickle
import socket
import struct
import threading
import unittest
from unittest import mock
from types import SimpleNamespace

from veusz import embed, embed_remote, qtall as qt
from veusz.embed import Embedded
from veusz.embed_remote import EmbedApplication


class FragmentSocket:
    """Exercise legal stream fragmentation without timing-dependent sleeps."""

    def __init__(self, data=b'', fragment=1):
        self.data = data
        self.fragment = fragment
        self.output = bytearray()
        self.eof_seen = False

    def recv(self, count):
        if not self.data:
            # Fail old code deterministically instead of hanging the test suite.
            if self.eof_seen:
                raise AssertionError('recv retried after EOF (infinite loop)')
            self.eof_seen = True
            return b''
        result = self.data[:min(count, self.fragment)]
        self.data = self.data[len(result):]
        return result

    def send(self, data):
        count = min(len(data), self.fragment)
        self.output.extend(data[:count])
        return count


def frame(value):
    data = pickle.dumps(value, 2)
    return struct.pack('<I', len(data)) + data


class TransportTests(unittest.TestCase):
    def test_posix_passes_only_child_socket_descriptor(self):
        class Client(Embedded):
            socket2 = mock.Mock()
        Client.socket2.fileno.return_value = 42
        with mock.patch.object(embed.sys, 'platform', 'linux'), \
             mock.patch.object(embed.os.path, 'isfile', return_value=True), \
             mock.patch.object(embed, 'findOnPath', return_value=None), \
             mock.patch.object(embed.subprocess, 'Popen') as popen:
            Client.makeRemoteProcess(False)
            self.assertTrue(popen.call_args.kwargs['close_fds'])
            self.assertEqual(popen.call_args.kwargs['pass_fds'], (42,))

    def test_posix_socketpair_is_not_made_globally_inheritable(self):
        class Client(Embedded):
            pass
        parent, child = mock.Mock(), mock.Mock()
        child.fileno.return_value = 42
        with mock.patch.object(embed.sys, 'platform', 'linux'), \
             mock.patch.object(socket, 'AF_UNIX', 1, create=True), \
             mock.patch.object(socket, 'socketpair', return_value=(parent, child)), \
             mock.patch.object(embed.os, 'set_inheritable') as inheritable:
            sock, params, waitaccept = Client.makeSockets()
        self.assertIs(sock, parent)
        self.assertEqual(params, b'unix 42\n')
        self.assertFalse(waitaccept)
        inheritable.assert_not_called()

    def test_remote_owns_inherited_descriptor_without_duplication(self):
        with mock.patch.object(embed_remote.sys, 'stdin', io.StringIO('unix 42\nsecret\n')), \
             mock.patch.object(socket, 'AF_UNIX', 1, create=True), \
             mock.patch.object(socket, 'socket') as constructor, \
             mock.patch.object(socket, 'fromfd', create=True) as fromfd, \
             mock.patch.object(embed_remote, 'EmbedApplication') as application:
            embed_remote.runremote()
            constructor.assert_called_once_with(
                socket.AF_UNIX, socket.SOCK_STREAM, fileno=42)
            constructor.return_value.set_inheritable.assert_called_once_with(False)
            fromfd.assert_not_called()
            application.writeToSocket.assert_called_once_with(
                constructor.return_value, b'secret\n')

    def test_failed_authentication_cleans_up_and_allows_restart(self):
        class Client(Embedded):
            pass
        listener, accepted, remote = mock.Mock(), mock.Mock(), mock.Mock()
        listener.accept.return_value = (accepted, ('127.0.0.1', 1))
        remote.poll.return_value = None

        def launch(debug):
            Client.remote = remote

        with mock.patch.object(Client, 'makeSockets', return_value=(listener, b'internet localhost 1\n', True)), \
             mock.patch.object(Client, 'makeRemoteProcess', side_effect=launch), \
             mock.patch.object(Client, 'readLenFromSocket', side_effect=[b'wrong\n', b'secret\n']), \
             mock.patch.object(embed.uuid, 'uuid4', return_value='secret'), \
             mock.patch.object(embed.select, 'select', return_value=([listener], [], [])), \
             mock.patch.object(embed.atexit, 'register') as register:
            with self.assertRaisesRegex(RuntimeError, 'Security'):
                Client.startRemote(False)
            self.assertIsNone(Client.remote)
            self.assertIsNone(Client.serv_socket)
            self.assertIsNone(Client.socket2)
            accepted.close.assert_called_once()
            remote.kill.assert_called_once()
            remote.wait.assert_called_once()
            register.assert_not_called()
            # A clean second bootstrap is not skipped because of a stale Popen.
            Client.startRemote(False)
            self.assertIs(Client.remote, remote)
            register.assert_called_once()

    def test_process_cleanup_errors_preserve_original_startup_failure(self):
        for operation in ('poll', 'kill', 'wait'):
            with self.subTest(operation=operation):
                class Client(Embedded):
                    pass
                parent, child, remote = mock.Mock(), mock.Mock(), mock.Mock()
                failure = ConnectionError('original handshake failure')
                remote.poll.return_value = None
                getattr(remote, operation).side_effect = PermissionError('cleanup failed')

                def sockets():
                    Client.socket2 = child
                    return parent, b'unix 42\n', False

                def launch(debug):
                    Client.remote = remote

                with mock.patch.object(Client, 'makeSockets', side_effect=sockets), \
                     mock.patch.object(Client, 'makeRemoteProcess', side_effect=launch), \
                     mock.patch.object(Client, 'readLenFromSocket', side_effect=failure):
                    with self.assertRaises(ConnectionError) as caught:
                        Client.startRemote(False)
                self.assertIs(caught.exception, failure)
                self.assertIsNone(Client.remote)
                self.assertIsNone(Client.serv_socket)
                self.assertIsNone(Client.socket2)
                parent.close.assert_called_once()
                child.close.assert_called_once()
                if operation in ('poll', 'kill'):
                    remote.wait.assert_not_called()
                else:
                    remote.kill.assert_called_once()
                    remote.wait.assert_called_once()

    def test_child_exit_before_connect_is_detected_without_timeout(self):
        class Client(Embedded):
            pass
        listener, remote = mock.Mock(), mock.Mock()
        remote.poll.side_effect = [None, None, 9, 9]

        def launch(debug):
            Client.remote = remote

        with mock.patch.object(Client, 'makeSockets', return_value=(listener, b'internet localhost 1\n', True)), \
             mock.patch.object(Client, 'makeRemoteProcess', side_effect=launch), \
             mock.patch.object(embed.select, 'select', return_value=([], [], [])) as select, \
             mock.patch.object(embed.atexit, 'register') as register:
            with self.assertRaisesRegex(RuntimeError, 'before connecting.*9'):
                Client.startRemote(False)
        self.assertEqual(select.call_count, 2)
        listener.accept.assert_not_called()
        remote.kill.assert_not_called()
        remote.wait.assert_called_once()
        register.assert_not_called()
        self.assertIsNone(Client.remote)
        self.assertIsNone(Client.serv_socket)

    def test_launch_failure_closes_both_socketpair_endpoints(self):
        class Client(Embedded):
            pass
        parent, child = mock.Mock(), mock.Mock()

        def sockets():
            Client.socket2 = child
            return parent, b'unix 42\n', False

        with mock.patch.object(Client, 'makeSockets', side_effect=sockets), \
             mock.patch.object(Client, 'makeRemoteProcess', side_effect=OSError('launch failed')):
            with self.assertRaisesRegex(OSError, 'launch failed'):
                Client.startRemote(False)
        parent.close.assert_called_once()
        child.close.assert_called_once()
        self.assertIsNone(Client.remote)
        self.assertIsNone(Client.serv_socket)
        self.assertIsNone(Client.socket2)

    def test_fragmented_reads_and_writes(self):
        for transport in (Embedded, EmbedApplication):
            with self.subTest(transport=transport.__name__):
                sock = FragmentSocket(b'abcdefgh')
                self.assertEqual(transport.readLenFromSocket(sock, 8), b'abcdefgh')
                transport.writeToSocket(sock, b'abcdefgh')
                self.assertEqual(sock.output, b'abcdefgh')

    def test_eof_in_header_and_body(self):
        command = (0, 'Load', ('example.vsz',), {})
        packet = frame(command)
        for cut in (0, 1, 3, 4, len(packet)-1):
            with self.subTest(cut=cut):
                with self.assertRaises(ConnectionError):
                    EmbedApplication.readCommand(FragmentSocket(packet[:cut]))

    def test_client_eof_in_reply(self):
        for cut in (0, 1, 3, 4, len(frame('reply'))-1):
            with self.subTest(cut=cut):
                with mock.patch.object(Embedded, 'serv_socket',
                                       FragmentSocket(frame('reply')[:cut]), create=True), \
                     mock.patch.object(Embedded, 'cmdlen', 4, create=True):
                    with self.assertRaises(ConnectionError):
                        Embedded.sendCommand((0, 'Load', ('example.vsz',), {}))

    def test_zero_write_is_disconnect(self):
        for transport in (Embedded, EmbedApplication):
            sock = mock.Mock()
            sock.send.side_effect = [0, AssertionError('send retried after zero')]
            with self.subTest(transport=transport.__name__):
                with self.assertRaises(ConnectionError):
                    transport.writeToSocket(sock, b'packet')

    def test_multiple_fragmented_frames(self):
        values = [(0, 'Load', ('example.vsz',), {}), None, {'x': list(range(100))}]
        sock = FragmentSocket(b''.join(frame(v) for v in values), fragment=3)
        for value in values:
            self.assertEqual(EmbedApplication.readCommand(sock), value)
        self.assertEqual(sock.data, b'')

    def test_invalid_pickle_is_not_silenced(self):
        packet = struct.pack('<I', 3) + b'bad'
        with self.assertRaises(pickle.UnpicklingError):
            EmbedApplication.readCommand(FragmentSocket(packet))
        with mock.patch.object(Embedded, 'serv_socket', FragmentSocket(packet), create=True), \
             mock.patch.object(Embedded, 'cmdlen', 4, create=True):
            with self.assertRaises(pickle.UnpicklingError):
                Embedded.sendCommand((0, 'Load', (), {}))

    def test_remote_exception_does_not_break_next_reply(self):
        sock = FragmentSocket(frame(ValueError('bad command')) + frame(42))
        with mock.patch.object(Embedded, 'serv_socket', sock, create=True), \
             mock.patch.object(Embedded, 'cmdlen', 4, create=True):
            with self.assertRaisesRegex(ValueError, 'bad command'):
                Embedded.sendCommand((0, 'bad', (), {}))
            self.assertEqual(Embedded.sendCommand((0, 'good', (), {})), 42)

    def test_real_tcp_fragmentation_and_eof(self):
        # Loopback peers are created here: never unpickle an unknown network peer.
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen(1)
            with socket.create_connection(listener.getsockname()) as writer:
                reader, _ = listener.accept()
                with reader:
                    packet = frame((0, 'Load', ('example.vsz',), {}))
                    writer.sendall(packet)
                    writer.shutdown(socket.SHUT_WR)

                    class ShortReads:
                        eof_seen = False

                        def recv(self, size):
                            if self.eof_seen:
                                raise AssertionError('real TCP recv retried after EOF')
                            data = reader.recv(min(size, 1))
                            self.eof_seen = not data
                            return data

                    stream = ShortReads()
                    self.assertEqual(EmbedApplication.readCommand(stream),
                                     (0, 'Load', ('example.vsz',), {}))
                    with self.assertRaises(ConnectionError):
                        EmbedApplication.readCommand(stream)

    def test_nested_qt_events_do_not_reenter_socket_reader(self):
        # Load/export/click commands may process Qt events. A second buffered
        # command must not run inside the first command's interpreter call.
        app = qt.QCoreApplication.instance() or qt.QCoreApplication([])
        calls = []
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen(1)
            with socket.create_connection(listener.getsockname()) as writer:
                reader, _ = listener.accept()
                with reader:
                    notifier = qt.QSocketNotifier(
                        reader.fileno(), qt.QSocketNotifier.Type.Read)
                    harness = SimpleNamespace(socket=reader, notifier=notifier)
                    harness.readCommand = EmbedApplication.readCommand
                    harness.writeToSocket = EmbedApplication.writeToSocket
                    harness.writeOutput = lambda value: EmbedApplication.writeOutput(harness, value)
                    harness.readFromSocket = lambda: EmbedApplication.readFromSocket(harness)

                    def nested():
                        calls.append('begin')
                        app.processEvents()
                        calls.append('end')
                        return len(calls)

                    harness.clients = {0: SimpleNamespace(ci=SimpleNamespace(cmds={'nested': nested}))}
                    notifier.activated.connect(lambda fd: harness.readFromSocket())
                    try:
                        writer.sendall(frame((0, 'nested', (), {})) * 2)
                        harness.readFromSocket()
                        self.assertEqual(calls, ['begin', 'end'])
                        harness.readFromSocket()
                        self.assertEqual(calls, ['begin', 'end', 'begin', 'end'])
                    finally:
                        notifier.setEnabled(False)

    def test_shutdown_after_disconnect_is_idempotent(self):
        sock = mock.Mock()
        sock.recv.return_value = b''
        sock.send.return_value = 1
        sock.shutdown.side_effect = OSError('disconnected')
        with mock.patch.object(Embedded, 'serv_socket', sock, create=True), \
             mock.patch.object(Embedded, 'cmdlen', 4, create=True), \
             mock.patch.object(Embedded, 'remote', mock.Mock()):
            Embedded.exitQt()
            Embedded.exitQt()
            sock.close.assert_called_once()
            self.assertIsNone(Embedded.remote)

    def test_shared_socket_transaction_is_locked(self):
        # An instrumented real lock provides exact scheduling, not sleeps.
        attempted = threading.Event()
        acquired = threading.Event()
        finished = threading.Event()
        lock = threading.RLock()
        errors = []

        class ObservedLock:
            def __enter__(self):
                attempted.set()
                lock.acquire()
                acquired.set()

            def __exit__(self, *args):
                lock.release()

        sock = FragmentSocket(frame('ok'))

        def send():
            try:
                self.assertEqual(Embedded.sendCommand((0, 'Load', (), {})), 'ok')
            except BaseException as ex:
                errors.append(ex)
            finally:
                finished.set()

        with mock.patch.object(Embedded, '_command_lock', ObservedLock(), create=True), \
             mock.patch.object(Embedded, 'serv_socket', sock, create=True), \
             mock.patch.object(Embedded, 'cmdlen', 4, create=True):
            with lock:
                worker = threading.Thread(target=send, daemon=True)
                worker.start()
                self.assertTrue(attempted.wait(5), 'sendCommand did not take the lock')
                self.assertFalse(acquired.is_set())
                self.assertEqual(sock.output, b'')
            self.assertTrue(finished.wait(5))
            worker.join()
        if errors:
            raise errors[0]
        self.assertTrue(acquired.is_set())


if __name__ == '__main__':
    unittest.main()
