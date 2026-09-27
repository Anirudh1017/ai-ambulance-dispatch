$bat = "C:\Users\sanir\FOAI Project\run_server.bat"
$cwd = "C:\Users\sanir\FOAI Project"
$result = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
    CommandLine = "cmd.exe /c `"$bat`""
    CurrentDirectory = $cwd
}
Write-Output "Return value: $($result.ReturnValue), ProcessId: $($result.ProcessId)"
