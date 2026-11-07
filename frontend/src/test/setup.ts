import '@testing-library/jest-dom';

// ResizeObserver mock for React Flow / jsdom
global.ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
};

// Mock DOM measurements for jsdom
window.DOMMatrixReadOnly = window.DOMMatrixReadOnly || (class DOMMatrixReadOnly {
  m22 = 1;
} as any);




