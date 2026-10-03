"""Author synthetic frontend cases as IR data; never evaluates their AST.

These cases exercise composition, not paper fidelity. Shared fixtures stay intact.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
def ref(name): return {'ref': name}
def const(value): return {'const': value}
def expr(op, *inputs, **params): return {'op': op, 'inputs': list(inputs), 'params': params}
def node(name, label, expression, kind='scalar', shape=None):
    return {'id': name, **expression, 'kind': kind, 'shape': shape, 'display': True, 'label': label, 'format': None}
def control(name, label, default, kind='scalar', bounds=None):
    result = {'id': name, 'label': label, 'default': default, 'value_kind': kind,
              'type': {'scalar':'number','vector':'vector_editor','matrix':'matrix_editor'}[kind],
              'help': 'Edit this teaching input and follow its downstream values.'}
    if kind != 'scalar': result['shape'] = [len(default), len(default[0])] if kind == 'matrix' else [len(default)]
    if bounds: result.update(min=bounds[0], max=bounds[1], step=bounds[2])
    return result
def visual(kind, value, title, **options): return {'type':kind, 'value':value, 'title':title, 'options':options}
def write(name, title, idea, controls, nodes, visuals, story, layout, changes, answers):
    outputs=[nodes[-1]['id']]
    spec={'schema_version':'1.0','teaching':{'title':title,'idea':idea,
          'why':'Following intermediate values makes the transformation and its assumptions visible.',
          'mental_model':'Change an input, follow the transformation, and compare the computed outcome.'},
          'controls':controls,'computation':{'nodes':nodes,'outputs':outputs},'visuals':visuals,
          'symbols':[{'symbol':c['id'],'meaning':c['label'],'kind':c['value_kind'],'units':None} for c in controls],
          'evidence':[{'id':'synthetic_claim','claim':idea,'blocks':['synthetic_excerpt']}],
          'mechanism_grounding':[{'nodes':[n['id']],'blocks':['synthetic_excerpt'],'relationship':'Synthetic teaching mechanism.'} for n in nodes],
          'provenance':{'simplifications':['A small, bounded teaching model.'], 'toy_examples':['Synthetic frontend acceptance fixture; not extracted from a paper.']},
          'limitation':{'kind':'simplification','text':'This synthetic example illustrates the declared mechanism and does not reproduce a paper experiment.'},
          'explorations':[{'title':label,'change':{'instructions':instruction,'suggested_values':patch},'observe':observe,'why':why,
                           'expectation':{'type':'approx','value':outputs[0],'expected':answer,'tolerance':1e-9}}
                          for (label,instruction,patch,observe,why),answer in zip(changes,answers)],
          'tests':[{'name':'Independent default output','inputs':{},'assertions':[{'value':outputs[0],'op':'approx','expected':DEFAULTS[name],'tolerance':1e-9}]}],
          'invariants':[{'name':'Finite output','value':outputs[0],'assertion':{'op':'all_finite','value':outputs[0]}}]}
    experience={'story':story,'layout':layout,'hero_visual':visuals[0]['value'],
                'calculation_order':[n['id'] for n in nodes],'emphasis_nodes':[outputs[0]],
                'guided_mode':[{'target':controls[0]['id'],'instruction':'Edit the first input; follow the outlined downstream path.','highlight_dependency_path':True},
                               {'target':visuals[0]['value'],'instruction':'Observe the bound result. It comes from the shared computation runtime.'},
                               {'target':outputs[0],'instruction':'Compare the final value with its previous value.'}],
                'annotations':[{'target':outputs[0],'kind':'hint','text':'This is a synthetic teaching case, not a paper experiment.'}]}
    (ROOT/f'tests/fixtures/{name}_ir.json').write_text(json.dumps(spec,indent=2)+'\n',encoding='utf-8')
    (ROOT/f'examples/experiences/{name}.json').write_text(json.dumps(experience,indent=2)+'\n',encoding='utf-8')

DEFAULTS={'iterative':.7119140625,'piecewise':[-1,-.5,.5,1], 'markov':[.562,.438], 'graph':[1,2,1], 'recurrence':.07776}

if __name__=='__main__':
    body=expr('multiply',ref('state'),expr('subtract',const(1),ref('rate')))
    write('iterative','Repeated contraction','A repeated update shrinks a state by a controllable fraction at each step.',
          [control('initial','Initial state',4,bounds=(1,8,1)),control('rate','Update fraction',.25,bounds=(0,.9,.05))],
          [node('history','State after each step',expr('scan',ref('initial'),const([0,1,2,3,4,5]),body=body),'vector',[6]),
           node('final','Final state',expr('iterate',ref('initial'),const(6),body=body))],
          [visual('line_chart','history','Six successive updates'),visual('number','final','Final state')],
          'iterate_and_observe','controls_left',
          [('No contraction','Set the update fraction to zero.',{'rate':0},'The state stays at its initial value.','The multiplier becomes one.'),
           ('Halve each time','Set the update fraction to one half.',{'rate':.5},'Each step halves the previous state.','The multiplier becomes one half.')],[4,.0625])
    write('piecewise','Bounded clipping','Clipping keeps values within a symmetric interval while preserving values already inside.',
          [control('input','Input values',[-2,-.5,.5,2],'vector'),control('bound','Symmetric bound',1,bounds=(.5,3,.5))],
          [node('lower','Lower bound',expr('negate',ref('bound'))),node('clipped','Clipped values',expr('clip',ref('input'),ref('lower'),ref('bound')),'vector',[4])],
          [visual('bar_chart','clipped','Values after clipping')],'compare_cases','comparison',
          [('Tight interval','Set the bound to one half.',{'bound':.5},'Outer values move to the boundary.','Clipping caps values outside the interval.'),
           ('Wide interval','Set the bound to three.',{'bound':3},'Every input is preserved.','Every value fits inside this interval.')],[[-.5,-.5,.5,.5],[-2,-.5,.5,2]])
    write('markov','Two-state transition','Repeated matrix multiplication redistributes a probability row between two states.',
          [control('initial','Initial distribution',[[1,0]],'matrix'),control('transition','Transition matrix',[[.8,.2],[.1,.9]],'matrix'),control('steps','Transition count',3,bounds=(0,10,1))],
          [node('distribution_row','Distribution row',expr('iterate',ref('initial'),ref('steps'),body=expr('matmul',ref('state'),ref('transition'))),'matrix',[1,2]),
           node('distribution','State probabilities',expr('flatten',ref('distribution_row')),'vector',[2])],
          [visual('bar_chart','distribution','Probability in each state',labels=['State A','State B']),visual('heatmap','distribution_row','Distribution row')],
          'input_to_output','controls_left',
          [('One transition','Set the transition count to one.',{'steps':1},'Some mass moves to the other state.','The first row gives the transfer from state A.'),
           ('No transitions','Set the transition count to zero.',{'steps':0},'The initial row is preserved.','No update has been applied.')],[[.8,.2],[1,0]])
    write('graph','Neighbor aggregation','A connectivity matrix collects neighbor features before a gain scales the messages.',
          [control('features','Node features',[[1],[2],[3]],'matrix'),control('gain','Message gain',.5,bounds=(0,2,.25))],
          [node('aggregate','Neighbor sums',expr('matmul',const([[0,1,0],[1,0,1],[0,1,0]]),ref('features')),'matrix',[3,1]),
           node('messages','Scaled messages',expr('multiply',ref('aggregate'),ref('gain')),'matrix',[3,1]),
           node('output','Messages by node',expr('flatten',ref('messages')),'vector',[3])],
          [visual('bar_chart','output','Message values',labels=['A','B','C']),visual('nodes_edges','output','Three connected nodes',nodes=[{'id':n,'label':n} for n in ['A','B','C']],edges=[{'source':'A','target':'B'},{'source':'B','target':'C'}])],
          'build_step_by_step','controls_left',
          [('Remove the gain','Set gain to zero.',{'gain':0},'All messages become zero.','The scale is zero.'),
           ('Unit gain','Set gain to one.',{'gain':1},'Messages equal neighbor sums.','The scale preserves each sum.')],[[0,0,0],[2,4,2]])
    write('recurrence','A system with memory','A recurrence combines retained state with the next input to produce an output history.',
          [control('signal','Input sequence',[1,0,0,0,0,0],'vector'),control('memory','Retention factor',.6,bounds=(0,.9,.1))],
          [node('history','Output history',expr('scan',const(0),ref('signal'),body=expr('add',expr('multiply',ref('state'),ref('memory')),ref('item'))),'vector',[6]),
           node('final','Last output',expr('index',ref('history'),const(-1)))],
          [visual('line_chart','history','Response over time'),visual('number','final','Last output')],
          'cause_and_effect','controls_left',
          [('Forget each step','Set retention to zero.',{'memory':0},'Only the current input contributes.','The prior state is multiplied by zero.'),
           ('Longer memory','Set retention to eight tenths.',{'memory':.8},'The response decays more slowly.','More state is retained at each step.')],[0,.32768])
