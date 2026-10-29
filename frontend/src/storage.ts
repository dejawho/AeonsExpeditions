// Saved expeditions live only in this browser (IndexedDB). Nothing is stored on the server.
import type { Save } from "./types";

const DB_NAME = "aeons-expeditions";
const STORE = "saves";
const EXPORT_FORMAT = "aeons-expeditions-save";

let memory: Map<string, Save> | null = null; // fallback when IndexedDB is unavailable (private mode...)

function open(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    if (typeof indexedDB === "undefined") return reject(new Error("IndexedDB unavailable"));
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = () => req.result.createObjectStore(STORE, { keyPath: "id" });
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function tx<T>(mode: IDBTransactionMode, run: (s: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  const db = await open();
  return new Promise((resolve, reject) => {
    const req = run(db.transaction(STORE, mode).objectStore(STORE));
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function withFallback<T>(idb: () => Promise<T>, mem: (m: Map<string, Save>) => T): Promise<T> {
  if (!memory) {
    try {
      return await idb();
    } catch {
      memory = new Map();
      console.warn("IndexedDB unavailable: saves will last only until the page is closed.");
    }
  }
  return mem(memory);
}

export const storageIsPersistent = () => memory === null;

export async function requestPersistence() {
  try {
    await navigator.storage?.persist?.();
  } catch {
    /* optional */
  }
}

export const listSaves = () =>
  withFallback(
    async () => (await tx<Save[]>("readonly", (s) => s.getAll())).sort((a, b) => b.updatedAt.localeCompare(a.updatedAt)),
    (m) => [...m.values()].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt)),
  );

export const getSave = (id: string) =>
  withFallback(
    async () => (await tx<Save | undefined>("readonly", (s) => s.get(id))) ?? null,
    (m) => m.get(id) ?? null,
  );

export const putSave = (save: Save) =>
  withFallback(
    async () => {
      await tx("readwrite", (s) => s.put({ ...save, updatedAt: new Date().toISOString() }));
    },
    (m) => {
      m.set(save.id, { ...save, updatedAt: new Date().toISOString() });
    },
  );

export const deleteSave = (id: string) =>
  withFallback(
    async () => {
      await tx("readwrite", (s) => s.delete(id));
    },
    (m) => {
      m.delete(id);
    },
  );

export function newId() {
  return crypto.randomUUID?.() ?? `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

// --- export / import (to move a save between devices or keep a backup) ---------------
export function exportSave(save: Save) {
  const blob = new Blob([JSON.stringify({ format: EXPORT_FORMAT, version: 1, save }, null, 1)], {
    type: "application/json",
  });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `${save.name.replace(/[^\w-]+/g, "_")}.aeonsave.json`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  // revoking immediately cancels the download in some browsers
  setTimeout(() => URL.revokeObjectURL(a.href), 10_000);
}

export async function importSave(file: File): Promise<Save> {
  const data = JSON.parse(await file.text());
  if (data?.format !== EXPORT_FORMAT || !data.save?.expedition?.nodes || !data.save?.story) {
    throw new Error("This file is not an Aeon's Expeditions save.");
  }
  const save: Save = { ...data.save, id: newId(), actions: data.save.actions ?? [], notes: data.save.notes ?? "" };
  await putSave(save);
  return save;
}
