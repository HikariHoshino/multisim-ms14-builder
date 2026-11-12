# 用法：check.ps1 <文件.ms14>，打开并列出元件，结束时只关本脚本启动的 Multisim 进程
$before = @(Get-Process multisim -ErrorAction SilentlyContinue | ForEach-Object { $_.Id })
$app = New-Object -ComObject MultisimInterface.MultisimApp
$app.Connect()
$c = $app.OpenFile($args[0])
"name: " + $c.CircuitName
$names = $c.EnumComponents(0)
$names
$app.Disconnect()
# 仿真服务进程（/SimServer）会在主进程退出前后才冒出来，隔两秒再查两轮，免得留下孤儿进程
foreach ($i in 1..3) { Get-Process multisim -ErrorAction SilentlyContinue | Where-Object { $before -notcontains $_.Id } | Stop-Process -Force; Start-Sleep 2 }
