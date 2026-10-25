@echo off
REM Push SRS Solar Daily Log to GitHub repository

echo Initializing Git repository...
git init
git branch -M main

echo Adding files...
git add .

echo Committing files...
git commit -m "feat: complete Phase P1, P2, and P3 for SRS Solar Daily Log"

echo Setting remote repository...
git remote remove origin 2>nul
git remote add origin https://github.com/JEEVANPRANAVRAVIKUMAR/SRS_report_genration.git

echo Pushing to GitHub...
git push -u origin main

echo Done!
pause
