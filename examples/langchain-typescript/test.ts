import { test } from 'node:test';
import assert from 'node:assert/strict';
import { resolve } from 'node:path';
import { connectGotoquill } from 'langchain-gotoquill';
import { connection, signingGraph } from './main.js';

const command = resolve('../langchain-python/.venv/bin/python');
const args = [resolve('../langchain-python/mock_server.py')];
test('configuration validates mode and missing Cloud credentials', () => {
  const token = process.env.GOTOQUILL_ACCESS_TOKEN;
  delete process.env.GOTOQUILL_ACCESS_TOKEN;
  try {
    assert.equal(connection('local').url, undefined);
    assert.throws(() => connection('cloud'), /OAuth access token/);
    assert.throws(() => connection('mistyped'), /Choose/);
  } finally { if (token !== undefined) process.env.GOTOQUILL_ACCESS_TOKEN = token; }
});
test('real adapter and graph hand off browser consent, retain origin and wait', async () => {
  const session = await connectGotoquill({command,args});
  const links: string[] = [];
  try {
    const result = await signingGraph(session.tools,{signer_name:'Dana Cohen'},async url => {links.push(url);},0).invoke({});
    assert.deepEqual(links,['https://signing.invalid/review']);
    assert.equal(result.request_id,'fixture-dana');
    assert.equal(result.status,'declined');
  } finally { await session.close(); }
});
test('bounded wait leaves the originating request pending', async () => {
  const session = await connectGotoquill({command,args});
  try {
    const result = await signingGraph(session.tools,{},async () => {},0,1).invoke({});
    assert.equal(result.status,'pending');
    assert.equal(result.request_id,'fixture-dana');
  } finally { await session.close(); }
});
