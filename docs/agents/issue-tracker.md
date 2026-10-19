# Issue tracker: GitHub

Issues and PRDs for this repo live as GitHub issues. Use the `gh` CLI for all operations.

## Conventions

- **Create an issue**: `gh issue create --title "..." --body-file ...`
- **Read an issue**: `gh issue view <number> --comments`
- **List issues**: `gh issue list --state open --json number,title,body,labels,assignees`
- **Comment**: `gh issue comment <number> --body-file ...`
- **Label**: `gh issue edit <number> --add-label "..."` / `--remove-label "..."`
- **Close**: `gh issue close <number> --comment "..."` or comment then close

Infer the repo from `git remote -v` — `gh` does this automatically inside a clone.

## Pull requests as a triage surface

**PRs as a request surface: no.**

## Wayfinding operations

How `/wayfinder` expresses maps, tickets, blocking, and the frontier in this repo. (Prefer body convention for blocking so `gh` stays reliable.)

### Labels

- The **map** is a GitHub issue labelled `wayfinder:map`.
- Each **ticket** is a GitHub issue labelled `wayfinder:<type>`, one of: `wayfinder:research`, `wayfinder:prototype`, `wayfinder:grilling`, `wayfinder:task`.

### Parent / child

A ticket declares its map with a first-line body reference:

```
Map: #<map-number>
```

List a map's children: `gh issue list --state all --search "Map: #<map-number> in:body" --json number,title,state,labels,assignees`

### Blocking

```
Blocked by: #<n>, #<m>
```

A ticket is **unblocked** when every listed blocker is closed.

### Frontier

Open children of the map that are **unblocked** and **unclaimed** (no assignee).

### Claiming

`gh issue edit <number> --add-assignee @me` before work.

### Resolving

Resolution comment, close the ticket, append one line to the map's `## Decisions so far`.

### Assets

Link assets from the resolution comment (repo paths or URLs); do not paste large bodies into the issue.
