// Development-only harness. Node is not required by assessed Python generation.
const fs = require('node:fs');
const runtime = require('../runtime/computation.js');
const tasks = JSON.parse(fs.readFileSync(0, 'utf8'));
const results = tasks.map(task => {
  try {
    return {ok: true, value: task.mode === 'registry' ? runtime.operations
      : task.mode === 'types' ? runtime.validateTypesShapes(task.spec)
      : task.mode === 'dependencies' ? runtime.deriveDependencies(task.spec)
      : task.spec ? runtime.evaluate(task.spec, task.inputs || {})
      : runtime.evaluateExpression(task.expression, task.values || {})};
  } catch (error) { return {ok: false, error: error.message}; }
});
process.stdout.write(JSON.stringify(results));
