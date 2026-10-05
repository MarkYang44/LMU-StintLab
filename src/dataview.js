/* Exact offline numeric storage; compressed payloads use the browser's gzip stream. */
const StintrixData=(()=>{
 class Table{
  constructor(values,width){this.values=values;this.width=width;this.length=values.length/width;if(!Number.isInteger(this.length))throw Error('遥测矩阵长度无效');return new Proxy(this,{get:(t,p)=>typeof p==='string'&&/^\d+$/.test(p)?t.at(Number(p)):Reflect.get(t,p)})}
  at(i){if(i<0)i+=this.length;if(i<0||i>=this.length)return undefined;return this.values.subarray(i*this.width,(i+1)*this.width)}
  *[Symbol.iterator](){for(let i=0;i<this.length;i++)yield this.at(i)}
  find(fn){let i=0;for(const r of this)if(fn(r,i++))return r}
  filter(fn){const out=[];let i=0;for(const r of this)if(fn(r,i++))out.push(r);return out}
  map(fn){const out=[];let i=0;for(const r of this)out.push(fn(r,i++));return out}
  reduce(fn,initial){let i=0;for(const r of this)initial=fn(initial,r,i++);return initial}
 }
 async function block(id){
  const node=document.getElementById(id);if(!node)throw Error('内嵌数据缺失：'+id);
  if(typeof DecompressionStream!=='function')throw Error('请使用支持离线 gzip 解压的新版 Edge、Chrome 或 Firefox 打开复盘');
  let text=node.textContent;const size=Number(node.dataset.bytes);if(!Number.isSafeInteger(size)||size<0)throw Error('内嵌数据长度无效');
  const output=new Uint8Array(size);let cursor=0,pos=0;
  const stream=new ReadableStream({pull(controller){if(pos>=text.length){text=null;controller.close();return}const part=atob(text.slice(pos,pos+65536));pos+=65536;const bytes=new Uint8Array(part.length);for(let i=0;i<part.length;i++)bytes[i]=part.charCodeAt(i);controller.enqueue(bytes)}});
  const reader=stream.pipeThrough(new DecompressionStream('gzip')).getReader();
  for(;;){const {done,value}=await reader.read();if(done)break;if(cursor+value.length>size)throw Error('内嵌数据超过声明长度');output.set(value,cursor);cursor+=value.length}
  if(cursor!==size)throw Error('内嵌数据不完整');node.remove();return output.buffer;
 }
 async function jsonBlock(id){return JSON.parse(new TextDecoder().decode(await block(id)))}
 async function tableBlock(id,width){return new Table(new Float64Array(await block(id)),width)}
 async function jsonNode(id,value){
  const blob=new Blob([JSON.stringify(value)],{type:'application/json'}),buffer=await new Response(blob.stream().pipeThrough(new CompressionStream('gzip'))).arrayBuffer(),bytes=new Uint8Array(buffer),parts=[];
  for(let i=0;i<bytes.length;i+=49152){const chunk=bytes.subarray(i,i+49152);let text='';for(let j=0;j<chunk.length;j+=4096)text+=String.fromCharCode(...chunk.subarray(j,j+4096));parts.push(btoa(text))}
  const node=document.createElement('script');node.type='application/octet-stream';node.id=id;node.dataset.bytes=blob.size;node.textContent=parts.join('');return node;
 }
 function fromRows(width,iterator){let count=0;for(const row of iterator())count++;const values=new Float64Array(count*width);let i=0;for(const row of iterator()){values.set(row,i);i+=width}return new Table(values,width)}
 return {Table,jsonBlock,tableBlock,jsonNode,fromRows};
})();
