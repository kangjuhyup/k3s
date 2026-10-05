// Dev-only deployment verification. Pass two existing synthetic fixture identities in memory.
import assert from 'node:assert/strict';
import {randomUUID} from 'node:crypto';
import {setTimeout as delay} from 'node:timers/promises';
import {PNG} from 'pngjs';
import {createInternalAuthAssertion} from '@core/auth-assertion';
import {createRequire} from 'node:module';
const {Client}=createRequire(import.meta.resolve('@core/database'))('pg');
import {readDatabaseConnectionOptions} from '@core/database';
const {users,tenantId}=globalThis.challengeSmokeInput;
assert.equal(process.env.NODE_ENV,'development');assert.equal(users.length,2);
assert(users.every(u=>u.fixtureOrdinal>=998 && u.fixtureOrdinal<=999));
const endpoint='http://127.0.0.1:'+process.env.CHALLENGE_SERVICE_API_PORT+'/challenge/graphql';
const scopes=['challenge:read','challenge:write'];
const ownedWalks=[],enrollments=[],photoKeys=[];let stage='health';const proof={};
async function raw(query,variables={},user=users[0],options={}) {
 const token=user?createInternalAuthAssertion({tenantId,subject:user.authSubject,userId:user.internalULID,scopes:options.scopes??scopes,roles:options.admin?['ADMIN']:[]},{secret:process.env.INTERNAL_AUTH_ASSERTION_SECRET,issuer:'gaegaeting-gateway',audience:'challenge'}):null;
 const r=await fetch(endpoint,{method:'POST',headers:{'content-type':'application/json',...(token?{'x-gaegaeting-principal':token}:{})},body:JSON.stringify({query,variables}),signal:AbortSignal.timeout(20000)});
 return r.json();
}
async function gql(query,variables={},user=users[0],options={}) {const j=await raw(query,variables,user,options);if(j.errors)throw Error('GraphQL '+j.errors[0].extensions?.code);return j.data;}
const db=new Client(readDatabaseConnectionOptions({get:(k,f)=>process.env[k]??f}));
async function walk(user,routeId=null) {
 const input={requestId:randomUUID(),petIds:[user.petId],routeId};
 const query='mutation($input:StartWalkInput!){startWalk(input:$input){id state startedAt}}';
 const w=(await gql(query,{input},user)).startWalk;ownedWalks.push({id:w.id,user});
 assert.equal((await gql(query,{input},user)).startWalk.id,w.id);
 const start=Date.parse(w.startedAt);await delay(17000);
 const points=[{latitude:0,longitude:0,recordedAt:new Date(start+100).toISOString(),accuracyMeters:5,segment:0},{latitude:0,longitude:0.0012,recordedAt:new Date(start+16100).toISOString(),accuracyMeters:5,segment:0}];
 await gql('mutation($input:AppendWalkPointsInput!){appendWalkPoints(input:$input){id}}',{input:{walkId:w.id,fromIndex:0,points}},user);
 const result=(await gql('mutation($id:ID!,$endedAt:DateTime!){finishWalk(id:$id,endedAt:$endedAt){id state distanceMeters completed coverage}}',{id:w.id,endedAt:new Date().toISOString()},user)).finishWalk;
 assert.equal(result.state,'FINISHED');assert(result.distanceMeters>120);return result;
}
try {
 await db.connect();
 const ssl=(await db.query('SELECT ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid()')).rows[0];assert.equal(ssl.ssl,true);
 const role=(await db.query('SELECT rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls FROM pg_roles WHERE rolname=current_user')).rows[0];assert(Object.values(role).every(v=>v===false));
 assert.equal(Number((await db.query('SELECT count(*) FROM challenge_migrations')).rows[0].count),2);proof.databaseTlsAndRestrictedRole=true;proof.migrations=2;
 assert.equal((await fetch(endpoint.replace('/graphql','/health'))).status,200);
 assert.equal((await raw('{challenges{kind}}',{},null)).errors[0].extensions.code,'UNAUTHENTICATED');
 assert.equal((await raw('{challenges{kind}}',{},users[0],{scopes:[]})).errors[0].extensions.code,'FORBIDDEN');proof.authenticationAndScopes=true;
 assert.equal((await gql('{challenges{kind}}')).challenges.length,2);
 for(const user of users){assert.equal((await gql('{myCurrentWalk{id}}',{},user)).myCurrentWalk,null);}
 stage='source-walk';const source=await walk(users[0]);proof.accountOwnershipAndWalkRecording=true;
 stage='route';const route=(await gql('mutation($input:CreateWalkingRouteInput!){createWalkingRoute(input:$input){id status revision}}',{input:{requestId:randomUUID(),walkId:source.id,fromIndex:0,toIndex:1,details:{title:'배포 검증용 임시 코스',description:'자동 검증 후 삭제',startPlace:'합성 시작점',endPlace:'합성 종료점',tags:['SHADE']}}})).createWalkingRoute;
 const pending=(await gql('mutation($id:ID!){submitWalkingRoute(id:$id){id revision status}}',{id:route.id})).submitWalkingRoute;
 const review='mutation($id:ID!,$revision:Int!){reviewWalkingRoute(id:$id,revision:$revision,decision:"PUBLISH")}';
 assert.equal((await raw(review,{id:route.id,revision:pending.revision})).errors[0].extensions.code,'FORBIDDEN');
 await gql(review,{id:route.id,revision:pending.revision},users[0],{admin:true});
 const other=(await gql('query($id:ID!){walkingRoute(id:$id){id path{latitude longitude} title description}}',{id:route.id},users[1])).walkingRoute;assert.equal(other.path.length,2);
 assert((await raw('query($id:ID!){myWalk(id:$id){id}}',{id:source.id},users[1])).errors);proof.publicRouteAndPrivateTrackBoundary=true;
 stage='join';for(const kind of ['NEIGHBORHOOD_EXPLORER','WALK_DIARY']){
  const input={kind,requestId:randomUUID()};const q='mutation($input:JoinChallengeInput!){joinChallenge(input:$input){id progressCount}}';
  const joined=(await gql(q,{input},users[1])).joinChallenge;enrollments.push(joined.id);assert.equal((await gql(q,{input},users[1])).joinChallenge.id,joined.id);
 }
 stage='follow-route';const followed=await walk(users[1],route.id);assert.equal(followed.completed,true);assert(followed.coverage>=0.8);proof.otherUserRouteCompletion=true;
 stage='photo';const upload=(await gql('mutation($walkId:ID!){beginWalkingPhotoUpload(walkId:$walkId){id uploadUrl}}',{walkId:followed.id},users[1])).beginWalkingPhotoUpload;
 const png=new PNG({width:2,height:2});png.data.fill(180);const bytes=PNG.sync.write(png);
 assert.equal((await fetch(upload.uploadUrl,{method:'PUT',headers:{'content-type':'image/png'},body:bytes})).status,200);
 const photo=(await gql('mutation($id:ID!){completeWalkingPhotoUpload(id:$id){id status url}}',{id:upload.id},users[1])).completeWalkingPhotoUpload;assert.equal(photo.status,'READY');
 const signed=await fetch(photo.url);assert.equal(signed.status,200);assert.equal(PNG.sync.read(Buffer.from(await signed.arrayBuffer())).width,2);
 const anon=new URL(photo.url);anon.search='';assert.equal((await fetch(anon)).status,403);
 const keys=(await db.query('SELECT upload_key,object_key FROM walking_photo WHERE id=$1 AND user_id=$2',[photo.id,users[1].internalULID])).rows[0];photoKeys.push(keys.upload_key,keys.object_key);proof.realSignedPngUploadAndRead=true;
 stage='diary';const input={walkId:followed.id,expectedRevision:0,content:'배포 검증 산책 일기',mood:'HAPPY',photoIds:[photo.id],visibility:'PRIVATE'};
 const save='mutation($input:SaveWalkingDiaryInput!){saveWalkingDiary(input:$input){id revision content visibility photos{id}}}';
 const diary=(await gql(save,{input},users[1])).saveWalkingDiary;assert.equal(diary.content,input.content);
 assert((await raw('query($id:ID!){myWalkingDiary(id:$id){id content}}',{id:diary.id},users[0])).errors);
 const reviews='query($id:ID!){walkingRouteReviews(routeId:$id){id content photos{id}}}';assert.equal((await gql(reviews,{id:route.id})).walkingRouteReviews.length,0);
 await gql(save,{input:{...input,expectedRevision:diary.revision,visibility:'PUBLIC'}},users[1]);const published=(await gql(reviews,{id:route.id})).walkingRouteReviews;assert.equal(published.length,1);assert.equal(published[0].content,input.content);proof.diaryPersistenceAndVisibility=true;
 for(const id of enrollments)assert.equal((await gql('query($id:ID!){myChallenge(id:$id){progressCount}}',{id},users[1])).myChallenge.progressCount,1);proof.challengeProgress=true;
} catch(error) {proof.failureStage=stage;proof.failureCode=error instanceof assert.AssertionError?'assertion':String(error.message).replace(/[^A-Za-z _-]/g,'').slice(0,80);process.exitCode=1;}
finally {
 try {
  for(const w of ownedWalks.toReversed())await gql('mutation($id:ID!){deleteWalk(id:$id)}',{id:w.id},w.user);
  for(const id of enrollments)await gql('mutation($id:ID!){cancelChallenge(id:$id)}',{id},users[1]);
  for(const w of ownedWalks){const row=(await db.query('SELECT state,points,author_name FROM walking_record WHERE id=$1 AND user_id=$2',[w.id,w.user.internalULID])).rows[0];assert.equal(row.state,'DELETED');assert.deepEqual(row.points,[]);assert.equal(row.author_name,'');}
  if(photoKeys.length){const pending=await db.query('SELECT object_key FROM walking_media_cleanup WHERE object_key=ANY($1::text[])',[photoKeys]);assert(pending.rows.some(row=>row.object_key===photoKeys[0]));}
  proof.ownedRecordsDeletedAndMediaCleanupQueued=true;
 }catch{proof.cleanupFailed=true;process.exitCode=1;}
 await db.end();console.log(JSON.stringify({proof,privateCleanupKeys:photoKeys}));
}
