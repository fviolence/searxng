# SPDX-License-Identifier: AGPL-3.0-or-later
# pylint: disable=missing-module-docstring,missing-class-docstring,invalid-name

from mock import Mock, patch
from parameterized import parameterized

from searx.engines import query_corrector
from searx.results import ResultContainer
from searx.search.processors import online

from tests import SearxTestCase


def setup_query_corrector(test_case):
    test_case.setattr4test(query_corrector, 'base_url', 'https://corrector.example')
    test_case.setattr4test(query_corrector, 'api_path', '/v1/correct')
    test_case.setattr4test(query_corrector, 'max_query_length', 80)
    test_case.setattr4test(query_corrector, 'max_correction_length', 256)


class TestQueryCorrectorSetup(SearxTestCase):

    def setUp(self):
        super().setUp()
        setup_query_corrector(self)

    def test_engine_uses_dedicated_query_correction_subgroup(self):
        self.assertEqual(query_corrector.categories, ['general', 'query correction'])

    def test_engine_defaults_to_https_only(self):
        self.assertFalse(query_corrector.enable_http)

    def test_engine_describes_self_hosted_contract(self):
        self.assertFalse(query_corrector.about["use_official_api"])
        self.assertEqual(query_corrector.about["official_api_documentation"], "")

    @parameterized.expand(
        [
            ('https', 'https://corrector.example'),
            ('https_with_port_and_path', 'https://corrector.example:8443/service'),
        ]
    )
    def test_setup_accepts_valid_base_url(self, _name, base_url):
        with patch.object(query_corrector, 'base_url', base_url):
            self.assertTrue(query_corrector.setup({}))

    def test_setup_rejects_http_without_enable_http(self):
        with patch.object(query_corrector, 'base_url', 'http://corrector.example'):
            with self.assertRaisesRegex(ValueError, 'enable_http'):
                query_corrector.setup({})

    def test_setup_accepts_http_when_explicitly_enabled(self):
        with (
            patch.object(query_corrector, 'base_url', 'http://corrector.example'),
            patch.object(query_corrector, 'enable_http', True),
        ):
            self.assertTrue(query_corrector.setup({}))

    @parameterized.expand(
        [
            ('empty', ''),
            ('relative', 'corrector.example'),
            ('scheme_relative', '//corrector.example'),
            ('unsupported_scheme', 'ftp://corrector.example'),
            ('missing_host_http', 'http:///v1/correct'),
            ('missing_host_https', 'https://'),
        ]
    )
    def test_setup_rejects_invalid_base_url(self, _name, base_url):
        with patch.object(query_corrector, 'base_url', base_url):
            with self.assertRaisesRegex(ValueError, 'base_url'):
                query_corrector.setup({})

    @parameterized.expand(
        [
            ('empty', ''),
            ('relative', 'v1/correct'),
        ]
    )
    def test_setup_rejects_invalid_api_path(self, _name, api_path):
        with patch.object(query_corrector, 'api_path', api_path):
            with self.assertRaisesRegex(ValueError, 'api_path'):
                query_corrector.setup({})

    @parameterized.expand(
        [
            ('query_zero', 'max_query_length', 0),
            ('query_negative', 'max_query_length', -1),
            ('correction_zero', 'max_correction_length', 0),
            ('correction_negative', 'max_correction_length', -1),
        ]
    )
    def test_setup_rejects_non_positive_length_limits(self, _name, setting_name, value):
        with patch.object(query_corrector, setting_name, value):
            with self.assertRaisesRegex(ValueError, setting_name):
                query_corrector.setup({})

    def test_setup_accepts_minimum_positive_length_limits(self):
        with (
            patch.object(query_corrector, 'max_query_length', 1),
            patch.object(query_corrector, 'max_correction_length', 1),
        ):
            self.assertTrue(query_corrector.setup({}))


