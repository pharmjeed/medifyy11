"use client";

/**
 * IndexedDB storage for audio chunks during live streaming
 * Survives page refresh, network failures, browser crashes
 * Auto-cleanup after server confirms receipt
 */

export interface AudioChunk {
  visitId: string;
  seq: number;
  payload: string; // base64 PCM16
  timestamp: number; // when captured
  synced: boolean; // confirmed by server
}

const DB_NAME = "medify_audio_streaming";
const STORE_NAME = "chunks";
const DB_VERSION = 1;

let dbInstance: IDBDatabase | null = null;

async function getDB(): Promise<IDBDatabase> {
  if (dbInstance) return dbInstance;

  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);

    req.onerror = () => reject(req.error);
    req.onsuccess = () => {
      dbInstance = req.result;
      resolve(dbInstance);
    };

    req.onupgradeneeded = (event) => {
      const db = (event.target as IDBOpenDBRequest).result;
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        const store = db.createObjectStore(STORE_NAME, { keyPath: ["visitId", "seq"] });
        store.createIndex("visitId", "visitId", { unique: false });
        store.createIndex("synced", "synced", { unique: false });
        store.createIndex("timestamp", "timestamp", { unique: false });
      }
    };
  });
}

/** Store a chunk and return the number of pending chunks */
export async function storeChunk(chunk: AudioChunk): Promise<number> {
  const db = await getDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction([STORE_NAME], "readwrite");
    const store = tx.objectStore(STORE_NAME);

    store.put(chunk);

    const countReq = store.index("visitId").count(chunk.visitId);

    tx.oncomplete = () => {
      resolve(countReq.result);
    };
    tx.onerror = () => reject(tx.error);
  });
}

/** Get all unsynced chunks for a visit, ordered by seq */
export async function getPendingChunks(visitId: string): Promise<AudioChunk[]> {
  const db = await getDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction([STORE_NAME], "readonly");
    const store = tx.objectStore(STORE_NAME);
    const index = store.index("visitId");

    const range = IDBKeyRange.only(visitId);
    const req = index.getAll(range);

    tx.onerror = () => reject(tx.error);
    req.onerror = () => reject(req.error);
    req.onsuccess = () => {
      const chunks = req.result as AudioChunk[];
      resolve(chunks.filter(c => !c.synced).sort((a, b) => a.seq - b.seq));
    };
  });
}

/** Mark chunks as synced and return count of remaining unsynced */
export async function markSynced(visitId: string, seqs: number[]): Promise<number> {
  const db = await getDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction([STORE_NAME], "readwrite");
    const store = tx.objectStore(STORE_NAME);

    for (const seq of seqs) {
      const req = store.get([visitId, seq]);
      req.onsuccess = () => {
        const chunk = req.result as AudioChunk | undefined;
        if (chunk) {
          chunk.synced = true;
          store.put(chunk);
        }
      };
    }

    // Count remaining unsynced after all updates
    const countReq = store.index("visitId").getAll(IDBKeyRange.only(visitId));

    tx.oncomplete = () => {
      const all = countReq.result as AudioChunk[];
      const unsynced = all.filter(c => !c.synced).length;
      resolve(unsynced);
    };
    tx.onerror = () => reject(tx.error);
  });
}

/** Clean up all synced chunks for a visit and return count deleted */
export async function cleanupSyncedChunks(visitId: string): Promise<number> {
  const db = await getDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction([STORE_NAME], "readwrite");
    const store = tx.objectStore(STORE_NAME);
    const index = store.index("visitId");

    const range = IDBKeyRange.only(visitId);
    const getAllReq = index.getAll(range);

    getAllReq.onsuccess = () => {
      const chunks = getAllReq.result as AudioChunk[];
      let deleted = 0;

      for (const chunk of chunks) {
        if (chunk.synced) {
          store.delete([chunk.visitId, chunk.seq]);
          deleted += 1;
        }
      }

      tx.oncomplete = () => resolve(deleted);
    };

    tx.onerror = () => reject(tx.error);
  });
}

/** Get buffer size estimate (bytes) for a visit */
export async function getBufferSize(visitId: string): Promise<number> {
  const db = await getDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction([STORE_NAME], "readonly");
    const store = tx.objectStore(STORE_NAME);
    const index = store.index("visitId");

    const req = index.getAll(IDBKeyRange.only(visitId));

    tx.onerror = () => reject(tx.error);
    req.onerror = () => reject(req.error);
    req.onsuccess = () => {
      const chunks = req.result as AudioChunk[];
      const bytes = chunks.reduce((sum, chunk) => sum + chunk.payload.length, 0);
      resolve(bytes);
    };
  });
}

/** Delete entire visit's chunks (on visit completion or error) */
export async function deleteVisitChunks(visitId: string): Promise<void> {
  const db = await getDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction([STORE_NAME], "readwrite");
    const store = tx.objectStore(STORE_NAME);
    const index = store.index("visitId");

    const range = IDBKeyRange.only(visitId);
    const req = index.openCursor(range);

    req.onsuccess = (event) => {
      const cursor = (event.target as IDBRequest).result as IDBCursorWithValue | null;
      if (cursor) {
        cursor.delete();
        cursor.continue();
      }
    };

    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

/** Auto-cleanup chunks older than TTL (default 24h) */
export async function cleanupOldChunks(ttlMs: number = 24 * 60 * 60 * 1000): Promise<number> {
  const db = await getDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction([STORE_NAME], "readwrite");
    const store = tx.objectStore(STORE_NAME);
    const index = store.index("timestamp");

    const cutoff = Date.now() - ttlMs;
    const range = IDBKeyRange.upperBound(cutoff);
    const req = index.openCursor(range);

    let deleted = 0;
    req.onsuccess = (event) => {
      const cursor = (event.target as IDBRequest).result as IDBCursorWithValue | null;
      if (cursor) {
        cursor.delete();
        deleted += 1;
        cursor.continue();
      }
    };

    tx.oncomplete = () => resolve(deleted);
    tx.onerror = () => reject(tx.error);
  });
}
