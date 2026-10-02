// One-off authorized dev QA cleanup. The operator supplies reviewed identity data
// through globalThis.qaCleanupInput in stdin; never put identities in this file.
// Execute with the current Account/Match image's Node and DB environment.
import assert from 'node:assert/strict';
import { Client } from 'pg';
import { readDatabaseConnectionOptions } from '@core/database';
const input = globalThis.qaCleanupInput;
const mode = globalThis.qaCleanupMode;
assert(input?.environment === 'gaegaeting-dev' && input.createdByThisQa === true);
assert(input.preserveAdministratorProfile === true && input.userAndPetImagesAlreadyDeleted === true);
assert(Number.isSafeInteger(input.petId) && input.petId > 0);
assert(['feed-check', 'verify', 'delete'].includes(mode));
const c = new Client(readDatabaseConnectionOptions({ get: (k, fallback) => process.env[k] ?? fallback }));
try {
  await c.connect();
  await c.query(mode === 'feed-check' ? 'BEGIN READ ONLY' : 'BEGIN ISOLATION LEVEL SERIALIZABLE');
  await c.query("SET LOCAL lock_timeout = '5s'");
  await c.query("SET LOCAL statement_timeout = '15s'");
  if (mode === 'feed-check') {
    const feed = await c.query('SELECT count(*)::int n FROM feed WHERE user_id=$1', [input.ownerProfileId]);
    const item = await c.query('SELECT count(*)::int n FROM feed_item WHERE target_user_id=$1', [input.ownerProfileId]);
    assert.equal(feed.rows[0].n, 0); assert.equal(item.rows[0].n, 0);
    await c.query('ROLLBACK');
    console.log(JSON.stringify({ feedReferences: 0, feedItemReferences: 0, readOnly: true }));
  } else {
    assert.equal(process.env.AUTH_TENANT_CODE, 'gaegaeting-dev');
    assert.equal(new URL(process.env.AUTH_ISSUER).pathname, '/t/gaegaeting-dev/oidc');
    const subject = await c.query('SELECT 1 FROM external_user_subject WHERE user_id=$1 AND subject=$2 AND tenant_id=$3', [input.ownerProfileId, input.ownerAuthSubject, process.env.AUTH_ISSUER]);
    assert.equal(subject.rowCount, 1, 'subject-match');
    const profile = await c.query('SELECT * FROM user_profile WHERE id=$1 FOR UPDATE', [input.ownerProfileId]);
    assert.equal(profile.rowCount, 1, 'profile-match'); assert.equal(profile.rows[0].nickname, input.profileNickname, 'nickname-match');
    const pet = await c.query('SELECT * FROM pet WHERE id=$1 AND user_id=$2 AND name=$3 FOR UPDATE', [input.petId, input.ownerProfileId, input.expectedPetName]);
    assert.equal(pet.rowCount, 1, 'pet-match');
    const photos = await c.query('SELECT count(*)::int n FROM pet_attachment WHERE pet_id=$1', [input.petId]);
    const userPhotos = await c.query('SELECT count(*)::int n FROM user_attachment WHERE user_id=$1', [input.ownerProfileId]);
    assert.equal(photos.rows[0].n, 0); assert.equal(userPhotos.rows[0].n, 0);
    const refs = await c.query("SELECT conrelid::regclass::text AS child FROM pg_constraint WHERE contype='f' AND confrelid='pet'::regclass");
    assert.deepEqual(refs.rows.map(r => r.child).sort(), ['pet_attachment']);
    assert.equal(typeof pet.rows[0].personalities, 'string');
    let deleted = 0;
    if (mode === 'delete') {
      const result = await c.query('DELETE FROM pet WHERE id=$1 AND user_id=$2 AND name=$3 RETURNING id', [input.petId, input.ownerProfileId, input.expectedPetName]);
      assert.equal(result.rowCount, 1); deleted = 1;
      assert.equal((await c.query('SELECT 1 FROM pet WHERE id=$1', [input.petId])).rowCount, 0);
      const after = await c.query('SELECT * FROM user_profile WHERE id=$1', [input.ownerProfileId]);
      assert.deepEqual(after.rows, profile.rows);
      await c.query('COMMIT');
    } else { await c.query('ROLLBACK'); }
    console.log(JSON.stringify({ ownerAndNameVerified: true, photos: 0, profilePreserved: true, deletedPets: deleted, personalityStorage: 'embedded pet.personalities', separatePersonalityRows: 0, committed: mode === 'delete' }));
  }
} catch (error) {
  await c.query('ROLLBACK').catch(() => {});
  console.log(JSON.stringify({ failed: true, error: error.name, code: error.code, check: ['subject-match','profile-match','nickname-match','pet-match'].find(label => error.message.startsWith(label)) }));
  process.exitCode = 1;
} finally { await c.end(); }
