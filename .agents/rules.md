# AI Agent Rules

## Mandatory Post-Change Verification

Every time you (the AI Agent) complete a task that involves modifying backend code, changing configuration files, updating Docker settings, or troubleshooting the application, you **MUST** verify that the stack is healthy before marking the task as complete or notifying the user.

To verify the stack, you must execute the checks defined in `.agents/workflows/verify_stack.md`.

Do not assume the application is running just because your code edit succeeded. Only consider your job done when you have definitive proof that the containers are up and the frontend/API are returning HTTP 200 OK.
