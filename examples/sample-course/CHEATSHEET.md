# cs108  cheatsheet    Web Programming    org 26fa-cs108

Every line is a command you can type. Nothing changes GitHub without `--go`.

## SETTING UP AN ASSIGNMENT

```
cs108 new a04                      make the folders, pick auto or manual
cs108 verify a04                   check it before anyone sees it
cs108 template a04 --go            push the starter to GitHub
cs108 assign a04 --go              create every student's repository
```

## DURING THE ASSIGNMENT

```
cs108                              what is out of step, and what to run
cs108 ui                           the same thing in a browser
cs108 students import form.csv     merge new GitHub usernames
cs108 patch a04                    preview a fix to a do-not-edit file
cs108 patch a04 --go               push it to everyone
cs108 patch a04 --missing --go     add starter files the repos do not have yet
```

## GRADING

```
cs108 marks a04                    run the autograder, write the gradebook
cs108 collect a04                  just download everyone's work
cs108 sheet a04                    a CSV to type marks into
  add --as-of "2026-10-14T23:59:59-04:00" to grade what existed at the deadline
```

## WHEN SOMETHING IS WRONG

```
cs108 doctor                       check everything at once
cs108 doctor --smoke --go          push one job and see it run, queue or fail
cs108 config                       show every setting
cs108 config --check               test GitHub, the org, and the runners
cs108 config runner NEW-NAME       change one
```

## THREE THINGS TO KNOW

```
  Nothing changes GitHub without --go.
  Never push a file students have edited. patch will refuse; let it.
  The green tick is not the grade. marks and sheet are.
```

## WHERE THINGS LIVE

```
assignments/a04/starter/       exactly what the student gets
assignments/a04/answers/       your solution, never published
autograders/a04/               the grading bundle, never published
~/cs108-grading/a04/           everything that comes back
course.json                    every setting; course-history.log says what changed
```

Course folder: `/home/claude/kit/examples/sample-course`. Long versions: the toolkit's `docs/` folder.
