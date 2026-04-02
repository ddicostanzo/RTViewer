// No database storage needed for RT Viewer.
export interface IStorage {}
export class MemStorage implements IStorage {}
export const storage = new MemStorage();
