import type { operations } from "./generated/openapi";
import { useProjectMutation, type ProjectMutationInput } from "./runtime";
import type { MutationDelta } from "./types";


type RevisionFields = "baseRevision" | "entityRevision";
type ClientCommand<T> = T extends Record<string, unknown> ? Omit<T, RevisionFields> : never;

export type FragmentCreateCommand = ClientCommand<operations["createFragment"]["requestBody"]>;
export type FragmentUpdateCommand = ClientCommand<operations["updateFragment"]["requestBody"]>;
export type FragmentClipboardImportCommand = ClientCommand<operations["importFragmentsFromClipboard"]["requestBody"]>;
export type FragmentPromoteCommand = ClientCommand<operations["promoteFragmentToPlot"]["requestBody"]>;

type Mutate = (input: ProjectMutationInput) => Promise<MutationDelta>;

export function fragmentMutationClient(mutate: Mutate) {
  return {
    create(command: FragmentCreateCommand) {
      return mutate({ path: "/fragments", method: "POST", payload: command });
    },
    update(entityId: string, command: FragmentUpdateCommand) {
      return mutate({
        path: `/fragments/${encodeURIComponent(entityId)}`,
        method: "PATCH",
        payload: command,
      });
    },
    importClipboard(command: FragmentClipboardImportCommand) {
      return mutate({ path: "/fragments/import-clipboard", method: "POST", payload: command });
    },
    promote(entityId: string, command: FragmentPromoteCommand) {
      return mutate({
        path: `/fragments/${encodeURIComponent(entityId)}/to-plot`,
        method: "POST",
        payload: command,
      });
    },
    remove(entityId: string) {
      return mutate({
        path: `/entities/${encodeURIComponent(entityId)}`,
        method: "DELETE",
        payload: {},
      });
    },
  };
}

export function useFragmentMutations() {
  const mutation = useProjectMutation();
  return {
    ...mutation,
    ...fragmentMutationClient((input) => mutation.mutateAsync(input)),
  };
}
