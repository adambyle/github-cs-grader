---
author: Adam Byle
---

# Goals of a web-based project

While the current version of this app runs locally and is tailored for a single instructor of a single course, we'd like this tool to work remotely. A user specifies at login whether they are a student or an instructor. They can switch if they make a mistake. They then authenticate with GitHub.

We will scrap the current web interface and build a new more sophisticated interface from scratch; however, this new interface should abide by the existing principles of web-based actions strongly mirroring those possible from the command line, at least from the instructor's point of view.

## User flow

### Instructor

An instructor can create a course that is reusable from semester to semester, and may instantiate this course with a roster of students for each given semester. In this way assignments don't have to be recreated between each semester, although the assignments may be modified. The instructor can also modify a course roster for a given semester in the event a student adds or drops a course.

Adding an assignment to a course involves uploading a template for that assignment. This template represents a basic GitHub repository that is duplicated for each student. If the instructor modifies the template, particularly files that are read-only for students, those changes are updated in each student repository. The instructor can control whether the assignments are open/visible.

An instructor can enable students to work on teams for certain assignments. The students will place themselves into teams. For team-based assignments, student repos are not generated for students until they are present on a team, at which point a repo is created for all of them and they are all given appropriate access.

The instructor can upload a markdown file for the assignment instructions which are visible to each student.

The instructor can view a dashboard of submissions for a certain assignment. They can see student-by-student statistics and important details, such as the number of errors on each commit, the time between commits and total time span between first and last commits, how many commits were past the due date, etc. The instructor can verify that no read-only files were modified. The dashboard returns the results of the autograding system and makes them visible to the instructor, and the instructor can export these grades as a worksheet for uploading to Moodle.

An instructor adds students to a certain semester roster for a course by specifying their GitHub usernmame. This roster is initially uploaded as a CSV.

### Student

A student automatically sees all courses they have been added to from their instructor. From there they can access assignments that are open to them, which will provide access to a template-generated repository they can modify for their assignment, as well as immediate grading feedback from the autograder scripts. A student can form teams with other students in their course for assignments that are team-enabled.

## Implementation details

Human developers on the project are most familiar with Python. A simple Python Flask server should do the trick. The frontend should be simple TypeScript and HTML. It does not have to be a single-page application.
