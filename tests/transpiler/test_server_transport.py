from pyjs.testing.helpers import assert_compiled_sources


def test_fetch_transport_uses_abort_signal_timeout():
    assert_compiled_sources(
        '''
        from pyjs.server.transport import FetchTransport

        async def main():
            response = await FetchTransport().request(
                "/api/issues",
                "{}",
                5000,
            )
            print(response.status)
        ''',
        {
            "pyjs.server.transport": '''
                export class TransportResponse {

                    constructor(status, body) {
                        this.status = status;
                        this.body = body;
                    }
                }

                export class ClientTransport {
                }

                export class FetchTransport extends ClientTransport {

                    request_headers() {
                        return new Map([['Content-Type', 'application/json']]);
                    }

                    async request(url, body, { timeout_ms=0} = {}) {
                        var options = ({method: 'POST', headers: this.request_headers(), body: body});
                        if (timeout_ms > 0) {
                            var $assignment6 = AbortSignal.timeout(timeout_ms);
                            (options['signal'] = $assignment6, null);
                        }
                        var response = await fetch(url, options);
                        return new TransportResponse(response.status, await response.text());
                    }
                }
            ''',
            "_pyjs_source_": '''
                import { FetchTransport } from './pyjs.server.transport.js';

                export async function main() {
                    var response = await new FetchTransport().request('/api/issues', '{}', {timeout_ms: 5000});
                    console.log(response.status);
                }
            ''',
        },
    )


def test_django_fetch_transport_reads_the_document_csrf_token():
    assert_compiled_sources(
        '''
        from pyjs.server.django import DjangoFetchTransport

        def main():
            print(DjangoFetchTransport().request_headers())
        ''',
        {
            "pyjs.server.transport": '''
                export class ClientTransport {
                }

                export class FetchTransport extends ClientTransport {
                }
            ''',
            "pyjs.server.django.transport": '''
                import { FetchTransport } from './pyjs.server.transport.js';
                import { RuntimeError as $RuntimeError } from './pyjs.python.js';

                export class DjangoFetchTransport extends FetchTransport {

                    request_headers() {
                        var csrf_meta = document.querySelector('meta[name="csrf-token"]');
                        if (csrf_meta == null) {
                            throw new $RuntimeError('Django CSRF metadata is missing from the current document.');
                        }
                        var csrf_token = csrf_meta.getAttribute('content');
                        if (csrf_token == null) {
                            throw new $RuntimeError('The Django CSRF token is missing from its metadata.');
                        }
                        return new Map([['Content-Type', 'application/json'], ['X-CSRFToken', csrf_token]]);
                    }
                }
            ''',
            "pyjs.python": '''
                export class RuntimeError extends Error {
                }
            ''',
            "_pyjs_source_": '''
                import { DjangoFetchTransport } from './pyjs.server.django.transport.js';

                export function main() {
                    console.log(new DjangoFetchTransport().request_headers());
                }
            ''',
        },
    )
