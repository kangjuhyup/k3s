// Read-only final fixture verification; only aggregate output is public.
import assert from 'node:assert/strict';import {Client} from 'pg';import {readDatabaseConnectionOptions} from '@core/database';
const {mode,users}=globalThis.fixtureVerification;assert.equal(users.length,1000);
const ids=users.map(u=>u.identity.internalULID);assert.equal(new Set(ids).size,1000);
const c=new Client(readDatabaseConnectionOptions({get:(k,f)=>process.env[k]??f}));
try{await c.connect();await c.query('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY');const proof={};
if(mode==='account'){
 const signups=(await c.query('SELECT username,user_id,auth_subject,auth_issuer,status FROM account_signup WHERE user_id=ANY($1)',[ids])).rows;
 const subjects=(await c.query('SELECT user_id,subject,tenant_id FROM external_user_subject WHERE user_id=ANY($1)',[ids])).rows;
 const profiles=(await c.query('SELECT id,name,nickname,gender,region,bio,status FROM user_profile WHERE id=ANY($1)',[ids])).rows;
 const pets=(await c.query('SELECT id,user_id,name,description,certification FROM pet WHERE user_id=ANY($1)',[ids])).rows;
 for(const rows of [signups,subjects,profiles,pets])assert.equal(rows.length,1000);
 for(const u of users){const id=u.identity.internalULID;const a=signups.find(x=>x.user_id===id);const s=subjects.find(x=>x.user_id===id);const p=profiles.find(x=>x.id===id);const pet=pets.find(x=>x.user_id===id);
 assert.equal(a.username,u.username);assert.equal(a.auth_subject,u.identity.authSubject);assert.equal(a.auth_issuer,process.env.AUTH_ISSUER);assert.equal(a.status,'COMPLETED');assert.equal(s.subject,a.auth_subject);assert.equal(s.tenant_id,a.auth_issuer);
 assert.equal(p.name,u.registration.name);assert.equal(p.nickname,u.profile.nickname);assert.equal(p.bio,u.profile.bio);assert.equal(p.region,0);assert.equal(p.status,0);assert.equal(p.gender,u.registration.gender==='MALE'?0:1);assert.equal(pet.id,Number(u.identity.petId));assert.equal(pet.name,u.pet.name);assert.equal(pet.description,u.pet.description);assert.equal(pet.certification,false);}
 const photos=(await c.query('SELECT (SELECT count(*)::int FROM user_attachment WHERE user_id=ANY($1)) AS users,(SELECT count(*)::int FROM pet_attachment WHERE pet_id=ANY($2)) AS pets',[ids,pets.map(p=>p.id)])).rows[0];assert.equal(photos.users,0);assert.equal(photos.pets,0);
 Object.assign(proof,{signups:1000,issuerSubjectMappings:1000,profiles:1000,pets:1000,activeSeoulProfiles:1000,male:profiles.filter(p=>p.gender===0).length,female:profiles.filter(p=>p.gender===1).length,photos:0,certificationBypass:false});
}else{
 const rows=(await c.query('SELECT user_id,latitude,longitude,city,district FROM location WHERE user_id=ANY($1)',[ids])).rows;assert.equal(rows.length,1000);
 for(const u of users){const r=rows.find(x=>x.user_id===u.identity.internalULID);assert(Math.abs(Number(r.latitude)-u.location.latitude)<1e-6);assert(Math.abs(Number(r.longitude)-u.location.longitude)<1e-6);assert.equal(r.city,u.location.city);assert.equal(r.district,u.location.district);}
 const perDistrict={};for(const r of rows)perDistrict[r.district]=(perDistrict[r.district]??0)+1;assert.equal(Object.keys(perDistrict).length,25);assert(Object.values(perDistrict).every(n=>n===40));
 assert.equal((await c.query('SELECT 1 FROM main_area WHERE user_id=ANY($1)',[ids])).rowCount,0);
 const representatives=users.filter((u,i)=>i%40===0);assert.equal(new Set(representatives.map(u=>u.district)).size,25);const counts=[];
 for(const u of representatives){const lat=u.location.latitude;const lng=u.location.longitude;const dlat=10000/111000;const dlng=10000/(111000*Math.cos(lat*Math.PI/180));const r=await c.query(`SELECT count(*)::int n FROM location l WHERE l.user_id=ANY($1) AND l.user_id<>$2 AND l.latitude BETWEEN $3 AND $4 AND l.longitude BETWEEN $5 AND $6 AND NOT EXISTS(SELECT 1 FROM pair p WHERE p.active=true AND p.left_user_id=LEAST($2,l.user_id) AND p.right_user_id=GREATEST($2,l.user_id)) AND NOT EXISTS(SELECT 1 FROM feed f JOIN feed_item fi ON fi.feed_id=f.id WHERE f.user_id=$2 AND f.date>=to_char(current_date-6,'YYYYMMDD') AND fi.target_user_id=l.user_id)`,[ids,u.identity.internalULID,lat-dlat,lat+dlat,lng-dlng,lng+dlng]);assert(r.rows[0].n>=2);counts.push(r.rows[0].n);}
 Object.assign(proof,{locations:1000,perDistrict,mainAreaInserted:0,representativesChecked:25,allRepresentativesHaveAtLeastTwoCandidates:true,minimumEligibleFixtureCandidates:Math.min(...counts)});
}
await c.query('ROLLBACK');console.log(JSON.stringify(proof));}catch(e){console.log(JSON.stringify({failed:true,error:e.name,code:e.code}));process.exitCode=1;}finally{await c.end()}