class TestQueryCorrectorRequest(SearxTestCase):

    def setUp(self):
        super().setUp()
        setup_query_corrector(self)

    @staticmethod
    def _request_params(locale='en-US'):
        return {
            **online.default_request_params(),
            'query': '',
            'category': 'general',
            'pageno': 1,
            'safesearch': 0,
            'time_range': None,
            'engine_data': {},
            'searxng_locale': locale,
        }

    def test_request_builds_post_request(self):
        params = self._request_params()
        query_corrector.request('  typo query  ', params)

        self.assertEqual(params['method'], 'POST')
        self.assertEqual(params['url'], 'https://corrector.example/v1/correct')
        self.assertEqual(params['json'], {'query': 'typo query', 'language': 'en-US'})
        self.assertEqual(params['headers']['Accept'], 'application/json')
        self.assertNotIn('Content-Type', params['headers'])
        self.assertFalse(params['raise_for_httperror'])

    def test_request_joins_trailing_base_url_without_double_slash(self):
        params = self._request_params()
        with patch.object(query_corrector, 'base_url', 'https://corrector.example/'):
            query_corrector.request('test', params)
        self.assertEqual(params['url'], 'https://corrector.example/v1/correct')

    @parameterized.expand(
        [
            ('empty', ''),
            ('all', 'all'),
            ('auto', 'auto'),
        ]
    )
    def test_request_omits_generic_language(self, _name, locale):
        params = self._request_params(locale)
        query_corrector.request('test', params)
        self.assertEqual(params['json'], {'query': 'test'})

    def test_request_accepts_query_at_length_limit(self):
        params = self._request_params()
        query_corrector.request('x' * query_corrector.max_query_length, params)
        self.assertEqual(params['url'], 'https://corrector.example/v1/correct')
        self.assertEqual(params['json']['query'], 'x' * query_corrector.max_query_length)

    @parameterized.expand(
        [
            ('empty', ''),
            ('whitespace', '   \t\n'),
            ('too_long', 'x' * 81),
        ]
    )
    def test_request_skips_unusable_query(self, _name, query):
        params = self._request_params()
        query_corrector.request(query, params)
        self.assertIsNone(params['url'])
        self.assertEqual(params['method'], 'GET')
        self.assertEqual(params['json'], {})


