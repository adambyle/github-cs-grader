/*
 * app.js, {{course}} {{assignment}}: {{title}}
 *
 * REFERENCE SOLUTION. Lives in answers/ and is never published. `verify`
 * runs the suite against it and expects full marks.
 */

"use strict";

/** Return the sum of a and b. */
function add(a, b) {
  return a + b;
}

/** Return "Hello, <name>!"; when no name is given, greet the world. */
function greet(name = "world") {
  return `Hello, ${name}!`;
}

module.exports = { add, greet };
