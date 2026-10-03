/* Person 2 owns this interpreter. Person 3 embeds it before playground-runtime.js.
 * Scientific AST data only: no eval, Function, DOM, network, or generated code.
 */
(function (root) {
  'use strict';
  const LIMITS = Object.freeze({iterations: 100, elements: 10000, steps: 20000, depth: 32});
  const registry = Object.create(null);
  function register(names, lo, hi = lo, params = []) {
    names.split(' ').forEach(n => { registry[n] = {arity: [lo, hi], params}; });
  }
  register('add subtract multiply divide pow dot matmul equal not_equal less less_equal greater greater_equal and or', 2);
  register('negate sqrt exp log log2 abs sin cos not transpose flatten', 1);
  register('sum product mean min max argmin argmax softmax softmax_rows normalize cumsum difference', 1, 1, ['axis']);
  register('clip where', 3);
  register('index', 2);
  register('slice', 1, 1, ['start', 'stop', 'step', 'end_ref']);
  register('reshape', 1, 1, ['shape']);
  register('concat', 1, 100, ['axis', 'promote_scalars']);
  register('range', 1, 3);
  register('map elementwise', 1, 1, ['body']);
  register('iterate scan', 2, 2, ['body']);
  const own = (x, k) => Object.prototype.hasOwnProperty.call(x, k);
  const fail = msg => { throw new Error(msg); };
  const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
  const flat = v => Array.isArray(v) ? v.flat(Infinity) : [v];
  function shape(v) {
    if (!Array.isArray(v)) return [];
    const child = v.length ? shape(v[0]) : [];
    if (v.some(x => !same(shape(x), child))) fail('Arrays must be rectangular');
    const s = [v.length, ...child];
    if (s.length > 2 || flat(v).length > LIMITS.elements) fail('Array size/rank limit exceeded');
    return s;
  }
  function numeric(v) {
    shape(v);
    if (flat(v).some(x => typeof x !== 'number' || !Number.isFinite(x))) fail('Expected finite numeric value');
    return v;
  }
  function boolean(v) {
    shape(v);
    if (flat(v).some(x => typeof x !== 'boolean')) fail('Expected boolean value');
    return v;
  }
  function finite(v) {
    shape(v);
    if (flat(v).some(x => typeof x === 'number' && !Number.isFinite(x))) fail('Nonfinite calculation result');
    return v;
  }
  function integer(v, name) {
    if (typeof v !== 'number' || !Number.isSafeInteger(v)) fail(name + ' must be an integer scalar');
    return v;
  }
  function broadcast(...values) {
    const ss = values.map(shape).filter(s => s.length);
    if (ss.some(s => !same(s, ss[0]))) fail('Only scalar broadcasting or identical shapes allowed');
  }
  function unary(v, fn) { return Array.isArray(v) ? v.map(x => unary(x, fn)) : fn(v); }
  function binary(a, b, fn) {
    if (Array.isArray(a)) return a.map((x, i) => binary(x, Array.isArray(b) ? b[i] : b, fn));
    if (Array.isArray(b)) return b.map(x => binary(a, x, fn));
    return fn(a, b);
  }
  function choose(c, a, b) {
    if (Array.isArray(c)) return c.map((x, i) => choose(x, Array.isArray(a) ? a[i] : a, Array.isArray(b) ? b[i] : b));
    return c ? a : b;
  }
  function axisOf(params, v, defaultAxis = null) {
    const rank = shape(v).length;
    let axis = own(params, 'axis') ? params.axis : defaultAxis;
    if (axis === null) return null;
    integer(axis, 'axis');
    if (axis < -rank || axis >= rank) fail('Invalid axis');
    return (axis + rank) % rank;
  }
  function columns(v) { return v[0].map((_, i) => v.map(r => r[i])); }
  function reduction(v, axis, fn) {
    const rank = shape(v).length;
    if (axis === null || rank < 2) return fn(flat(v));
    return (axis === 0 ? columns(v) : v).map(fn);
  }
  function along(v, axis, fn) {
    const rank = shape(v).length;
    if (rank < 2) return fn(flat(v));
    if (axis === null) return fn(flat(v));
    if (axis === 1) return v.map(fn);
    return columns(columns(v).map(fn));
  }
  function compensated(a, history = false) {
    let total = 0, correction = 0; const out = [];
    a.forEach(value => {
      const updated = total + value;
      correction += Math.abs(total) >= Math.abs(value) ? (total - updated) + value : (value - updated) + total;
      total = updated;
      if (history) out.push(total + correction);
    });
    return history ? out : total + correction;
  }
  const sum = a => compensated(a);
  const argmax = a => a.indexOf(Math.max(...a));
  function typeOf(v) {
    const s = shape(v);
    const kind = s.length === 2 ? 'matrix' : s.length === 1 ? 'vector' : typeof v === 'boolean' ? 'boolean' : typeof v === 'string' ? 'categorical' : 'scalar';
    return {kind, shape: s};
  }
  function validateControl(c, v) {
    finite(v);
    const actual = typeOf(v), wanted = c.value_kind === 'sequence' ? 'vector' : c.value_kind;
    if (actual.kind !== wanted && !(c.type === 'select' && c.value_kind === 'categorical' && ['scalar', 'boolean'].includes(actual.kind))) fail(c.id + ': wrong value kind');
    if (c.shape && !same(c.shape, actual.shape)) fail(c.id + ': wrong shape');
    const editors = {slider: ['scalar'], number: ['scalar'], checkbox: ['boolean'], select: ['scalar', 'categorical', 'boolean'], vector_editor: ['vector'], matrix_editor: ['matrix'], sequence_editor: ['sequence']};
    if (!editors[c.type]?.includes(c.value_kind)) fail(c.id + ': incompatible editor');
    if (c.type === 'select' && !(c.options || []).some(x => same(x, v))) fail(c.id + ': not an option');
    if (flat(v).some(x => typeof x === 'number' && ((c.min != null && x < c.min) || (c.max != null && x > c.max)))) fail(c.id + ': out of bounds');
    if (flat(v).some(x => !['number', 'boolean', 'string'].includes(typeof x))) fail('Invalid literal');
    if (['vector','matrix','sequence'].includes(c.value_kind)) numeric(v);
  }
  function references(e, locals = new Set(), depth = 0) {
    if (depth > LIMITS.depth || !e || typeof e !== 'object' || Array.isArray(e)) fail('Invalid expression/depth');
    if (own(e, 'ref')) {
      if (Object.keys(e).length !== 1 || typeof e.ref !== 'string') fail('Invalid reference');
      return new Set(locals.has(e.ref) ? [] : [e.ref]);
    }
    if (own(e, 'const')) {
      if (Object.keys(e).length !== 1) fail('Invalid constant');
      finite(e.const);
      if (flat(e.const).some(x => !['number', 'boolean', 'string'].includes(typeof x))) fail('Invalid constant');
      return new Set();
    }
    const rule = registry[e.op], p = e.params || {};
    if (!rule || !Array.isArray(e.inputs) || e.inputs.length < rule.arity[0] || e.inputs.length > rule.arity[1]) fail('Unknown op or invalid arity');
    if (Object.keys(p).some(k => !rule.params.includes(k))) fail('Unsupported parameters');
    if (Object.keys(e).some(k => !['id', 'op', 'inputs', 'params', 'kind', 'shape', 'display', 'label', 'format'].includes(k))) fail('Unknown expression fields');
    const refs = new Set();
    e.inputs.forEach(x => references(x, locals, depth + 1).forEach(r => refs.add(r)));
    if (e.op === 'slice' && own(p, 'end_ref')) {
      if (own(p, 'stop') || typeof p.end_ref !== 'string') fail('Invalid end_ref');
      if (!locals.has(p.end_ref)) refs.add(p.end_ref);
    }
    if (['map', 'elementwise', 'iterate', 'scan'].includes(e.op)) {
      const scoped = new Set(locals);
      (e.op === 'iterate' ? ['state', 'index'] : e.op === 'scan' ? ['state', 'item', 'index'] : ['item', 'index']).forEach(x => scoped.add(x));
      references(p.body, scoped, depth + 1).forEach(r => refs.add(r));
    }
    return refs;
  }
  function graph(spec) {
    const controls = new Set(spec.controls.map(c => c.id)), nodes = new Map(spec.computation.nodes.map(n => [n.id, n]));
    if (controls.size !== spec.controls.length || nodes.size !== spec.computation.nodes.length) fail('Duplicate IDs');
    if ([...nodes.keys()].some(n => controls.has(n))) fail('Control/node collision');
    if ([...controls, ...nodes.keys()].some(n => ['state', 'item', 'index'].includes(n))) fail('Reserved ID');
    const refs = new Map([...nodes].map(([id, n]) => [id, references(n)]));
    for (const deps of refs.values()) for (const ref of deps) if (!nodes.has(ref) && !controls.has(ref)) fail('Unknown reference: ' + ref);
    if (spec.computation.outputs.some(id => !nodes.has(id) && !controls.has(id))) fail('Unknown output');
    const order = [], done = new Set(), active = new Set();
    function visit(id) {
      if (controls.has(id) || done.has(id)) return;
      if (active.has(id)) fail('Cyclic computation graph');
      active.add(id);
      [...refs.get(id)].sort().forEach(visit);
      active.delete(id); done.add(id); order.push(id);
    }
    nodes.forEach((_, id) => visit(id));
    return {controls, nodes, refs, order};
  }
  function deriveDependencies(spec) {
    const g = graph(spec), out = Object.create(null);
    [...g.controls, ...g.nodes.keys()].sort().forEach(source => {
      const affected = new Set(); let changed = true;
      while (changed) {
        changed = false;
        g.refs.forEach((deps, id) => {
          if (!affected.has(id) && [...deps].some(d => d === source || affected.has(d))) { affected.add(id); changed = true; }
        });
      }
      out[source] = [...affected].sort();
    });
    return out;
  }
  function compatible(a,b) {return a.length===b.length&&a.every((d,i)=>d===null||b[i]===null||d===b[i]);}
  function literalType(v) {const t=typeOf(v),leaf=flat(v)[0];return {dtype:typeof leaf==='boolean'?'boolean':typeof leaf==='string'?'categorical':'numeric',shape:t.shape};}
  function typeKind(t){return t.shape.length===2?'matrix':t.shape.length===1?'vector':t.dtype==='boolean'?'boolean':t.dtype==='categorical'?'categorical':'scalar';}
  function mergedShape(args){let result=[];args.filter(t=>t.shape.length).forEach(t=>{if(!result.length)result=t.shape;else{if(!compatible(result,t.shape))fail('Static shape mismatch');result=result.map((d,i)=>d===null?t.shape[i]:d);}});return result;}
  function checkMapProjection(op, count, bodyShape) {
    let projected = count;
    if (op === 'elementwise') {
      if (bodyShape.length) fail('elementwise body must return scalar');
    } else {
      if (bodyShape.length + 1 > 2) fail('map projected output exceeds rank limit');
      if (bodyShape.includes(null)) return;
      for (const dimension of bodyShape) projected *= dimension;
    }
    if (projected > LIMITS.elements) fail(op + ' projected output exceeds element limit');
  }
  function inferExpression(e,types,depth=0){
    if(depth>LIMITS.depth)fail('Type inference depth');
    if(own(e,'ref'))return types[e.ref];if(own(e,'const'))return literalType(e.const);
    const op=e.op,p=e.params||{},a=e.inputs.map(x=>inferExpression(x,types,depth+1));
    const result=(dtype,shape)=>({dtype,shape});
    function numbers(...v){if(v.some(t=>t.dtype!=='numeric'))fail(op+': numeric operands required');}
    function axis(){const ax=own(p,'axis')?p.axis:null;if(ax===null)return null;if(!Number.isInteger(ax)||ax< -a[0].shape.length||ax>=a[0].shape.length)fail('Static invalid axis');return (ax+a[0].shape.length)%a[0].shape.length;}
    if(['map','elementwise','iterate','scan'].includes(op)){
      const first=a[0],scope=Object.assign(Object.create(null),types,{index:result('numeric',[])});
      if(['map','elementwise'].includes(op)){if(!first.shape.length)fail('Static map requires array');scope.item=result(first.dtype,op==='elementwise'?[]:first.shape.slice(1));}
      else{scope.state=first;if(op==='iterate'){numbers(a[1]);if(a[1].shape.length)fail('Static iteration count must be scalar');}else{if(a[1].shape.length!==1)fail('Static scan requires vector');scope.item=result(a[1].dtype,[]);}}
      const body=inferExpression(p.body,scope,depth+1);let out;
      if(['iterate','scan'].includes(op)){if(body.dtype!==first.dtype||!compatible(body.shape,first.shape))fail('Static iteration state mismatch');out=op==='iterate'?first:result(first.dtype,[a[1].shape[0],...first.shape]);}
      else if(op==='elementwise'){if(body.shape.length)fail('Static elementwise body must return scalar');out=result(body.dtype,first.shape);}
      else out=result(body.dtype,[first.shape[0],...body.shape]);
      if(out.shape.length>2)fail('Static rank limit');return out;
    }
    if(op==='where'){if(a[0].dtype!=='boolean'||a[1].dtype!==a[2].dtype)fail('Static where types');return result(a[1].dtype,mergedShape(a));}
    if(['equal','not_equal'].includes(op)){if(a[0].dtype!==a[1].dtype)fail('Static comparison types');return result('boolean',mergedShape(a));}
    if(['and','or','not'].includes(op)){if(a.some(t=>t.dtype!=='boolean'))fail('Static logic types');return result('boolean',mergedShape(a));}
    if(['less','less_equal','greater','greater_equal'].includes(op)){numbers(...a);return result('boolean',mergedShape(a));}
    if(['add','subtract','multiply','divide','pow','clip'].includes(op)){numbers(...a);return result('numeric',mergedShape(a));}
    if(['negate','sqrt','exp','log','log2','abs','sin','cos'].includes(op)){numbers(...a);return a[0];}
    if(['dot','matmul','transpose'].includes(op)){
      numbers(...a);const s=a[0].shape;
      if(op==='transpose'){if(s.length!==2)fail('Static transpose requires matrix');return result('numeric',[s[1],s[0]]);}
      const t=a[1].shape;if(op==='dot'){if(s.length!==1||!compatible(s,t))fail('Static dot shape');return result('numeric',[]);}
      if(s.length!==2||t.length!==2||!compatible([s[1]],[t[0]]))fail('Static matmul shape');return result('numeric',[s[0],t[1]]);
    }
    if(op==='index'){numbers(a[1]);if(!a[0].shape.length||a[1].shape.length)fail('Static index types');return result(a[0].dtype,a[0].shape.slice(1));}
    if(op==='flatten')return result(a[0].dtype,[a[0].shape.includes(null)?null:a[0].shape.reduce((x,y)=>x*y,1)]);
    if(op==='reshape'){
      if(!Array.isArray(p.shape)||p.shape.length<1||p.shape.length>2||p.shape.some(n=>!Number.isInteger(n)||n<1))fail('Static reshape dimensions');
      if(!a[0].shape.includes(null)&&a[0].shape.reduce((x,y)=>x*y,1)!==p.shape.reduce((x,y)=>x*y,1))fail('Static reshape size');return result(a[0].dtype,p.shape);
    }
    if(op==='slice'){
      if(!a[0].shape.length)fail('Static slice requires array');let length=null;
      if(own(p,'end_ref')){numbers(types[p.end_ref]);if(types[p.end_ref].shape.length)fail('Static slice endpoint');}
      else if(a[0].shape[0]!==null)length=operation('slice',[Array(a[0].shape[0]).fill(0)],p,null).length;
      return result(a[0].dtype,[length,...a[0].shape.slice(1)]);
    }
    if(op==='concat'){
      const dims=a.map(t=>!t.shape.length&&p.promote_scalars?[1]:t.shape),rank=dims[0].length;
      if(!rank||dims.some(s=>s.length!==rank)||a.some(t=>t.dtype!==a[0].dtype))fail('Static concat types');let ax=own(p,'axis')?p.axis:0;
      if(!Number.isInteger(ax)||ax< -rank||ax>=rank)fail('Static concat axis');ax=(ax+rank)%rank;
      const others=s=>s.filter((_,i)=>i!==ax);if(dims.some(s=>!compatible(others(dims[0]),others(s))))fail('Static concat shape');
      const total=dims.some(s=>s[ax]===null)?null:sum(dims.map(s=>s[ax]));const out=[...dims[0]];out[ax]=total;return result(a[0].dtype,out);
    }
    numbers(...a);if(op==='range'){if(a.some(t=>t.shape.length))fail('Static range arguments');return result('numeric',[null]);}
    const ax=axis(),dims=a[0].shape;
    if(['sum','product','mean','min','max','argmin','argmax'].includes(op))return result('numeric',ax===null?[]:dims.filter((_,i)=>i!==ax));
    if(op==='softmax_rows'&&dims.length!==2)fail('Static softmax_rows matrix required');
    if(['softmax','softmax_rows','normalize'].includes(op))return a[0];
    if(['cumsum','difference'].includes(op)){
      const out=ax!==null?[...dims]:[dims.includes(null)?null:dims.reduce((x,y)=>x*y,1)];
      if(op==='difference'){const d=ax===null?0:ax;if(out[d]!==null)out[d]=Math.max(out[d]-1,0);}return result('numeric',out);
    }
    fail('Cannot infer operation '+op);
  }
  function validateTypesShapes(spec){
    const g=graph(spec),types=Object.create(null);spec.controls.forEach(c=>{types[c.id]=literalType(c.default);});
    g.order.forEach(id=>{const node=g.nodes.get(id),t=inferExpression(node,types);
      if(node.kind&&typeKind(t)!==(node.kind==='sequence'?'vector':node.kind))fail(id+': static declared kind mismatch');
      if(node.shape&&!compatible(node.shape,t.shape))fail(id+': static declared shape mismatch');types[id]=t;});return types;
  }
  function engine() {
    let steps = 0;
    function expression(e, values, mask = null, depth = 0) {
      if (++steps > LIMITS.steps || depth > LIMITS.depth) fail('Execution step/depth limit');
      if (own(e, 'ref')) { if (!own(values, e.ref)) fail('Unknown reference'); return values[e.ref]; }
      if (own(e, 'const')) return e.const;
      const op = e.op, p = e.params || {};
      if (op === 'where') {
        const condition = boolean(expression(e.inputs[0], values, mask, depth + 1));
        if (!Array.isArray(condition)) return expression(e.inputs[condition ? 1 : 2], values, mask, depth + 1);
        const active = mask === null ? unary(condition, () => true) : binary(condition, mask, (_, m) => m);
        const yes = binary(active, condition, (a, c) => a && c), no = binary(active, condition, (a, c) => a && !c);
        let a = flat(yes).some(Boolean) ? expression(e.inputs[1], values, yes, depth + 1) : null;
        let b = flat(no).some(Boolean) ? expression(e.inputs[2], values, no, depth + 1) : null;
        if (a === null) a = b === null ? 0 : b;
        if (b === null) b = a;
        broadcast(condition, a, b);
        return choose(condition, a, b);
      }
      const args = e.inputs.map(x => expression(x, values, mask, depth + 1));
      if (['map', 'elementwise'].includes(op)) {
        if (!Array.isArray(args[0])) fail('map/elementwise requires array');
        const items = op === 'elementwise' ? flat(args[0]) : args[0];
        const scope = Object.create(null), inputType = literalType(args[0]);
        Object.keys(values).forEach(name => { scope[name] = literalType(values[name]); });
        scope.item = {dtype: inputType.dtype, shape: op === 'elementwise' ? [] : inputType.shape.slice(1)};
        scope.index = {dtype: 'numeric', shape: []};
        checkMapProjection(op, items.length, inferExpression(p.body, scope).shape);
        if (!items.length) return op === 'elementwise' ? unary(args[0], x => x) : [];
        const out = []; let bodyShape = null;
        for (let index = 0; index < items.length; index++) {
          const candidate = expression(p.body, Object.assign(Object.create(null), values, {item: items[index], index}), null, depth + 1);
          const candidateShape = shape(candidate);
          checkMapProjection(op, items.length, candidateShape);
          if (bodyShape !== null && !same(bodyShape, candidateShape)) fail('map body result shape changed');
          bodyShape = candidateShape;
          out.push(candidate);
        }
        if (op === 'elementwise') {
          if (out.some(Array.isArray)) fail('elementwise body must return scalar');
          return reshape(out, shape(args[0]));
        }
        return finite(out);
      }
      if (['iterate', 'scan'].includes(op)) {
        let count, items;
        if (op === 'iterate') { count = integer(args[1], 'iteration count'); items = Array.from({length: Math.max(0, Math.min(count, 101))}, (_, i) => i); }
        else { if (shape(args[1]).length !== 1) fail('scan requires vector'); items = args[1]; count = items.length; }
        if (count < 0 || count > LIMITS.iterations) fail('Iteration limit exceeded');
        let state = args[0]; const history = [];
        items.forEach((item, index) => {
          const locals = Object.assign(Object.create(null), values, {state, index});
          if (op === 'scan') locals.item = item;
          const next = finite(expression(p.body, locals, null, depth + 1));
          if (!same(typeOf(next), typeOf(args[0]))) fail('Iteration state changed shape/type');
          state = next; history.push(state);
        });
        return op === 'iterate' ? state : finite(history);
      }
      let params = p;
      if (op === 'slice' && own(p, 'end_ref')) params = {...p, stop: expression({ref: p.end_ref}, values, null, depth + 1)};
      return finite(operation(op, args, params, mask));
    }
    return expression;
  }
  function reshape(v, s) {
    if (!Array.isArray(s) || s.length < 1 || s.length > 2 || s.some(n => !Number.isInteger(n) || n < 1)) fail('Invalid reshape');
    const f = flat(v);
    if (s.reduce((a, b) => a * b, 1) !== f.length) fail('reshape size mismatch');
    return s.length === 1 ? f : Array.from({length: s[0]}, (_, i) => f.slice(i * s[1], (i + 1) * s[1]));
  }
  function operation(op, a, p, mask) {
    const binaries = {add: (x,y)=>x+y, subtract:(x,y)=>x-y, multiply:(x,y)=>x*y, divide:(x,y)=>{if(y===0)fail('Division by zero');return x/y;}, pow:Math.pow,
      equal:(x,y)=>x===y, not_equal:(x,y)=>x!==y, less:(x,y)=>x<y, less_equal:(x,y)=>x<=y, greater:(x,y)=>x>y, greater_equal:(x,y)=>x>=y, and:(x,y)=>x&&y, or:(x,y)=>x||y};
    if (own(binaries, op)) {
      if (['and','or'].includes(op)) a.forEach(boolean);
      else if (['equal','not_equal'].includes(op)) {
        const ta = typeof flat(a[0])[0], tb = typeof flat(a[1])[0];
        if (ta !== tb) fail('Comparison types differ');
      } else a.forEach(numeric);
      broadcast(...a);
      if (mask !== null && ['divide','pow'].includes(op)) a = a.map(x => choose(mask, x, 1));
      return binary(a[0], a[1], binaries[op]);
    }
    const unaries = {negate:x=>-x, sqrt:x=>{if(x<0)fail('Negative sqrt');return Math.sqrt(x);}, exp:Math.exp,
      log:x=>{if(x<=0)fail('Nonpositive log');return Math.log(x);}, log2:x=>{if(x<=0)fail('Nonpositive log2');return Math.log2(x);}, abs:Math.abs, sin:Math.sin, cos:Math.cos, not:x=>!x};
    if (own(unaries, op)) {
      op === 'not' ? boolean(a[0]) : numeric(a[0]);
      let v = a[0];
      if (mask !== null && ['sqrt','log','log2','exp'].includes(op)) v = choose(mask, v, 1);
      return unary(v, unaries[op]);
    }
    if (op === 'clip') {
      a.forEach(numeric); broadcast(...a);
      if (flat(binary(a[1], a[2], (x,y)=>x>y)).some(Boolean)) fail('Clip bounds reversed');
      return binary(binary(a[0],a[1],Math.max),a[2],Math.min);
    }
    if (op === 'transpose') { numeric(a[0]); if(shape(a[0]).length!==2)fail('transpose requires matrix'); return columns(a[0]); }
    if (op === 'dot') { a.forEach(numeric); if(shape(a[0]).length!==1 || !same(shape(a[0]),shape(a[1])))fail('dot shape mismatch'); return sum(a[0].map((x,i)=>x*a[1][i])); }
    if (op === 'matmul') {
      a.forEach(numeric); const sa=shape(a[0]),sb=shape(a[1]);
      if(sa.length!==2||sb.length!==2||sa[1]!==sb[0])fail('matmul shape mismatch');
      if(sa[0]*sb[1]>LIMITS.elements)fail('Matrix size limit');
      const cols=columns(a[1]); return a[0].map(row=>cols.map(col=>sum(row.map((x,i)=>x*col[i]))));
    }
    if (op === 'range') {
      a.forEach(x=>integer(x,'range argument')); let start=0,stop=a[0],step=1;
      if(a.length>1){start=a[0];stop=a[1];step=a.length>2?a[2]:1;}
      if(step===0)fail('Zero range step'); const n=Math.max(0,Math.ceil((stop-start)/step));
      if(n>LIMITS.elements)fail('range size limit'); return Array.from({length:n},(_,i)=>start+i*step);
    }
    if(op==='index'){if(!Array.isArray(a[0]))fail('index requires array');let i=integer(a[1],'index');if(i<0)i+=a[0].length;if(i<0||i>=a[0].length)fail('Index bounds');return a[0][i];}
    if(op==='slice') {
      const v=a[0];if(!Array.isArray(v))fail('slice requires array');const step=own(p,'step')?integer(p.step,'step'):1;if(step===0)fail('Zero slice step');
      const n=v.length, positive=step>0;
      function bound(key, fallback){if(!own(p,key))return fallback;let x=integer(p[key],'slice bound');if(x<0)x+=n;return Math.max(positive?0:-1,Math.min(positive?n:n-1,x));}
      const start=bound('start',positive?0:n-1),stop=bound('stop',positive?n:-1),out=[];
      for(let i=start;positive?i<stop:i>stop;i+=step)out.push(v[i]);return out;
    }
    if(op==='flatten')return flat(a[0]);
    if(op==='reshape')return reshape(a[0],p.shape);
    if(op==='concat') {
      const v=a.map(x=>p.promote_scalars&&!Array.isArray(x)?[x]:x);
      if(v.some(x=>!Array.isArray(x)))fail('concat requires arrays');const axis=axisOf(p,v[0],0),rank=shape(v[0]).length;
      if(v.some(x=>shape(x).length!==rank))fail('concat rank mismatch');
      if(axis===0){if(rank===2&&v.some(x=>shape(x)[1]!==shape(v[0])[1]))fail('concat shape mismatch');return v.flat(1);}
      if(v.some(x=>x.length!==v[0].length))fail('concat shape mismatch');return v[0].map((_,i)=>v.flatMap(x=>x[i]));
    }
    numeric(a[0]);if(flat(a[0]).length===0)fail('Empty input');let axis=axisOf(p,a[0]);
    const reductions={sum,product:x=>x.reduce((s,y)=>s*y,1),mean:x=>sum(x)/x.length,min:x=>Math.min(...x),max:x=>Math.max(...x),argmin:x=>x.indexOf(Math.min(...x)),argmax};
    if(own(reductions,op))return reduction(a[0],axis,reductions[op]);
    if(op==='cumsum')return along(a[0],axis,v=>compensated(v,true));
    if(op==='difference')return along(a[0],axis,v=>v.slice(1).map((x,i)=>x-v[i]));
    if(op==='softmax_rows'){if(shape(a[0]).length!==2)fail('softmax_rows requires matrix');axis=1;}
    if(['softmax','softmax_rows','normalize'].includes(op)) {
      const fn=v=>{let terms=v;if(op!=='normalize'){const max=Math.max(...v);terms=v.map(x=>Math.exp(x-max));}const total=sum(terms);if(total===0)fail('Zero total');return terms.map(x=>x/total);};
      if(axis===null){const f=fn(flat(a[0]));const s=shape(a[0]);return s.length?reshape(f,s):f[0];}
      return along(a[0],axis,fn);
    }
    fail('Unknown operation: '+op);
  }
  function evaluate(spec, inputs = {}) {
    const g=graph(spec),values=Object.create(null);
    validateTypesShapes(spec);
    if(Object.keys(inputs).some(k=>!g.controls.has(k)))fail('Unknown input control');
    spec.controls.forEach(c=>{const v=own(inputs,c.id)?inputs[c.id]:c.default;validateControl(c,v);values[c.id]=v;});
    const expr=engine();
    g.order.forEach(id=>{const n=g.nodes.get(id),v=finite(expr(n,values)),t=typeOf(v);
      if(n.kind&&t.kind!==(n.kind==='sequence'?'vector':n.kind))fail(id+': declared kind mismatch');
      if(n.shape&&!same(n.shape,t.shape))fail(id+': declared shape mismatch');values[id]=v;});
    return values;
  }
  function evaluateExpression(e, values = {}) { references(e); return finite(engine()(e,values)); }
  const api = Object.freeze({evaluate, evaluateExpression, deriveDependencies, validateTypesShapes, typeOf, operations: registry, limits: LIMITS});
  if(typeof module==='object'&&module.exports)module.exports=api;
  else root.PaperComputation=api;
})(typeof globalThis==='object'?globalThis:this);
