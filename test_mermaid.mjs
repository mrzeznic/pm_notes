import mermaid from 'mermaid';
import { JSDOM } from 'jsdom';

const dom = new JSDOM(`<!DOCTYPE html><html><body><div id="container"></div></body></html>`);
global.window = dom.window;
global.document = dom.window.document;

mermaid.initialize({ startOnLoad: false });

const graphDefinition = `
gantt
    title Project Timeline
    dateFormat YYYY-MM-DD
    section Project1
    Task 1 : proj0, active, id_1, 2026-08-17, 1d
`;

mermaid.render('graphDiv', graphDefinition).then(result => {
    console.log(result.svg);
}).catch(err => {
    console.error("MERMAID ERROR:", err);
});
