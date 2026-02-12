@echo off
set "JAVA_HOME=C:\Program Files\Microsoft\jdk-17.0.18.8-hotspot"
echo Using JAVA_HOME=%JAVA_HOME%
call gradlew.bat assembleDebug > build_log.txt 2>&1
ifCode %ERRORLEVEL% NEQ 0 (
  echo Build failed with code %ERRORLEVEL%
  type build_log.txt
  exit /b %ERRORLEVEL%
)
echo Build succeeded
type build_log.txt
exit /b 0
