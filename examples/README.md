# examples/sample-course

A course folder exactly as `./install` and `cs108 new` produce it, with:

| assignment | kind | grader | what it shows |
|---|---|---|---|
| `a01` | auto | `autograder.js` | the JavaScript grader; `assignment.json` names it, the harness runs it with `node` |
| `a02` | auto | `autograder.py` | the Python grader, same contract, same `test.js`; the harness runs it with `python3` |
| `a09` | manual | none | no bundle, no workflow, empty restore list; `collect` and `sheet` still work |

Every assignment here passes `verify` as it stands (starter scores 0 of 4,
answers score 4 of 4), so the way to write a real assignment is to copy one
of these and change it, running `verify` after each change.

The two graders differ only in language. Diff them side by side to see the
contract; the config block at the top of each is the only part an
instructor normally edits.

To try it without touching GitHub:

```bash
export COURSEKIT_COMMAND=cs108
cd examples/sample-course
python3 ../../coursekit/__main__.py verify
python3 ../../coursekit/__main__.py           # the status screen (GitHub will read as unknown)
```
