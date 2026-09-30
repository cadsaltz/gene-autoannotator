import "server-only";

import { MongoClient } from "mongodb";

import {
  ANNOTATION_COLLECTION_NAME,
  ANNOTATION_DATABASE_NAME,
  getAnnotationStorageHealth,
} from "./annotationStore";
import { redactConnectionStrings } from "./redact";

const SERVER_SELECTION_TIMEOUT_MS = 1000;

function getMongoUri() {
  const mongoUri = process.env.MONGO_URI || process.env.MONGODB_URI;
  if (!mongoUri) {
    throw new Error("MONGO_URI is not configured for the Next.js server");
  }
  return mongoUri;
}

function getGlobalMongoCache() {
  if (!globalThis.__geneAutoannotatorMongo) {
    globalThis.__geneAutoannotatorMongo = {
      client: null,
      promise: null,
      uri: null,
    };
  }
  return globalThis.__geneAutoannotatorMongo;
}

export async function getMongoClient() {
  const mongoUri = getMongoUri();
  const cache = getGlobalMongoCache();

  if (cache.client && cache.uri === mongoUri) {
    return cache.client;
  }

  if (!cache.promise || cache.uri !== mongoUri) {
    cache.uri = mongoUri;
    cache.promise = new MongoClient(mongoUri, {
      serverSelectionTimeoutMS: SERVER_SELECTION_TIMEOUT_MS,
    }).connect();
  }

  cache.client = await cache.promise;
  return cache.client;
}

export async function getAnnotationsCollection() {
  const client = await getMongoClient();
  return client.db(ANNOTATION_DATABASE_NAME).collection(ANNOTATION_COLLECTION_NAME);
}

export async function getNextAnnotationHealth() {
  try {
    const client = await getMongoClient();
    return getAnnotationStorageHealth({
      databaseName: ANNOTATION_DATABASE_NAME,
      async ping() {
        await client.db("admin").command({ ping: 1 });
      },
    });
  } catch (error) {
    return {
      status: process.env.MONGO_URI || process.env.MONGODB_URI ? "unavailable" : "unconfigured",
      message: redactConnectionStrings(error.message),
      source: "next",
    };
  }
}
