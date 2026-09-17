# {{course_title}} ({{course}})

This folder is the whole course as the `{{course}}` command sees it. Keep it in a
**private** repository: `roster/roster.csv` holds student names and email
addresses, and `answers/` holds solutions.

```
{{folder_name}}/
├── course.json              the only file tying the tools to this course
├── course-history.log       one line per setting change, with the date
├── CHEATSHEET.md            one page of commands, task first
├── roster/
│   └── roster.csv           username,first_name,last_name,email,section,github_id,role
├── assignments/
│   └── a04/
│       ├── assignment.json  kind (auto or manual), grader, restore list
│       ├── README.md        instructions that ship with the starter
│       ├── MAINTENANCE.md   notes to self, never published
│       ├── starter/         EXACTLY what the student receives
│       └── answers/         your reference solution, never published
├── autograders/
│   └── a04/                 OPTIONAL. Absent means graded by hand.
│       ├── autograder.js    the grader (or autograder.py), run by `marks`
│       ├── test.js          authoritative copy of the visible suite
│       └── ...              authoritative copies of every do-not-edit file
└── templates/
    ├── autograde.yml        copied into every autograded template
    └── check.yml            copied into hand-graded templates only if tick_on_manual
```

## The four-command semester

```bash
{{course}} new a04               # make the folders, choose auto or manual
{{course}} verify a04            # check it before anyone sees it
{{course}} template a04 --go     # starter -> GitHub template repository
{{course}} assign a04 --go       # one private repository per student
```

Then, when marks are wanted:

```bash
{{course}} marks a04 --as-of "2026-10-14T23:59:59-04:00"
{{course}} sheet a04
```

Nothing changes GitHub without `--go`. Run `{{course}}` on its own to see what
is out of step, and `{{course}} doctor` when something feels wrong.

## Three things to know

1. **Nothing changes GitHub without `--go`.** Every other invocation is a preview.
2. **Never push a file students have edited.** `patch` refuses; let it.
3. **The green tick is not the grade.** `marks` and `sheet` are.

## Where to read more

The toolkit's `docs/` folder has the long versions: writing an assignment,
score versus complete, troubleshooting, and the runner infrastructure.
