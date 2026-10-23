/* Synthetic scientific content only. No network or model calls. */
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const R=require('../sage/console_static/reading.js');
const c={id:'fixture',title:'Synthetic',problem:'Unknown cause. Prior work is limited.',mechanism:'Test a controlled change.',baselines:'B1 equal compute; B2 sham',
  protocol:{primary_endpoint_ids:['E1'],endpoints:[{id:'E1',role:'primary',definition:'Synthetic test'},{id:'E2',role:'secondary',definition:'Exploration'}],variables:[{id:'V1',definition:'Binary success'}],decision_rule:{support_when:'Positive contrast'},extra_rule:'Keep this too'},extra_field:'Unknown future field',status:'provisional'};
const doc={shared_protocol:{definitions:{unit:'item'}},shared_scientific_context:{verification_boundary:'Not yet tested'}};
const before=JSON.stringify([c,doc]),v=R.proposal(c,doc),md=R.markdown(v,{run:'synthetic-run'});
for(const s of ['Unknown cause','B1 equal compute','B2 sham','Positive contrast','Keep this too','Unknown future field','Not yet tested','item'])assert.ok(md.includes(s),s);
assert.equal(JSON.stringify([c,doc]),before,'Projection never rewrites the candidate');
assert.ok(v.sections.find(s=>s.id==='experiment').fields.some(f=>f.key==='endpoints'&&f.value[1].role==='secondary'));
assert.ok(R.markdown(R.proposal({id:'empty',protocol:'legacy plain protocol'})).includes('legacy plain protocol'));
assert.ok(R.markdown(R.proposal({id:'empty'})).includes('原稿未单列，待补充'));
const card={claims:[{category:'problem',claim:'Uncertain proposition',source_span_ids:['p1'],entailment_audit:{verdict:'uncertain'}}],unverified_claims:[{category:'results',claim:'Rejected result',entailment_audit:{verdict:'unsupported'},source_span_ids:['absent']}],source_spans:{p1:{text:'Exact quotation'}}};
const groups=R.evidence(card);assert.equal(groups.find(g=>g.key==='problem').claims[0].sources[0].span.text,'Exact quotation');assert.equal(groups.find(g=>g.key==='results').claims[0].verdict,'unsupported');assert.equal(groups.find(g=>g.key==='results').claims[0].sources[0].span,null);
assert.equal(groups.find(g=>g.key==='motivation').claims.length,0);
// Renderer cannot execute hostile paper text or hide unsupported status; full protocol remains in the DOM.
function element(tag){return {tag,children:[],textContent:'',append(...x){this.children.push(...x)},setAttribute(){},set innerHTML(_){throw Error('No raw HTML allowed')}};}
const ctx=vm.createContext({SageReading:R,document:{createElement:element},URL,Blob,setTimeout});
vm.runInContext(fs.readFileSync(require.resolve('../sage/console_static/reading-ui.js'),'utf8'),ctx);
const dom=ctx.SageReadingUI.proposal({...c,title:'<script>bad()</script>'},doc);
assert.ok(JSON.stringify(dom).includes('<script>bad()</script>'));assert.ok(JSON.stringify(dom).includes('Positive contrast'));
assert.ok(JSON.stringify(ctx.SageReadingUI.evidence(card)).includes('模型建议：不支持'));
console.log('Reading projection: field preservation, endpoint roles, missing content, evidence provenance, and inert text passed');
