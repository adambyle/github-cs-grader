---
author: Adam Byle
---

# Environmental changes

## Virtual environment

Pre-expansion project, this repo does not make use of a Python virtual environment. It should do so and use pip for Python package management.

## Containerization

This project should use Docker for containerization purposes, for ease of using server-side tools as needed (I currently don't know to what extent Git related tools or the GitHub command line will need to be used on the server).

## Database

A SQLite database, or anything that may behave better with Flask, should be used on the server to keep track of users, courses, rosters, assignments, etc.
