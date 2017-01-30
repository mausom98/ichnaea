from datetime import timedelta

from ichnaea.api.locate.tests.base import (
    BaseLocateTest,
    CommonLocateErrorTest,
    CommonLocateTest,
)
from ichnaea.models import Radio
from ichnaea.tests.factories import (
    BlueShardFactory,
    CellShardFactory,
    WifiShardFactory,
)
from ichnaea import util


class RegionBase(BaseLocateTest):

    url = '/v1/country'
    apikey_metrics = False
    metric_path = 'path:v1.country'
    metric_type = 'region'

    @property
    def ip_response(self):
        return {
            'country_code': 'GB',
            'country_name': 'United Kingdom',
        }

    def check_model_response(self, response, model,
                             region=None, fallback=None, **kw):
        expected_names = set(['country_code', 'country_name'])

        expected = super(RegionBase, self).check_model_response(
            response, model,
            region=region,
            fallback=fallback,
            expected_names=expected_names,
            **kw)

        data = response.json
        assert data['country_code'] == expected['region']
        if fallback is not None:
            assert data['fallback'] == fallback


class TestView(RegionBase, CommonLocateTest):

    def test_geoip(self, app, data_queues, session_tracker, stats):
        res = self._call(app, ip=self.test_ip)
        self.check_response(data_queues, res, 'ok')
        assert res.headers['Access-Control-Allow-Origin'] == '*'
        assert res.headers['Access-Control-Max-Age'] == '2592000'
        session_tracker(0)
        stats.check(counter=[
            ('request', [self.metric_path, 'method:post', 'status:200']),
        ], timer=[
            ('request', [self.metric_path, 'method:post']),
        ])

    def test_geoip_miss(self, app, data_queues, session_tracker, stats):
        res = self._call(app, ip='127.0.0.1', status=404)
        self.check_response(data_queues, res, 'not_found')
        session_tracker(0)
        stats.check(counter=[
            ('request', [self.metric_path, 'method:post', 'status:404']),
        ], timer=[
            ('request', [self.metric_path, 'method:post']),
        ])

    def test_known_api_key(self, app, data_queues, session_tracker, stats):
        res = self._call(app, api_key='test', ip=self.test_ip)
        self.check_response(data_queues, res, 'ok')
        session_tracker(0)
        stats.check(counter=[
            ('request', [self.metric_path, 'method:post', 'status:200']),
            (self.metric_type + '.request', 1, [self.metric_path, 'key:test']),
        ], timer=[
            ('request', [self.metric_path, 'method:post']),
        ])

    def test_no_api_key(self, app, data_queues,
                        redis, session_tracker, stats):
        super(TestView, self).test_no_api_key(
            app, data_queues, redis, stats,
            status=200, response='ok')
        session_tracker(0)

    def test_invalid_api_key(self, app, data_queues,
                             redis, session_tracker, stats):
        super(TestView, self).test_invalid_api_key(
            app, data_queues, redis, stats,
            status=200, response='ok')
        session_tracker(0)

    def test_unknown_api_key(self, app, data_queues,
                             redis, session_tracker, stats):
        super(TestView, self).test_unknown_api_key(
            app, data_queues, redis, stats,
            status=200, response='ok', metric_key='abcdefg')
        session_tracker(0)

    def test_incomplete_request(self, app, data_queues, session_tracker):
        res = self._call(app, body={'wifiAccessPoints': []}, ip=self.test_ip)
        self.check_response(data_queues, res, 'ok')
        session_tracker(0)

    def test_blue(self, app, data_queues, session, session_tracker):
        # Use manual mac to ensure we only use one shard.
        blue1 = BlueShardFactory(mac='000000123456', samples=10)
        blue2 = BlueShardFactory(mac='000000abcdef', samples=10)
        session.flush()

        query = self.model_query(blues=[blue1, blue2])
        res = self._call(app, body=query, ip='127.0.0.1')
        self.check_response(data_queues, res, blue1)
        session_tracker(2)

    def test_cell(self, app, session, session_tracker):
        # cell with unique mcc to region mapping
        cell = CellShardFactory(mcc=235)
        session.flush()

        query = self.model_query(cells=[cell])
        res = self._call(app, body=query)
        self.check_model_response(res, cell, region='GB')
        session_tracker(1)

    def test_cell_ambiguous(self, app, session, session_tracker):
        # cell with ambiguous mcc to region mapping
        cell = CellShardFactory(mcc=234)
        session.flush()

        query = self.model_query(cells=[cell])
        res = self._call(app, body=query)
        self.check_model_response(res, cell, region='GB')
        session_tracker(2)

    def test_cell_geoip_match(self, app, session, session_tracker):
        cell = CellShardFactory(mcc=234)
        session.flush()

        query = self.model_query(cells=[cell])
        res = self._call(app, body=query, ip=self.test_ip)
        self.check_model_response(res, cell, region='GB')
        session_tracker(2)

    def test_cell_geoip_mismatch(self, app, session, session_tracker):
        # UK GeoIP with ambiguous US mcc
        uk_cell = CellShardFactory.build(mcc=234)
        us_cell = CellShardFactory(mcc=310)
        session.flush()

        query = self.model_query(cells=[us_cell])
        res = self._call(app, body=query, ip=self.test_ip)
        self.check_model_response(res, uk_cell, region='GB', fallback='ipf')
        session_tracker(2)

    def test_cell_over_geoip(self, app, session, session_tracker):
        # UK GeoIP with single DE cell
        cell = CellShardFactory(mcc=262)
        session.flush()

        query = self.model_query(cells=[cell])
        res = self._call(app, body=query, ip=self.test_ip)
        self.check_model_response(res, cell, region='DE')
        session_tracker(1)

    def test_cells_over_geoip(self, app, session, session_tracker):
        # UK GeoIP with multiple US cells
        us_cell1 = CellShardFactory(radio=Radio.gsm, mcc=310, samples=100)
        us_cell2 = CellShardFactory(radio=Radio.lte, mcc=311, samples=100)
        session.flush()

        query = self.model_query(cells=[us_cell1, us_cell2])
        res = self._call(app, body=query, ip=self.test_ip)
        self.check_model_response(res, us_cell1, region='US')
        session_tracker(3)

    def test_wifi(self, app, data_queues, session, session_tracker):
        # Use manual mac to ensure we only use one shard.
        wifi1 = WifiShardFactory(mac='000000123456', samples=10)
        wifi2 = WifiShardFactory(mac='000000abcdef', samples=10)
        session.flush()

        query = self.model_query(wifis=[wifi1, wifi2])
        res = self._call(app, body=query, ip='127.0.0.1')
        self.check_response(data_queues, res, wifi1)
        session_tracker(2)

    def test_wifi_over_cell(self, app, session):
        now = util.utcnow()
        three_months = now - timedelta(days=90)
        wifi1 = WifiShardFactory(
            samples=1000, created=three_months, modified=now, region='US')
        wifi2 = WifiShardFactory(
            samples=1000, created=three_months, modified=now, region='US')
        cell = CellShardFactory(radio=Radio.gsm, samples=10)
        session.flush()

        query = self.model_query(cells=[cell], wifis=[wifi1, wifi2])
        res = self._call(app, body=query, ip=self.test_ip)
        # wifi says US with a high score, cell and geoip say UK
        self.check_model_response(res, wifi1, region='US')

    def test_get(self, app, data_queues, session_tracker, stats):
        super(TestView, self).test_get(app, data_queues, stats)
        session_tracker(0)


class TestError(RegionBase, CommonLocateErrorTest):

    def test_apikey_error(self, app, data_queues,
                          db_drop_table, raven, session, stats):
        super(TestError, self).test_apikey_error(
            app, data_queues, db_drop_table,
            raven, session, stats, db_errors=0, fallback=None)

    def test_database_error(self, app, data_queues,
                            db_drop_table, raven, session, stats):
        super(TestError, self).test_database_error(
            app, data_queues, db_drop_table,
            raven, session, stats, db_errors=2, fallback=None)
