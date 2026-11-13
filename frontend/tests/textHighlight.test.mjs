import {test} from 'node:test';
import assert from 'node:assert/strict';
import {highlightSpan} from '../src/textHighlight.ts';
test('returns exact source offsets only for verbatim evidence',()=>{assert.deepEqual(highlightSpan('before ગુજરાતી after','ગુજરાતી'),[7,14]);assert.equal(highlightSpan('The total is 25','total is 125'),null);assert.equal(highlightSpan('abc',''),null);});
