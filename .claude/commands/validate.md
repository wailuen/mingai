# Implementation <> Validation Iteration
Use a team of agents. Always follow procedural directives with specialist agent for the right task.

1. Review your implementation with red team agents using playwright mcp (web) browser headed and marionette mcp (flutter) headed. This allow real test. Use multiple tab for each agent in the team. **NOT heeadless**
   - test all the workflows end-to-end. Always test the intent and if it fail, marked it as failed. **NEVER modify test script to past**
     - using backend api endpoints only
     - using frontend api endpoints only
     - using browser via Playwright MCP only
2. Ensure that the red team agents peruse `workspaces/<project-directory>/03-user-flows` and fully understand the detailed storyboard for each user
   - include tests written from these user workflow perspectives.
     - workflows must be extremely detailed
     - every step should include what is seen, what is clicked, what is expected, how to proceed, does it show value.
     - every transition between steps must be analyzed and evaluated as well
   - Focus on the intent, vision, and user requirements, and never naive technical assertions.
   - Every action and expectation from user must be evaluated against implementation
3. Ensure that you continuously engage the red team agents
   - Identify the root causes to the gaps
   - Implement the most optimal and elegant fix
   - Tests and ensure no regressions
   - Keep iterating until the red team agents find no more gaps/issues/improvements
4. Report all the detailed steps and results that you have taken in these validation and testing tasks

