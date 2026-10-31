declare module 'react' {
  export type ReactNode = any
  export type FormEvent = any
  export function useState<T = any>(initial: T): [T, (value: any) => void]
  export function useEffect(effect: () => void | (() => void), deps?: any[]): void
}

declare module 'react/jsx-runtime' {
  export function jsx(...args: any[]): any
  export function jsxs(...args: any[]): any
  export const Fragment: any
}

declare module 'react-dom/client' {
  export function createRoot(element: Element): { render(node: any): void }
}

declare namespace JSX {
  interface IntrinsicElements {
    [element: string]: any
  }
}
