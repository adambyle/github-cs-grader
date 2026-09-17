# score versus complete

`gradebook.csv` has two very different kinds of column, and confusing them
is the single most consequential mistake available in this system.

```
username,name,section,score,max_score,percent,complete,changed,status,commit,repo
jsmith,Jane Smith,A,24,29,82.8,yes,edited app.js (+2 more),graded,a1b2c3d,26fa-cs108/cs108-a04-jsmith
```

## score, max_score, percent: diagnostic

They say how close a student got. Useful to you and to the student. They
feed nothing. A 24/29 is a fact about the code on that commit, produced by
running the instructor's copy of the tests against a fresh clone on the
instructor's machine. It is not a grade and nothing downstream treats it as
one.

## complete: the column the grade table consumes

`yes` when the student pushed **anything at all** beyond the untouched
starter. `no` when the repository is still the starter byte for byte.
Nothing else enters into it: not the score, not whether it builds, not how
much they wrote.

Three things count as a change:

- a starter file whose bytes differ
- a file the starter never had
- a starter file that is gone

The second case matters more than it looks. Some assignments ask students to
**create** a file that does not ship in the starter, and a student who wrote
only that file has still done the work.

It is generous on purpose. The published policy already promised students
that reasonable work counts whether or not every test is green, and
`complete` is that sentence made computable, which is what makes it
survivable at thirty students times fifteen assignments.

## changed: the evidence

The file that produced the `yes`: `edited app.js (+2 more)`, `added
render.js`, `deleted helper.js`. It exists so a disputed cell can be
checked without re-running anything. The deliverable is listed first;
`README.md` edits are pushed to the back because they tell you nothing.

## So why is a student with a low score marked complete?

Because those are answers to two different questions. The score answers
"how much of this works". `complete` answers "did they do the assignment".
A student who pushed a serious attempt that passes four checks out of
twenty-nine did the assignment. A student whose repository is still the
starter did not, whatever the reason.

If you want a threshold, apply it in your own gradebook from the `score`
column. This system records what happened; it does not decide what it is
worth.

## Two things the implementation gets right that are easy to get wrong

**Order.** The comparison runs **before** the grader, on a checkout that has
just been cleaned. `restore` overwrites the provided files and a build
leaves artifacts behind; either would muddy the comparison.

**One definition of "the starter".** The set of files the comparison uses is
computed by the same function `template` uses to decide what to publish
(`Assignment.starter_files()`). Written twice, they drift, and the symptom
is a student marked incomplete because of a file that was never published.

## complete is computed for manual assignments too

It needs only the starter and the checkout, not a grader. `collect` fills
it in, `sheet` carries it into the CSV. This is what makes a hand-graded
assignment a full citizen of the system.

## complete never regresses

`marks` keeps the previous gradebook and compares. A student who read `yes`
in one run must never read `no` in a later run for the same commit. If that
happens it is a bug in the comparison, not a student who un-did their work,
and `marks` says so in capital letters and leaves the previous gradebook
beside the new one.
