---
author: Adam Byle
---

# Adaptation of current features

Some features from the single-user CLI will translate to the new web app. Some will not. This document should comprehensively outline the transition.

## The `--go` flag

Because the interface should be flexible and user-friendly, a confirmation step in the form of `--go` will be omitted from the web interface.

## The `new` command

The interface will allow the creation of a new assignment. Instead of scaffolding empty folders, the user must upload starter code, answers, and auto-graders. The web app should specify to the user that they should maintain a personal copy of these resources on their computers in case there is an issue with the server. The instructor user can view these files from the web interface but cannot modify them; only replace them.

## The `verify` command

Instead of manually verifying, an assignment dashboard has a section telling the instructor user whether the assignment meets the specified criteria (starter code scores 0, answers score full marks, etc.).

## The `template` command

This is done manually from a button from an assignment's dashboard page. The instructor can navigate to the template repo if it has been created, or else press a button to create it based on the provided files if files have been provided.

## The `assign` command

Once a template repo has been created, the instructor may manually generate individual repos for each student. Or, if left ungenerated, each student will instantiate their own repository when they open the assignment for the first time. The latter method is necessary for teams.

The instructor can see from an assignment dashboard for which students a repo exists, for which a student has already made commits to the repo, and for which students no repo has yet been created.

## The `patch` command

This is also replicated with a button. Any changes to the assignment files must be manually deployed to student repos in the same way as the patch command.

## The `marks` command

When the page is loaded, for any student submission that has not yet been graded or has been updated (given another commit before the due date), the server grades the submission. If the grading script and solutions are updated, all the current grades are made stale. An instructor can manually request a regrade, which could be necessary for e.g. giving grace for late assignments. The instructor should be able to grade any commit in the commit history, and the latest commit before the due date is the default option.

## The `sheet` command

A download button for a Moodle worksheet is present on the assignment dashboard.
