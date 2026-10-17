from pyjs.testing.helpers import assert_transpile


def test_jsonapi_decoder_uses_plain_json_and_map_backed_indexes():
    assert_transpile(
        r'''
        from pydantic import BaseModel
        from pyjs import js
        from pyjs.server.jsonapi import (
            decode_jsonapi_document,
            parse_jsonapi_document,
        )

        @js
        class Task(BaseModel):
            id: str
            title: str

        def main():
            document = parse_jsonapi_document('{"data":null}')
            decoded = decode_jsonapi_document(
                document,
                {"tasks": Task},
            )
        ''',
        '''
        import { BaseModel } from './pyjs.lib.pydantic.v2.js';
        import { decode_jsonapi_document } from './pyjs.server.jsonapi.js';

        export class Task extends BaseModel {
        }
        Task.__pyjs_required__ = ['id', 'title'];
        Task.__pyjs_fields__ = new Map([['id', 'str'], ['title', 'str']]);

        export function main() {
            var document = JSON.parse('{"data":null}');
            var decoded = decode_jsonapi_document(document, new Map([['tasks', Task]]));
        }
        ''',
    )
