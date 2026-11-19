// Files Vite imports that are not JavaScript: the type check only needs to know they exist.
declare module '*?raw' {
  const content: string;
  export default content;
}
declare module '*.css';
