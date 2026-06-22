# Issue tracker: GitHub

Issues and PRDs for this repo live as GitHub issues in **`ChHsiching/cee-admission-data`**. Use the `gh` CLI for all operations.

> Note: this working directory is not (yet) a git clone of that repo, so `gh`
> cannot infer the repo from `git remote`. Pass
> `--repo ChHsiching/cee-admission-data` explicitly (shown below). Once the
> directory is a clone of the repo, `gh` infers the repo automatically and the
> flag becomes optional.

## Conventions

- **Create an issue**: `gh issue create --repo ChHsiching/cee-admission-data --title "..." --body "..."`. Use a heredoc for multi-line bodies.
- **Read an issue**: `gh issue view <number> --repo ChHsiching/cee-admission-data --comments`, filtering comments by `jq` and also fetching labels.
- **List issues**: `gh issue list --repo ChHsiching/cee-admission-data --state open --json number,title,body,labels,comments --jq '[.[] | {number, title, body, labels: [.labels[].name], comments: [.comments[].body]}]'` with appropriate `--label` and `--state` filters.
- **Comment on an issue**: `gh issue comment <number> --repo ChHsiching/cee-admission-data --body "..."`
- **Apply / remove labels**: `gh issue edit <number> --repo ChHsiching/cee-admission-data --add-label "..."` / `--remove-label "..."`
- **Close**: `gh issue close <number> --repo ChHsiching/cee-admission-data --comment "..."`

## Pull requests as a triage surface

**PRs as a request surface: no.** `/triage` does **not** pull external PRs into the queue — only GitHub Issues are triaged. _(Set to `yes` if this repo starts treating external PRs as feature requests; `/triage` reads this flag.)_

## When a skill says "publish to the issue tracker"

Create a GitHub issue in `ChHsiching/cee-admission-data`.

## When a skill says "fetch the relevant ticket"

Run `gh issue view <number> --repo ChHsiching/cee-admission-data --comments`.
