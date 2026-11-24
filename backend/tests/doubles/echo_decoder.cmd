@echo off
rem Windows wrapper for the portable decoder test double (AHAIET-048).
rem Invokes the Python helper with the same interpreter family the
rem test suite uses; %~dp0 is this script's directory.
python "%~dp0echo_decoder.py" %*
