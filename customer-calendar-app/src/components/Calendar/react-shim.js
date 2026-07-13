// Bridges the React UMD global (window.React, loaded by support.js) to bundled code.
// Access is lazy so the bundle can be safely evaluated before React finishes loading.
const lazy = (prop) => (...args) => window.React[prop](...args);

const React = new Proxy(
  {},
  {
    get: (_, prop) => lazy(prop),
    apply: (_, __, args) => window.React(...args),
  }
);

export default React;
export const useState = lazy('useState');
export const useEffect = lazy('useEffect');

// react/jsx-runtime (automatic JSX transform) expects these exports.
export const jsx = (type, props, key) => window.React.createElement(type, key !== undefined ? Object.assign({ key }, props) : props);
export const jsxs = (type, props, key) => window.React.createElement(type, key !== undefined ? Object.assign({ key }, props) : props);
