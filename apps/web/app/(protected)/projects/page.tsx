// TODO(v2): this page pre-dates the v2.0 homeowner/tenant pivot
// (docs/product-vision.md). Reframe before V1 ships:
//   - Empty-state copy ("Projects group drawings and share them with
//     collaborators") is architect/multi-user framing. Replace with
//     homeowner/tenant language — a project is one undertaking
//     (kitchen remodel, office fit-out), not a folder of drawings.
//   - Remove the "assign drawings to it from the drawing page"
//     sentence; the v2 mental model puts the project first, drawings
//     are one possible input ("Grounds").
//   - Post-login entry should be a conversational composer +
//     project-type picker, not a bare list. This list page still
//     exists in v2 but isn't the front door.
//   - ProjectRow needs project type, state (designing/priced/quoted),
//     and a thumbnail (see ProjectRow.tsx TODO).
import { CreateProjectForm } from "@/components/projects/CreateProjectForm";
import { ProjectRow } from "@/components/projects/ProjectRow";
import { listProjectsServer } from "@/lib/api-server";


export const metadata = {
  title: "Projects · Atlas",
};


export default async function ProjectsPage() {
  const data = await listProjectsServer();
  // (protected) layout already validates auth; a null here means the
  // session dropped mid-render — treat as empty.
  const projects = data?.projects ?? [];

  return (
    <main className="min-h-screen bg-bg-base bg-grid-fade px-2 py-6">
      <div className="mx-auto max-w-[960px]">
        <header className="flex items-center justify-between mb-4">
          <div>
            <h1 className="text-3xl font-semibold text-text-primary">
              Projects
            </h1>
            <p className="text-sm text-text-secondary mt-0.5">
              {projects.length === 0
                ? "No projects yet."
                : `${projects.length} ${projects.length === 1 ? "project" : "projects"}`}
            </p>
          </div>
          <CreateProjectForm />
        </header>

        {projects.length === 0 ? (
          <div className="rounded border border-border-subtle bg-bg-surface p-3 text-sm text-text-secondary">
            Projects group drawings and share them with collaborators.
            Create one with the <span className="text-text-primary font-medium">New project</span>{" "}
            button, then assign drawings to it from the drawing page.
          </div>
        ) : (
          <ul className="list-none">
            {projects.map((p) => (
              <li key={p.id}>
                <ProjectRow project={p} />
              </li>
            ))}
          </ul>
        )}
      </div>
    </main>
  );
}
