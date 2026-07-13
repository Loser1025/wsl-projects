// Bridges the React UMD global (window.React, loaded by support.js) to bundled code.
// Access is lazy so the bundle can be safely evaluated before React finishes loading.
// Supports both CommonJS (require) and ESM (import) for esbuild compatibility.

// UMD グローバルへの遅延アクセサ
function getReact() {
  if (typeof window === 'undefined' || !window.React) {
    throw new Error('React UMD global not loaded. Ensure React script tag is present.');
  }
  return window.React;
}

function getReactDOM() {
  if (typeof window === 'undefined' || !window.ReactDOM) {
    throw new Error('ReactDOM UMD global not loaded. Ensure ReactDOM script tag is present.');
  }
  return window.ReactDOM;
}

// ラッパー関数
const createHook = (name) => (...args) => getReact()[name](...args);
const createReactDOMMethod = (name) => (...args) => getReactDOM()[name](...args);

// React Proxy
const ReactProxy = new Proxy(
  {},
  {
    get: (_, prop) => createHook(prop),
    apply: (_, __, args) => getReact()(...args),
  }
);

// ReactDOM Proxy
const ReactDOMProxy = new Proxy(
  {},
  {
    get: (_, prop) => createReactDOMMethod(prop),
    apply: (_, __, args) => getReactDOM()(...args),
  }
);

// React hooks and methods
const useState = createHook('useState');
const useEffect = createHook('useEffect');
const createElement = createHook('createElement');
const Fragment = createHook('Fragment');
const createContext = createHook('createContext');
const useContext = createHook('useContext');
const useRef = createHook('useRef');
const useMemo = createHook('useMemo');
const useCallback = createHook('useCallback');
const useReducer = createHook('useReducer');
const useLayoutEffect = createHook('useLayoutEffect');
const useImperativeHandle = createHook('useImperativeHandle');
const useDebugValue = createHook('useDebugValue');
const version = () => getReact().version;
const Children = new Proxy(
  {},
  { get: (_, prop) => createHook('Children')[prop] }
);
const isValidElement = createHook('isValidElement');
const cloneElement = createHook('cloneElement');
const createFactory = createHook('createFactory');

// react/jsx-runtime (automatic JSX transform) expects these exports
const jsx = (type, props, key) =>
  getReact().createElement(type, key !== undefined ? Object.assign({ key }, props) : props);

const jsxs = (type, props, key) =>
  getReact().createElement(type, key !== undefined ? Object.assign({ key }, props) : props);

// ReactDOM methods
const render = createReactDOMMethod('render');
const hydrate = createReactDOMMethod('hydrate');
const unmountComponentAtNode = createReactDOMMethod('unmountComponentAtNode');
const findDOMNode = createReactDOMMethod('findDOMNode');
const createPortal = createReactDOMMethod('createPortal');

// ESM exports
export {
  ReactProxy as React,
  ReactProxy as default,
  ReactDOMProxy as ReactDOM,
  useState,
  useEffect,
  createElement,
  Fragment,
  createContext,
  useContext,
  useRef,
  useMemo,
  useCallback,
  useReducer,
  useLayoutEffect,
  useImperativeHandle,
  useDebugValue,
  version,
  Children,
  isValidElement,
  cloneElement,
  createFactory,
  jsx,
  jsxs,
  render,
  hydrate,
  unmountComponentAtNode,
  findDOMNode,
  createPortal,
};

// CommonJS exports
if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    React: ReactProxy,
    ReactDOM: ReactDOMProxy,
    useState,
    useEffect,
    createElement,
    Fragment,
    createContext,
    useContext,
    useRef,
    useMemo,
    useCallback,
    useReducer,
    useLayoutEffect,
    useImperativeHandle,
    useDebugValue,
    version,
    Children,
    isValidElement,
    cloneElement,
    createFactory,
    jsx,
    jsxs,
    render,
    hydrate,
    unmountComponentAtNode,
    findDOMNode,
    createPortal,
    default: ReactProxy,
  };
}