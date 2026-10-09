"""Map handedness, view interaction and presentation-only report upgrades."""
import shutil,subprocess,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))

class MapTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'),'Node required for offline renderer tests')
    def test_world_and_gps_handedness_markers_click_and_rotation_share_projection(self):
        source=(ROOT/'src/trackview.js').read_text(encoding='utf-8')
        checks=r'''
const assert=require('assert/strict');
const bounds={minX:0,maxX:20,minY:0,maxY:10};
const area=points=>points.reduce((sum,p,i)=>{const q=points[(i+1)%points.length];return sum+p[0]*q[1]-q[0]*p[1]},0);
const triangle=[[0,0],[20,0],[20,10]];
for(const rotation of [0,90,-90,180]){
 const screen=InputScopeTrack.projection(bounds,440,400,{rotation});
 const world=InputScopeTrack.projection(bounds,440,400,{invertY:true,rotation});
 assert(area(triangle.map(p=>screen(...p)))>0);
 assert(area(triangle.map(p=>world(...p)))<0);
}
global.devicePixelRatio=1;
const context=()=>new Proxy({},{get:(o,k)=>o[k]||(()=>{}),set:(o,k,v)=>(o[k]=v,true)});
function view(frame,recorded){
 const v=Object.create(InputScopeTrack.View.prototype),entry={id:'A',length:20,duration:1,color:'#709de0',points:recorded?[[0,0,0,0],[.5,10,10,10],[1,20,20,0]]:[]};
 Object.assign(v,{frame,canvas:{clientWidth:440,clientHeight:400},back:{},ctx:context(),bg:context(),mode:{},source:{},zoomLabel:{},key:'',zoom:1,rotation:0,panX:0,panY:0,lineScale:{value:1},entries:[entry],route:recorded?entry:null,baseline:null,diagram:recorded?null:{points:[[0,0,0],[.5,10,10],[1,20,0]]},length:20,calibration:{}});
 return v;
}
global.InputScopeLab={fraction:(distance,length)=>distance/length,distance:(fraction,length)=>fraction*length};
for(const frame of ['recorded_world_xz','gps_mercator_m']){
 const v=view(frame,true),before=JSON.stringify(v.entries[0].points);
 const result=v.draw([{id:'A',t:.5,d:10}])[0];
 assert.deepEqual(result.xy,v.project(10,10));assert(result.xy[1]<v.project(10,0)[1]);
 let seek;v.onSeekDistance=(distance,time)=>seek=[distance,time];v.pick(...result.xy);assert.deepEqual(seek,[10,.5]);
 v.rotate(90);const rotated=v.draw([{id:'A',t:.5,d:10}])[0];v.pick(...rotated.xy);assert.deepEqual(seek,[10,.5]);
 v.zoomAt(1.4,100,150);assert.equal(JSON.stringify(v.entries[0].points),before);
 v.resetView();assert.equal(v.rotation,0);
}
const outline=view('recorded_world_xz',false);outline.draw([{id:'A',t:.5,d:10}]);assert(outline.project(10,10)[1]>outline.project(10,0)[1]);
'''
        result=subprocess.run(['node','-'],input=source+checks,capture_output=True,text=True,encoding='utf-8',timeout=20)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
    def test_upgrade_changes_only_renderer_and_is_idempotent(self):
        from tools.upgrade_maps import PATTERN,replace_renderer
        renderer=PATTERN.search((ROOT/'src/trackview.js').read_bytes()).group()
        old=b'const InputScopeTrack=(()=>{\n return {old:true};\n})();'
        payload=b'<script type="application/octet-stream" id="stintrix-laps">PERSONAL-PAYLOAD</script>'
        prefix=b'const trackCatalog=[{"private":true}];\n';suffix=b'\nconst initial={"laps":[]};'+payload
        upgraded,_=replace_renderer(prefix+old+suffix,renderer)
        self.assertEqual(upgraded,prefix+renderer+suffix)
        self.assertEqual(replace_renderer(upgraded,renderer)[0],upgraded)
        with self.assertRaises(ValueError):replace_renderer(old+old,renderer)
