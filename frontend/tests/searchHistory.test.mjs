import {test} from 'node:test';
import assert from 'node:assert/strict';
import {rememberSearch} from '../src/searchHistory.ts';
test('recent searches are trimmed, case-insensitive deduplicated and bounded',()=>{
 assert.deepEqual(rememberSearch(['Alpha','Beta'],'  alpha  '),['alpha','Beta']);
 assert.deepEqual(rememberSearch(['Alpha'],'   '),['Alpha']);
 assert.equal(rememberSearch(Array.from({length:20},(_,i)=>`q${i}`),'new').length,20);
});
