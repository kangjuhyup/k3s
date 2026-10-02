// Authorized dev-only fixture worker. Operator injects seedInput through stdin.
// Structured stdout contains NEW fixture mappings for the private checkpoint only.
import assert from 'node:assert/strict';
import {Client} from 'pg';
import {readDatabaseConnectionOptions} from '@core/database';
const {createInternalAuthAssertion}=await import(new URL('../../../auth-assertion/dist/src/index.js',import.meta.resolve('@core/auth')));
const {users,tenantId,mode}=globalThis.seedInput;
assert(['account','match'].includes(mode));assert(users.length<=25);
const c=new Client(readDatabaseConnectionOptions({get:(k,f)=>process.env[k]??f}));
const scopes=['account:read','account:write','match:read','match:write'];
async function gql(query,variables,identity){
 const headers={'content-type':'application/json'};
 if(identity)headers['x-gaegaeting-principal']=createInternalAuthAssertion({tenantId,subject:identity.authSubject,userId:identity.internalULID,scopes,roles:[]},{secret:process.env.INTERNAL_AUTH_ASSERTION_SECRET,issuer:'gaegaeting-gateway',audience:mode});
 const r=await fetch(`http://127.0.0.1:${mode==='account'?2800:2801}/${mode}/graphql`,{method:'POST',headers,body:JSON.stringify({query,variables}),signal:AbortSignal.timeout(25000)});
 if(!r.ok)throw Error('http-'+r.status);const result=await r.json();if(result.errors?.length)throw Error('graphql-'+(result.errors[0].extensions?.code??'error'));return result.data;
}
try{
 await c.connect();
 if(mode==='account'){assert.equal(process.env.NODE_ENV,'development');assert.equal(process.env.REGISTRATION_MOCK_ENABLED,'true');assert.equal(process.env.AUTH_TENANT_CODE,'gaegaeting-dev');}
 for(const u of users){
  const start=Date.now();let stage='guard';
  try{
   assert.equal(u.username,'qa_seoul_20261002_'+String(u.ordinal).padStart(4,'0'));assert(u.ordinal>=1&&u.ordinal<=1000);
   if(mode==='account'){
    stage='signup';const input={...u.registration,tenantId,password:u.password};
    const result=await gql('mutation($input:RegisterAccountInput!){registerAccount(input:$input){authSubject}}',{input});const authSubject=result.registerAccount.authSubject;assert.equal(typeof authSubject,'string');
    stage='mapping';const r=await c.query('SELECT a.user_id,a.auth_subject FROM account_signup a JOIN external_user_subject e ON e.user_id=a.user_id AND e.subject=a.auth_subject AND e.tenant_id=a.auth_issuer WHERE a.username=$1 AND a.auth_issuer=$2 AND a.status=$3',[u.username,process.env.AUTH_ISSUER,'COMPLETED']);assert.equal(r.rowCount,1);assert.equal(r.rows[0].auth_subject,authSubject);const internalULID=r.rows[0].user_id;assert(/^[0-9A-HJKMNP-TV-Z]{26}$/.test(internalULID));const identity={authSubject,internalULID};
    if(u.identity){assert.equal(u.identity.authSubject,authSubject);assert.equal(u.identity.internalULID,internalULID);}
    stage='profile';let profile=(await gql('query{myProfile{id nickname bio}}',{},identity)).myProfile;
    if(!profile)profile=(await gql('mutation($input:CreateUserProfileInput!){createProfile(input:$input){id nickname bio}}',{input:u.profile},identity)).createProfile;
    assert.equal(profile.id,internalULID);assert.equal(profile.nickname,u.profile.nickname);assert.equal(profile.bio,u.profile.bio);
    stage='pet';const existing=await c.query('SELECT id,name,description FROM pet WHERE user_id=$1',[internalULID]);assert(existing.rowCount<=1);let petId;
    if(existing.rowCount){assert.equal(existing.rows[0].name,u.pet.name);assert.equal(existing.rows[0].description,u.pet.description);petId=existing.rows[0].id;}
    else{const {certification,...petInput}=u.pet;assert.equal(certification,false);petId=(await gql('mutation($input:CreatePetInput!){createPet(input:$input){id}}',{input:petInput},identity)).createPet.id;}
    const counts=await c.query('SELECT (SELECT count(*)::int FROM user_attachment WHERE user_id=$1) AS u,(SELECT count(*)::int FROM pet_attachment WHERE pet_id=$2) AS p',[internalULID,petId]);assert.equal(counts.rows[0].u,0);assert.equal(counts.rows[0].p,0);
    console.log(JSON.stringify({ordinal:u.ordinal,accountComplete:true,authSubject,internalULID,petId}));
    await new Promise(r=>setTimeout(r,Math.max(0,1300-(Date.now()-start))));
   }else{
    const identity=u.identity;assert(identity?.authSubject&&identity.internalULID);stage='location-read';
    let r=await c.query('SELECT latitude,longitude,city,district FROM location WHERE user_id=$1',[identity.internalULID]);
    if(!r.rowCount){stage='location-api';await gql('mutation($input:SetLocationInput!){setCurrentLocation(input:$input)}',{input:{latitude:u.location.latitude,longitude:u.location.longitude}},identity);r=await c.query('SELECT latitude,longitude,city,district FROM location WHERE user_id=$1',[identity.internalULID]);}
    assert.equal(r.rowCount,1);assert(Math.abs(Number(r.rows[0].latitude)-u.location.latitude)<1e-6);assert(Math.abs(Number(r.rows[0].longitude)-u.location.longitude)<1e-6);
    assert(!r.rows[0].city||r.rows[0].city===u.location.city);assert(!r.rows[0].district||r.rows[0].district===u.location.district);
    stage='location-label';if(r.rows[0].city!==u.location.city||r.rows[0].district!==u.location.district){const update=await c.query('UPDATE location SET city=$2,district=$3 WHERE user_id=$1 AND (city IS NULL OR city=$2) AND (district IS NULL OR district=$3)',[identity.internalULID,u.location.city,u.location.district]);assert.equal(update.rowCount,1);}
    console.log(JSON.stringify({ordinal:u.ordinal,locationComplete:true}));
   }
  }catch(e){console.log(JSON.stringify({ordinal:u.ordinal,failed:true,stage,error:e.message.startsWith('graphql-')||e.message.startsWith('http-')?e.message:e.name,code:e.code}));process.exitCode=1;break;}
 }
}catch(e){console.log(JSON.stringify({failed:true,error:e.name,code:e.code}));process.exitCode=1;}finally{await c.end();}
