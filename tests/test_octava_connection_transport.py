import ast
from pathlib import Path
import socket
import ssl
import unittest
from unittest.mock import patch, Mock
from urllib.error import URLError,HTTPError

class SafeKeyError(ValueError):pass

tree=ast.parse((Path(__file__).parents[1]/'local_agent/studio_server.py').read_text('utf-8'))
scope={'OctavaKeyError':SafeKeyError,'_replace_octava_key':Mock(return_value={'validated':True})}
for node in tree.body:
    if isinstance(node,ast.FunctionDef) and node.name in ('_octava_key_probe_transport','replace_key'):
        exec(compile(ast.Module(body=[node],type_ignores=[]),'studio_transport','exec'),scope)
transport=scope['_octava_key_probe_transport']

class TransportTests(unittest.TestCase):
    def test_single_request_has_60_seconds(self):
        sentinel=object();request=object()
        with patch('urllib.request.urlopen',return_value=sentinel) as call:
            self.assertIs(transport(request,timeout=18),sentinel)
            call.assert_called_once_with(request,timeout=60)
    def test_dns_error_does_not_echo_provider_secret(self):
        with patch('urllib.request.urlopen',side_effect=URLError(socket.gaierror(-2,'private-secret'))):
            with self.assertRaisesRegex(SafeKeyError,'DNS') as exc:transport(object())
            self.assertNotIn('private-secret',str(exc.exception))
    def test_certificate_error_is_distinct(self):
        with patch('urllib.request.urlopen',side_effect=URLError(ssl.SSLCertVerificationError(1,'private-secret'))):
            with self.assertRaisesRegex(SafeKeyError,'сертификата') as exc:transport(object())
            self.assertNotIn('private-secret',str(exc.exception))
    def test_timeout_preserves_old_key_message(self):
        with patch('urllib.request.urlopen',side_effect=TimeoutError('private-secret')):
            with self.assertRaisesRegex(SafeKeyError,'60 секунд') as exc:transport(object())
            self.assertIn('прежний ключ не изменён',str(exc.exception))
    def test_http_status_goes_to_existing_credential_validator(self):
        error=HTTPError('https://octavapi.shop/v1/chat/completions',401,'private-secret',{},None)
        with patch('urllib.request.urlopen',side_effect=error):
            with self.assertRaises(HTTPError) as exc:transport(object())
            self.assertIs(exc.exception,error)
    def test_candidate_is_validated_once_by_original_vault_logic(self):
        scope['_replace_octava_key'].reset_mock()
        self.assertEqual(scope['replace_key']('test-candidate'),{'validated':True})
        scope['_replace_octava_key'].assert_called_once_with('test-candidate',transport=transport)

if __name__=='__main__':unittest.main()
