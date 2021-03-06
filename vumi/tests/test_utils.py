import os.path

from twisted.trial.unittest import TestCase
from twisted.internet import reactor
from twisted.internet.defer import Deferred, inlineCallbacks
from twisted.web.server import Site, NOT_DONE_YET
from twisted.web.resource import Resource
from twisted.web import http
from twisted.internet.protocol import Protocol, Factory


from vumi.utils import (normalize_msisdn, vumi_resource_path, cleanup_msisdn,
                        get_operator_name, http_request, http_request_full,
                        get_first_word, redis_from_config)
from vumi.tests.utils import FakeRedis


class UtilsTestCase(TestCase):
    def setUp(self):
        pass

    def tearDown(self):
        pass

    def test_normalize_msisdn(self):
        self.assertEqual(normalize_msisdn('0761234567', '27'),
                         '+27761234567')
        self.assertEqual(normalize_msisdn('27761234567', '27'),
                         '+27761234567')
        self.assertEqual(normalize_msisdn('+27761234567', '27'),
                         '+27761234567')
        self.assertEqual(normalize_msisdn('0027761234567', '27'),
                         '+27761234567')
        self.assertEqual(normalize_msisdn('1234'), '1234')
        self.assertEqual(normalize_msisdn('12345'), '12345')
        self.assertEqual(normalize_msisdn('+12345'), '+12345')

    def test_make_campaign_path_abs(self):
        vumi_tests_path = os.path.dirname(__file__)
        vumi_path = os.path.dirname(os.path.dirname(vumi_tests_path))
        self.assertEqual('/foo/bar', vumi_resource_path('/foo/bar'))
        self.assertEqual(os.path.join(vumi_path, 'vumi/resources/foo/bar'),
                         vumi_resource_path('foo/bar'))

    def test_cleanup_msisdn(self):
        self.assertEqual('27761234567', cleanup_msisdn('27761234567', '27'))
        self.assertEqual('27761234567', cleanup_msisdn('+27761234567', '27'))
        self.assertEqual('27761234567', cleanup_msisdn('0761234567', '27'))

    def test_get_operator_name(self):
        mapping = {'27': {'2782': 'VODACOM', '2783': 'MTN'}}
        self.assertEqual('MTN', get_operator_name('27831234567', mapping))
        self.assertEqual('VODACOM', get_operator_name('27821234567', mapping))
        self.assertEqual('UNKNOWN', get_operator_name('27801234567', mapping))

    def test_get_first_word(self):
        self.assertEqual('KEYWORD',
                         get_first_word('KEYWORD rest of the message'))
        self.assertEqual('', get_first_word(''))
        self.assertEqual('', get_first_word(None))

    def test_redis_from_config_str(self):
        fake_redis = redis_from_config("FAKE_REDIS")
        self.assertTrue(isinstance(fake_redis, FakeRedis))

    def test_redis_from_config_fake_redis(self):
        fake_redis = FakeRedis()
        self.assertEqual(redis_from_config(fake_redis), fake_redis)


class FakeHTTP10(Protocol):
    def dataReceived(self, data):
        self.transport.write(self.factory.response_body)
        self.transport.loseConnection()


class HttpUtilsTestCase(TestCase):

    timeout = 3

    class InterruptHttp(Exception):
        """Indicates that test server should halt http reply"""
        pass

    @inlineCallbacks
    def setUp(self):
        self.root = Resource()
        self.root.isLeaf = True
        site_factory = Site(self.root)
        self.webserver = yield reactor.listenTCP(0, site_factory)
        addr = self.webserver.getHost()
        self.url = "http://%s:%s/" % (addr.host, addr.port)

    @inlineCallbacks
    def tearDown(self):
        yield self.webserver.loseConnection()

    def set_render(self, f, d=None):
        def render(request):
            request.setHeader('Content-Type', 'text/plain')
            try:
                data = f(request)
                request.setResponseCode(http.OK)
            except self.InterruptHttp:
                reactor.callLater(0, d.callback, request)
                return NOT_DONE_YET
            except Exception, err:
                data = str(err)
                request.setResponseCode(http.INTERNAL_SERVER_ERROR)
            return data

        self.root.render = render

    @inlineCallbacks
    def test_http_request_ok(self):
        self.set_render(lambda r: "Yay")
        data = yield http_request(self.url, '')
        self.assertEqual(data, "Yay")

    @inlineCallbacks
    def test_http_request_err(self):
        def err(r):
            raise ValueError("Bad")
        self.set_render(err)
        data = yield http_request(self.url, '')
        self.assertEqual(data, "Bad")

    @inlineCallbacks
    def test_http_request_full_drop(self):
        def interrupt(r):
            raise self.InterruptHttp()
        got_request = Deferred()
        self.set_render(interrupt, got_request)

        got_data = http_request_full(self.url, '')

        request = yield got_request
        request.setResponseCode(http.OK)
        request.write("Foo!")
        request.transport.loseConnection()

        def callback(reason):
            self.assertTrue(
                reason.check("twisted.web._newclient.ResponseFailed"))
            done.callback(None)
        done = Deferred()

        got_data.addBoth(callback)

        yield done

    @inlineCallbacks
    def test_http_request_full_ok(self):
        self.set_render(lambda r: "Yay")
        request = yield http_request_full(self.url, '')
        self.assertEqual(request.delivered_body, "Yay")
        self.assertEqual(request.code, http.OK)

    @inlineCallbacks
    def test_http_request_full_headers(self):
        def check_ua(request):
            self.assertEqual('blah', request.getHeader('user-agent'))
            return "Yay"
        self.set_render(check_ua)

        request = yield http_request_full(self.url, '',
                                          {'User-Agent': ['blah']})
        self.assertEqual(request.delivered_body, "Yay")
        self.assertEqual(request.code, http.OK)

        request = yield http_request_full(self.url, '', {'User-Agent': 'blah'})
        self.assertEqual(request.delivered_body, "Yay")
        self.assertEqual(request.code, http.OK)

    @inlineCallbacks
    def test_http_request_full_err(self):
        def err(r):
            raise ValueError("Bad")
        self.set_render(err)
        request = yield http_request_full(self.url, '')
        self.assertEqual(request.delivered_body, "Bad")
        self.assertEqual(request.code, http.INTERNAL_SERVER_ERROR)

    @inlineCallbacks
    def test_http_request_potential_data_loss(self):
        self.webserver.loseConnection()
        factory = Factory()
        factory.protocol = FakeHTTP10
        factory.response_body = (
            "HTTP/1.0 201 CREATED\r\n"
            "Date: Mon, 23 Jan 2012 15:08:47 GMT\r\n"
            "Server: Fake HTTP 1.0\r\n"
            "Content-Type: text/html; charset=utf-8\r\n"
            "\r\n"
            "Yay")
        self.webserver = yield reactor.listenTCP(0, factory)
        addr = self.webserver.getHost()
        self.url = "http://%s:%s/" % (addr.host, addr.port)

        data = yield http_request(self.url, '')
        self.assertEqual(data, "Yay")
