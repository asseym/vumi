# -*- test-case-name: vumi.transports.api.tests.test_api -*-
import json

from twisted.python import log
from twisted.internet.defer import inlineCallbacks

from vumi.transports.httprpc import HttpRpcTransport


class HttpApiTransport(HttpRpcTransport):
    """
    Native HTTP API for getting messages into vumi.

    NOTE: This has no security. Put it behind a firewall or something.

    Configuration Values
    --------------------
    web_path : str
        The path relative to the host where this listens
    web_port : int
        The port this listens on
    transport_name : str
        The name this transport instance will use to create its queues
    reply_expected : boolean (default False)
        True if a reply message is expected
    allowed_fields : list (default DEFAULT_ALLOWED_FIELDS class attribute)
        The list of fields a request is allowed to contain
        DEFAULT_ALLOWED_FIELDS = [content, to_addr, from_addr]
    field_defaults : dict (default {})
        Default values for fields not sent by the client

    If reply_expected is True, the transport will wait for a reply message
    and will return the reply's content as the HTTP response body. If False,
    the message_id of the dispatched incoming message will be returned.
    """

    transport_type = 'http_api'

    DEFAULT_ALLOWED_FIELDS = (
        'content',
        'to_addr',
        'from_addr',
        'group',
        'session_event',
        )

    def setup_transport(self):
        self.reply_expected = self.config.get('reply_expected', False)
        self.allowed_fields = set(self.config.get('allowed_fields',
                                                  self.DEFAULT_ALLOWED_FIELDS))
        self.field_defaults = self.config.get('field_defaults', {})
        return super(HttpApiTransport, self).setup_transport()

    def handle_outbound_message(self, message):
        if self.reply_expected:
            return super(HttpApiTransport, self).handle_outbound_message(
                message)
        log.msg("HttpApiTransport dropping outbound message: %s" % (message))

    def get_field_values(self, request, required_fields):
        values = self.field_defaults.copy()
        errors = {}
        for field in request.args:
            if field not in self.allowed_fields:
                errors.setdefault('unexpected_parameter', []).append(field)
            else:
                values[field] = str(request.args.get(field)[0])
        for field in required_fields:
            if field not in values and field in self.allowed_fields:
                errors.setdefault('missing_parameter', []).append(field)
        return values, errors

    @inlineCallbacks
    def handle_raw_inbound_message(self, message_id, request):
        values, errors = self.get_field_values(request, ['content', 'to_addr',
                                                         'from_addr'])
        if errors:
            yield self.finish_request(message_id, json.dumps(errors), code=400)
            return
        log.msg(('HttpApiTransport sending from %(from_addr)s to %(to_addr)s '
                 'message "%(content)s"') % values)
        payload = {
            'message_id': message_id,
            'transport_type': self.transport_type,
            }
        payload.update(values)
        yield self.publish_message(**payload)
        if not self.reply_expected:
            yield self.finish_request(message_id,
                                      json.dumps({'message_id': message_id}))
