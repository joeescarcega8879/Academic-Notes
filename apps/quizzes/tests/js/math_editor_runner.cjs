// Ejecuta la lógica pura del editor de fórmulas (static/js/math_editor.js) con casos que manda la prueba de Python.
// Entrada (stdin): lista de {op, args}; salida (stdout): lista de resultados en JSON.
const path = require('path');

const editor = require(path.resolve(__dirname, '../../../../static/js/math_editor.js'));

let entrada = '';
process.stdin.on('data', (trozo) => { entrada += trozo; });
process.stdin.on('end', () => {
  const casos = JSON.parse(entrada);
  const resultados = casos.map(({ op, args }) => {
    if (op === 'insertar') return editor.insertSnippet(...args);
    if (op === 'dentro') return editor.insideMath(...args);
    if (op === 'grupos') return editor.GROUPS;
    throw new Error(`operación desconocida: ${op}`);
  });
  process.stdout.write(JSON.stringify(resultados));
});
