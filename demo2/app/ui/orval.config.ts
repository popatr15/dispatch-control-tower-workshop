import { defineConfig } from "orval";

export default defineConfig({
  dispatch: {
    input: "./openapi.json",
    output: {
      target: "./src/lib/api.ts",
      client: "react-query",
      httpClient: "axios",
      mode: "single",
      override: {
        query: { useSuspenseQuery: true },
      },
    },
  },
});
