# Security policy

## Supported versions

Security fixes go into the latest release only.

## Reporting a vulnerability

Please report vulnerabilities privately through GitHub private vulnerability reporting: open the repository's **Security** tab and choose **Report a vulnerability**. Do not open a public issue for a security problem.

Useful reports describe the problem and how to reproduce it. Never attach a real save file. If a crafted file triggers the problem, describe how to build that file, or attach a small synthetic file that holds no data from a real save.

fmsave is a hobby project maintained on a best-effort basis. Reports are acknowledged as soon as practical, and fixes are released as soon as they are ready.

## Scope

fmsave treats every save file as untrusted input. Its readers check bounds and cap sizes, and its file handling is fuzz tested. Examples of problems worth reporting:

- a crafted file that makes fmsave crash with something other than an fmsave error, hang, or use excessive memory or disk;
- an error message or diagnostic output that shows folder paths or text from a save that the documentation says stays out;
- any way for fmsave to write to a save, reach the network, or run code taken from a save.
