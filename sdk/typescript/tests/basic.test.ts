import { describe, it, expect } from 'vitest';

describe('Basic test suite', () => {
  it('should pass a basic assertion', () => {
    expect(true).toBe(true);
  });

  it('should perform simple math', () => {
    expect(2 + 2).toBe(4);
  });

  it('should verify the test runner is working', () => {
    expect(typeof describe).toBe('function');
    expect(typeof it).toBe('function');
    expect(typeof expect).toBe('function');
  });
});