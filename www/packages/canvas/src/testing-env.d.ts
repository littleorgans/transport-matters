// Type-level companion to the shell's runtime test-setup.ts: pulls the
// jest-dom matcher augmentation into this package's typecheck program so
// component tests keep compiling standalone.
import "@testing-library/jest-dom/vitest";
