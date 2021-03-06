from twisted.internet.defer import inlineCallbacks, returnValue
from twisted.internet.task import Clock
from twisted.words.xish import domish

from vumi.transports.tests.test_base import TransportTestCase
from vumi.message import TransportUserMessage, from_json
from vumi.transports.xmpp.xmpp import XMPPTransport
from vumi.transports.xmpp.tests import test_xmpp_stubs


class XMPPTransportTestCase(TransportTestCase):

    transport_name = 'test_xmpp'

    @inlineCallbacks
    def mk_transport(self):
        transport = yield self.get_transport({
            'username': 'user@xmpp.domain.com',
            'password': 'testing password',
            'status': 'chat',
            'status_message': 'XMPP Transport',
            'host': 'xmpp.domain.com',
            'port': 5222,
            'transport_name': 'test_xmpp',
            'transport_type': 'xmpp',
        }, XMPPTransport, start=False)

        transport._xmpp_protocol = test_xmpp_stubs.TestXMPPTransportProtocol
        transport._xmpp_client = test_xmpp_stubs.TestXMPPClient
        transport.ping_call.clock = Clock()
        transport.presence_call.clock = Clock()
        yield transport.startWorker()
        yield transport.xmpp_protocol.connectionMade()
        self.jid = transport.jid
        returnValue(transport)

    @inlineCallbacks
    def test_outbound_message(self):
        transport = yield self.mk_transport()
        yield self.dispatch(TransportUserMessage(
            to_addr='user@xmpp.domain.com', from_addr='test@case.com',
            content='hello world', transport_name='test_xmpp',
            transport_type='xmpp', transport_metadata={}),
            rkey='test_xmpp.outbound')

        xmlstream = transport.xmpp_protocol.xmlstream
        self.assertEqual(len(xmlstream.outbox), 1)
        message = xmlstream.outbox[0]
        self.assertEqual(message['to'], 'user@xmpp.domain.com')
        self.assertTrue(message['id'])
        self.assertEqual(str(message.children[0]), 'hello world')

    @inlineCallbacks
    def test_inbound_message(self):
        transport = yield self.mk_transport()

        message = domish.Element((None, "message"))
        message['to'] = self.jid.userhost()
        message['from'] = 'test@case.com'
        message.addUniqueId()
        message.addElement((None, 'body'), content='hello world')
        protocol = transport.xmpp_protocol
        protocol.onMessage(message)
        dispatched_messages = self._amqp.get_dispatched('vumi',
            'test_xmpp.inbound')
        self.assertEqual(1, len(dispatched_messages))
        msg = from_json(dispatched_messages[0].body)
        self.assertEqual(msg['to_addr'], self.jid.userhost())
        self.assertEqual(msg['from_addr'], 'test@case.com')
        self.assertEqual(msg['transport_name'], 'test_xmpp')
        self.assertNotEqual(msg['message_id'], message['id'])
        self.assertEqual(msg['transport_metadata']['xmpp_id'], message['id'])
        self.assertEqual(msg['content'], 'hello world')

    @inlineCallbacks
    def test_message_without_id(self):
        transport = yield self.mk_transport()

        message = domish.Element((None, "message"))
        message['to'] = self.jid.userhost()
        message['from'] = 'test@case.com'
        message.addElement((None, 'body'), content='hello world')
        self.assertFalse(message.hasAttribute('id'))

        protocol = transport.xmpp_protocol
        protocol.onMessage(message)

        [msg] = self.get_dispatched_messages()
        self.assertTrue(msg['message_id'])
        self.assertEqual(msg['transport_metadata']['xmpp_id'], None)

    @inlineCallbacks
    def test_pinger(self):
        """
        The transport's pinger should send a ping after the ping_interval.
        """
        transport = yield self.mk_transport()
        self.assertEqual(transport.ping_interval, 60)
        # The LoopingCall should be configured and started.
        self.assertEqual(transport.ping_call.f, transport.send_ping)
        self.assertEqual(transport.ping_call.a, ())
        self.assertEqual(transport.ping_call.kw, {})
        self.assertEqual(transport.ping_call.interval, 60)
        self.assertTrue(transport.ping_call.running)

        # Stub output stream
        xmlstream = test_xmpp_stubs.TestXMLStream()
        transport.xmpp_client.xmlstream = xmlstream
        transport.pinger.xmlstream = xmlstream

        # Ping
        transport.ping_call.clock.advance(59)
        self.assertEqual(xmlstream.outbox, [])
        transport.ping_call.clock.advance(2)
        self.assertEqual(len(xmlstream.outbox), 1, repr(xmlstream.outbox))

        [message] = xmlstream.outbox
        self.assertEqual(message['to'], u'user@xmpp.domain.com')
        self.assertEqual(message['type'], u'get')
        [child] = message.children
        self.assertEqual(child.toXml(), u"<ping xmlns='urn:xmpp:ping'/>")

    @inlineCallbacks
    def test_presence(self):
        """
        The transport's presence should be announced regularly.
        """
        transport = yield self.mk_transport()
        self.assertEqual(transport.presence_interval, 60)
        # The LoopingCall should be configured and started.
        self.assertEqual(transport.presence_call.f, transport.send_presence)
        self.assertEqual(transport.presence_call.a, ())
        self.assertEqual(transport.presence_call.kw, {})
        self.assertEqual(transport.presence_call.interval, 60)
        self.assertTrue(transport.presence_call.running)

        # Stub output stream
        xmlstream = test_xmpp_stubs.TestXMLStream()
        transport.xmpp_client.xmlstream = xmlstream
        transport.xmpp_client._initialized = True
        transport.presence.xmlstream = xmlstream

        # Send presence
        transport.presence_call.clock.advance(59)
        self.assertEqual(xmlstream.outbox, [])
        transport.presence_call.clock.advance(2)
        self.assertEqual(len(xmlstream.outbox), 1, repr(xmlstream.outbox))

        [presence] = xmlstream.outbox
        self.assertEqual(presence.toXml(),
            u"<presence><status>chat</status></presence>")

    @inlineCallbacks
    def test_normalizing_from_addr(self):
        transport = yield self.mk_transport()

        message = domish.Element((None, "message"))
        message['to'] = self.jid.userhost()
        message['from'] = 'test@case.com/some_xmpp_id'
        message.addUniqueId()
        message.addElement((None, 'body'), content='hello world')
        protocol = transport.xmpp_protocol
        protocol.onMessage(message)
        dispatched_messages = self._amqp.get_dispatched('vumi',
            'test_xmpp.inbound')
        self.assertEqual(1, len(dispatched_messages))
        msg = from_json(dispatched_messages[0].body)
        self.assertEqual(msg['from_addr'], 'test@case.com')
        self.assertEqual(msg['transport_metadata']['xmpp_id'], message['id'])
