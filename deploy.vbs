' تشغيل deploy.bat في نافذة CMD مرئية (انقر مرتين على هذا الملف اذا deploy.bat لا يظهر)
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
sh.Run "cmd.exe /k deploy.bat", 1, False