class TestQueryCorrectorResponse(SearxTestCase):

    def setUp(self):
        super().setUp()
        setup_query_corrector(self)

    @staticmethod
    def _response(status_code=200, payload=None, query='typo query'):
        response = Mock(status_code=status_code)
        response.json.return_value = payload
        response.search_params = {'query': query}
        return response

    @parameterized.expand(
        [
            ('lower_success_boundary', 200),
            ('upper_success_boundary', 299),
        ]
    )
    def test_response_adds_trimmed_correction(self, _name, status_code):
        response = self._response(status_code=status_code, payload={'correction': '  corrected query  '})
        results = query_corrector.response(response)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['correction'], 'corrected query')

    def test_response_accepts_correction_at_length_limit(self):
        correction = 'x' * query_corrector.max_correction_length
        response = self._response(payload={'correction': correction})
        results = query_corrector.response(response)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['correction'], correction)

    @parameterized.expand(
        [
            ('below_success_range', 199),
            ('redirect', 300),
            ('client_error', 404),
            ('server_error', 500),
        ]
    )
    def test_response_ignores_non_success_status(self, _name, status_code):
        response = self._response(status_code=status_code, payload={'correction': 'corrected query'})
        with (
            patch.object(query_corrector, '_last_http_warning', float('-inf')),
            patch.object(query_corrector, '_now', return_value=100.0),
            patch.object(query_corrector, 'logger', create=True) as logger_mock,
        ):
            self.assertEqual(query_corrector.response(response), [])
        logger_mock.warning.assert_called_once_with(
            'query corrector returned HTTP %s; repeated warnings are suppressed for %.0f seconds',
            status_code,
            query_corrector._HTTP_WARNING_INTERVAL,  # pylint: disable=protected-access
        )
        response.json.assert_not_called()

    def test_response_rate_limits_http_failure_warnings(self):
        response = self._response(status_code=503, payload={'correction': 'corrected query'})
        with (
            patch.object(query_corrector, '_last_http_warning', float('-inf')),
            patch.object(query_corrector, '_now', side_effect=[100.0, 101.0, 401.0]),
            patch.object(query_corrector, 'logger', create=True) as logger_mock,
        ):
            self.assertEqual(query_corrector.response(response), [])
            self.assertEqual(query_corrector.response(response), [])
            self.assertEqual(query_corrector.response(response), [])

        self.assertEqual(logger_mock.warning.call_count, 2)
        logger_mock.debug.assert_called_once_with('query corrector returned HTTP %s', 503)

    def test_response_ignores_invalid_json(self):
        response = self._response(payload=None)
        response.json.side_effect = ValueError('invalid JSON')
        self.assertEqual(query_corrector.response(response), [])

    @parameterized.expand(
        [
            ('null', None),
            ('list', []),
            ('string', 'corrected query'),
            ('number', 1),
        ]
    )
    def test_response_ignores_non_object_json(self, _name, payload):
        response = self._response(payload=payload)
        self.assertEqual(query_corrector.response(response), [])

    @parameterized.expand(
        [
            ('missing', {}),
            ('null', {'correction': None}),
            ('number', {'correction': 123}),
            ('list', {'correction': ['corrected query']}),
            ('blank', {'correction': '   '}),
            ('too_long', {'correction': 'x' * 257}),
        ]
    )
    def test_response_ignores_invalid_correction(self, _name, payload):
        response = self._response(payload=payload)
        self.assertEqual(query_corrector.response(response), [])

    @parameterized.expand(
        [
            ('identical', 'typo query', 'typo query'),
            ('case_only', 'TyPo QuErY', 'typo query'),
            ('surrounding_whitespace', '  typo query  ', 'typo query'),
            ('unicode_casefold', 'STRASSE', 'Straße'),
            ('canonical_equivalence', 'cafe\u0301', 'café'),
            ('zero_width_non_joiner_deletion', 'میرود', 'می\u200cرود'),
            ('zero_width_joiner_deletion', 'क्ष', 'क्\u200dष'),
        ]
    )
    def test_response_ignores_equivalent_correction(self, _name, correction, original_query):
        response = self._response(payload={'correction': correction}, query=original_query)
        self.assertEqual(query_corrector.response(response), [])

    @parameterized.expand(
        [
            ('external_bang', '!!ddg corrected query'),
            ('engine_bang', '!google corrected query'),
            ('trimmed_engine_bang', '  !google corrected query  '),
            ('language_prefix', ':de corrected query'),
            ('timeout_prefix', '<0.1 corrected query'),
            ('trailing_external_bang', 'corrected query !!ddg'),
            ('trailing_feeling_lucky', 'corrected query !!'),
            ('trailing_engine_bang', 'corrected query !google'),
            ('trailing_language_prefix', 'corrected query :de'),
            ('trailing_timeout_prefix', 'corrected query <1'),
            ('tab', 'corrected\tquery'),
            ('newline', 'corrected\nquery'),
            ('carriage_return', 'corrected\rquery'),
            ('right_to_left_override', 'corrected \u202equery'),
            ('zero_width_space', 'corrected \u200bquery'),
        ]
    )
    def test_response_ignores_query_syntax_and_control_characters(self, _name, correction):
        response = self._response(payload={'correction': correction})
        self.assertEqual(query_corrector.response(response), [])

    @parameterized.expand(
        [
            ('zero_width_non_joiner_insertion', 'می\u200cرود', 'میرود'),
            ('zero_width_joiner_insertion', 'क्\u200dष', 'क्ष'),
        ]
    )
    def test_response_accepts_required_joining_character_insertions(self, _name, correction, original_query):
        response = self._response(payload={'correction': correction}, query=original_query)
        results = query_corrector.response(response)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['correction'], correction)

    def test_response_correction_reaches_result_container(self):
        response = self._response(payload={'correction': 'corrected query'})
        container = ResultContainer()

        container.extend('query corrector', query_corrector.response(response))
        container.close()

        self.assertEqual(container.corrections, {'corrected query'})
