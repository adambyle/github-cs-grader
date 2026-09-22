---
author: Adam Byle
---

# Web expansion

This directory contains documentation and specification for an web-app-based expansion of the Coursekit project. Right now, this app is a standalone, local-only tool for generating student assignment repos based on an assignment template and providing immediate grading feedback based on the results of an autograder workflow. It is integrated with GitHub, replacing GitHub Classroom and other dispersed grading tools for CS courses following the sundown of GitHub Classroom.

Human-written markdown files like this one in this directory serve as highest-authority instructions and reference for the direction of the project. Agents may write their own specifications and notes in the `agent-spec` directory for planning and future reference.

Agents are to annotate the top of all outputted markdown with an authorship attribution.

Instead of running locally, this app will be deployed on university servers at a subdomain available to students and instructors.
